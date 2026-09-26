from __future__ import annotations

import asyncio
import time
from collections.abc import Callable
from typing import Any

from .security import parse_action_token
from .sender import SUPPORTED_PLATFORMS


class QQOfficialCallbackHandler:
    """Attach native QQ button callbacks to AstrBot's existing botpy clients."""

    def __init__(self, plugin: Any, log: Callable[[str], None]) -> None:
        self.plugin = plugin
        self.log = log
        self._bindings: dict[int, tuple[Any, Any, Any]] = {}
        self._seen: dict[str, float] = {}
        self._lock = asyncio.Lock()

    def bind_available(self) -> None:
        platforms = [
            platform
            for platform in self.plugin.context.platform_manager.get_insts()
            if platform.meta().name in SUPPORTED_PLATFORMS
        ]
        active_clients = {
            id(platform.get_client() if hasattr(platform, "get_client") else platform.client)
            for platform in platforms
        }
        for key in list(self._bindings):
            if key not in active_clients:
                self._unbind_client(key)

        for platform in platforms:
            client = platform.get_client() if hasattr(platform, "get_client") else platform.client
            key = id(client)
            if key in self._bindings:
                continue

            previous = getattr(client, "on_interaction_create", None)

            async def receive(interaction: Any, *, _client=client, _previous=previous, _platform=platform) -> None:
                if await self.handle(_client.api, interaction, platform=_platform):
                    return
                if _previous is not None:
                    await _previous(interaction)

            client.on_interaction_create = receive
            self._bindings[key] = (client, previous, receive)
            if platform.meta().name == "qq_official":
                platform.intents.interaction = True
                client.intents = platform.intents.value
                if getattr(client, "_active_websockets", None):
                    self.log("[QQ官Bot按钮] 原生回调已绑定；请重载 QQ 平台以更新 WebSocket intent。")
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
            (button for row in preset["rows"] for button in row if button["id"] == button_id),
            None,
        )

    @staticmethod
    def _allowed(interaction: Any, button: dict[str, Any]) -> bool:
        permission = button["permission"]
        if permission["type"] == 0:
            data = getattr(interaction, "data", None)
            user_id = (
                getattr(interaction, "group_member_openid", None)
                or getattr(interaction, "user_openid", None)
                or getattr(getattr(data, "resolved", None), "user_id", None)
            )
            return bool(user_id and str(user_id) in permission["user_ids"])
        # QQ enforces administrator and channel-role permissions before dispatch.
        return permission["type"] in {1, 2, 3}

    async def _claim(self, interaction_id: str) -> bool:
        async with self._lock:
            now = time.monotonic()
            self._seen = {key: when for key, when in self._seen.items() if now - when < 300}
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
        if not await self._claim(interaction_id):
            await api.on_interaction_result(interaction_id, 3)
            return True

        parsed = parse_action_token(self.plugin.storage.signing_secret, button_data[6:])
        preset = self.plugin.storage.get(parsed[0]) if parsed else None
        button = self._find_button(preset, parsed[1]) if preset and parsed else None
        if not preset or not preset["enabled"] or not button:
            await api.on_interaction_result(interaction_id, 1)
            return True
        action = button["action"]
        if action["type"] not in {"callback_text", "callback_preset", "callback_command"}:
            await api.on_interaction_result(interaction_id, 1)
            return True
        if not self._allowed(interaction, button):
            await api.on_interaction_result(interaction_id, 4)
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
                await self.plugin.sender.send_interaction_text(api, interaction, action["value"])
            elif action["type"] == "callback_command":
                from .commands import build_command_event

                event = build_command_event(self.plugin.context, platform, interaction, action["value"])
                platform.commit_event(event)
            else:
                await self.plugin.sender.send_interaction(api, interaction, target)
        except Exception as exc:
            self.log(f"[QQ官Bot按钮] 原生回调已确认，但动作执行失败：{exc}")
            if action["type"] == "callback_command":
                await self.plugin.sender.send_interaction_text(
                    api, interaction, f"回调指令未能提交：{exc}"
                )
        return True
