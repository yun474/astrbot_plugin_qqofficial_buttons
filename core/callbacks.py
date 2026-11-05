from __future__ import annotations

import asyncio
import time
from collections.abc import Callable
from html import escape
from typing import Any

from .commands import send_interaction_reply
from .deny import mention_segments, pick_deny_reply
from .models import PERMISSION_BOT_ADMIN, PERMISSION_TRIGGER, plugin_intercepts
from .security import action_token_user, button_token_matches, parse_action_token
from .sender import SUPPORTED_PLATFORMS


class QQOfficialCallbackHandler:
    """Attach native QQ button callbacks to AstrBot's existing botpy clients."""

    def __init__(self, plugin: Any, log: Callable[[str], None]) -> None:
        self.plugin = plugin
        self.log = log
        self._bindings: dict[int, tuple[Any, Any, Any]] = {}
        self._seen: dict[str, float] = {}
        self._llm_clicks: dict[str, float] = {}
        self._lock = asyncio.Lock()

    def bind_available(self) -> None:
        platforms = [
            platform
            for platform in self.plugin.context.platform_manager.get_insts()
            if platform.meta().name in SUPPORTED_PLATFORMS
        ]
        active_clients = {
            id(
                platform.get_client()
                if hasattr(platform, "get_client")
                else platform.client
            )
            for platform in platforms
        }
        for key in list(self._bindings):
            if key not in active_clients:
                self._unbind_client(key)

        for platform in platforms:
            client = (
                platform.get_client()
                if hasattr(platform, "get_client")
                else platform.client
            )
            key = id(client)
            if key in self._bindings:
                continue

            previous = getattr(client, "on_interaction_create", None)

            async def receive(
                interaction: Any,
                *,
                _client=client,
                _previous=previous,
                _platform=platform,
            ) -> None:
                if id(_client) in self._bindings and await self.handle(
                    _client.api, interaction, platform=_platform
                ):
                    return
                if _previous is not None:
                    await _previous(interaction)

            client.on_interaction_create = receive
            self._bindings[key] = (client, previous, receive)
            if platform.meta().name == "qq_official":
                platform.intents.interaction = True
                client.intents = platform.intents.value
                if getattr(client, "_active_websockets", None):
                    self.log(
                        "[QQ官Bot按钮] 原生回调已绑定；请重载 QQ 平台以更新 WebSocket intent。"
                    )
            self.log(f"[QQ官Bot按钮] 已绑定 {platform.meta().id} 的原生按钮回调。")

    def _unbind_client(self, key: int) -> None:
        client, previous, receive = self._bindings.pop(key)
        if getattr(client, "on_interaction_create", None) is receive:
            if previous is None:
                del client.on_interaction_create
            else:
                client.on_interaction_create = previous

    def unbind(self) -> None:
        for key in list(self._bindings):
            self._unbind_client(key)

    @staticmethod
    def _find_button(preset: dict[str, Any], button_id: str) -> dict[str, Any] | None:
        return next(
            (
                button
                for row in preset["rows"]
                for button in row
                if button["id"] == button_id
            ),
            None,
        )

    def _allowed(
        self,
        interaction: Any,
        button: dict[str, Any],
        *,
        token_user: str = "",
        platform: Any = None,
    ) -> bool:
        permission = button["permission"]
        permission_type = permission["type"]
        user = self.plugin.sender.trigger_user_id(interaction)
        if permission_type == 0:
            return bool(user) and user in permission["user_ids"]
        if permission_type == PERMISSION_TRIGGER:
            return bool(token_user) and user == token_user
        if permission_type == PERMISSION_BOT_ADMIN:
            session = self.plugin.callback_session(platform, interaction)
            return session is not None and self.plugin.is_bot_admin(user, session[1])
        # QQ enforces administrator and channel-role permissions before dispatch.
        return permission_type in {1, 2, 3}

    def _click_key(self, api: Any, interaction: Any) -> str:
        """区分“哪个机器人、哪个会话、谁点的”，用于冷却计时。"""
        group = getattr(interaction, "group_openid", None) or getattr(
            interaction, "channel_id", None
        )
        user = self.plugin.sender.trigger_user_id(interaction)
        return f"{id(api)}:{group or ''}:{user}"

    async def _reply(
        self, api: Any, interaction: Any, platform: Any, segments: list[str | None]
    ) -> None:
        """回复点击；segments 中的 None 表示艾特点击者。"""
        if platform is not None:
            # 与 AstrBot 普通回复同路径：默认 Markdown，艾特由框架转换。
            await send_interaction_reply(platform, interaction, segments)
            return
        # 找不到平台适配器时直接调用接口发送纯文本。
        user = self.plugin.sender.trigger_user_id(interaction)
        mention = f'<qqbot-at-user id="{escape(user, quote=True)}" />' if user else ""
        text = "".join(mention if part is None else part for part in segments)
        await self.plugin.sender.send_interaction_text(api, interaction, text.strip())

    async def _deny(
        self,
        api: Any,
        interaction: Any,
        interaction_id: str,
        button: dict[str, Any],
        platform: Any = None,
    ) -> None:
        # 由 QQ 客户端拦截的按钮能到这里只是兜底校验，保持旧版直接回执“无权限”。
        reply = pick_deny_reply(button) if plugin_intercepts(button) else ""
        cooldown = getattr(self.plugin, "deny_cooldown", None)
        if reply and cooldown is not None and cooldown.cooling(
            self._click_key(api, interaction)
        ):
            reply = ""
        if not reply:
            await api.on_interaction_result(interaction_id, 4)
            return
        # 先回执成功再发拒绝语，避免 QQ 的“无权限”提示和拒绝语叠在一起。
        await api.on_interaction_result(interaction_id, 0)
        try:
            await self._reply(api, interaction, platform, mention_segments(reply))
        except Exception as exc:
            self.log(f"[QQ官Bot按钮] 拒绝语发送失败：{exc}")

    def _llm_cooling(self, api: Any, interaction: Any) -> bool:
        """同一会话里同一个人在冷却时间内重复点击直接调用，只放行第一次。"""
        cooldown = getattr(self.plugin, "llm_cooldown", 0)
        if cooldown <= 0:
            return False
        key = self._click_key(api, interaction)
        now = time.monotonic()
        self._llm_clicks = {
            item: when
            for item, when in self._llm_clicks.items()
            if now - when < cooldown
        }
        if key in self._llm_clicks:
            return True
        self._llm_clicks[key] = now
        return False

    async def _claim(self, interaction_id: str) -> bool:
        async with self._lock:
            now = time.monotonic()
            self._seen = {
                key: when for key, when in self._seen.items() if now - when < 300
            }
            if interaction_id in self._seen:
                return False
            self._seen[interaction_id] = now
            return True

    async def handle(self, api: Any, interaction: Any, *, platform: Any = None) -> bool:
        data = getattr(getattr(interaction, "data", None), "resolved", None)
        button_data = str(getattr(data, "button_data", None) or "")
        if not button_data.startswith("qqbtn:"):
            return False

        interaction_id = str(getattr(interaction, "id", None) or "")
        if not interaction_id:
            self.log("[QQ官Bot按钮] 收到缺少 interaction id 的回调，无法回执。")
            return True
        if not getattr(self.plugin, "allow_functions", True):
            await api.on_interaction_result(interaction_id, 4)
            return True
        if not await self._claim(f"{id(api)}:{interaction_id}"):
            await api.on_interaction_result(interaction_id, 3)
            return True

        parsed = parse_action_token(self.plugin.storage.signing_secret, button_data[6:])
        preset = self.plugin.storage.get(parsed[0]) if parsed else None
        button = self._find_button(preset, parsed[1]) if preset and parsed else None
        if (
            not preset
            or not preset["enabled"]
            or not button
            or not button_token_matches(
                self.plugin.storage.signing_secret,
                button_data[6:],
                preset["id"],
                button,
            )
        ):
            await api.on_interaction_result(interaction_id, 1)
            return True
        action = button["action"]
        if action["type"] not in {
            "callback_text",
            "callback_preset",
            "callback_command",
            "callback_llm",
        }:
            await api.on_interaction_result(interaction_id, 1)
            return True
        token_user = action_token_user(
            self.plugin.storage.signing_secret, button_data[6:]
        )
        # 先确认插件在该会话可用，停用插件的会话里不发拒绝语。
        if platform is not None and not await self.plugin.callback_allowed(
            platform, interaction
        ):
            await api.on_interaction_result(interaction_id, 4)
            return True
        if not self._allowed(
            interaction, button, token_user=token_user, platform=platform
        ):
            await self._deny(api, interaction, interaction_id, button, platform)
            return True
        if action["type"] == "callback_llm" and self._llm_cooling(api, interaction):
            await api.on_interaction_result(interaction_id, 2)
            return True

        target = None
        if action["type"] == "callback_preset":
            target = self.plugin.storage.get(action["value"])
            if not target or not target["enabled"]:
                await api.on_interaction_result(interaction_id, 1)
                return True

        await api.on_interaction_result(interaction_id, 0)
        try:
            if action["type"] == "callback_text":
                await self.plugin.sender.send_interaction_text(
                    api, interaction, action["value"]
                )
            elif action["type"] == "callback_llm":
                from .commands import build_llm_event, render_prompt

                if platform is None:
                    raise RuntimeError("找不到对应的 QQ 官方平台适配器")
                prompt = render_prompt(
                    action["value"],
                    user=self.plugin.sender.trigger_user_id(interaction),
                )
                # 以插件内部指令进入 AstrBot 流水线，人格、记忆、回复与报错都由框架处理。
                platform.commit_event(
                    build_llm_event(
                        self.plugin.context,
                        platform,
                        interaction,
                        prompt,
                        label=button["label"],
                        mention=action.get("at_user") is True,
                    )
                )
            elif action["type"] == "callback_command":
                from .commands import build_command_event

                event = build_command_event(
                    self.plugin.context, platform, interaction, action["value"]
                )
                platform.commit_event(event)
            else:
                await self.plugin.sender.send_interaction(api, interaction, target)
        except Exception as exc:
            self.log(f"[QQ官Bot按钮] 原生回调已确认，但动作执行失败：{exc}")
            notice = {
                "callback_command": f"回调指令未能提交：{exc}",
                "callback_llm": f"直接调用未能提交：{exc}",
            }.get(action["type"])
            if notice:
                try:
                    await self.plugin.sender.send_interaction_text(
                        api, interaction, notice
                    )
                except Exception as send_exc:
                    self.log(f"[QQ官Bot按钮] 回调错误提示发送失败：{send_exc}")
        return True
