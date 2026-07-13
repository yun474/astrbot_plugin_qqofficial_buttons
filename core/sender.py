from __future__ import annotations

import random
from collections.abc import Awaitable, Callable
from functools import partial
from typing import Any

from .security import create_action_token


SUPPORTED_PLATFORMS = {"qq_official", "qq_official_webhook"}
MESSAGE_MODES = {"auto", "markdown", "content"}
MARKDOWN_NOT_ALLOWED_ERROR = "不允许发送原生 markdown"


class QQOfficialButtonSender:
    """Build and send QQ Official inline keyboards for the current event."""

    def __init__(
        self,
        *,
        signing_secret: str,
        action_command: str,
        message_mode: str = "auto",
        log: Callable[[str], None] | None = None,
    ) -> None:
        self.signing_secret = signing_secret
        self.action_command = action_command.strip() or "/qqbtn_action"
        self.message_mode = message_mode if message_mode in MESSAGE_MODES else "auto"
        self.log = log or (lambda _message: None)

    @staticmethod
    def is_supported_event(event: Any) -> bool:
        try:
            return event.get_platform_name() in SUPPORTED_PLATFORMS
        except Exception:
            return False

    def build_keyboard(self, preset: dict[str, Any]) -> dict[str, Any]:
        rows = []
        for row in preset["rows"]:
            buttons = []
            for button in row:
                action_spec = button["action"]
                action_type = action_spec["type"]
                if action_type == "link":
                    qq_action: dict[str, Any] = {
                        "type": 0,
                        "data": action_spec["value"],
                        "permission": self._permission(button["permission"]),
                    }
                elif action_type in {"send_text", "show_preset"}:
                    token = create_action_token(
                        self.signing_secret, preset["id"], button["id"]
                    )
                    qq_action = {
                        "type": 2,
                        "data": f"{self.action_command} {token}",
                        "enter": True,
                        "permission": self._permission(button["permission"]),
                    }
                else:
                    qq_action = {
                        "type": 2,
                        "data": action_spec["value"],
                        "enter": action_type == "command",
                        "permission": self._permission(button["permission"]),
                    }
                # QQ 客户端不支持按钮时会展示这段提示，方便区分能力问题。
                qq_action["unsupport_tips"] = "当前 QQ 版本暂不支持此按钮"
                buttons.append(
                    {
                        "id": button["id"],
                        "render_data": {
                            "label": button["label"],
                            "visited_label": button["visited_label"],
                            "style": button["style"],
                        },
                        "action": qq_action,
                    }
                )
            rows.append({"buttons": buttons})
        return {"content": {"rows": rows}}

    @staticmethod
    def _permission(permission: dict[str, Any]) -> dict[str, Any]:
        result: dict[str, Any] = {"type": permission["type"]}
        if permission["type"] == 0 and permission.get("user_ids"):
            result["specify_user_ids"] = permission["user_ids"]
        if permission["type"] == 3 and permission.get("role_ids"):
            result["specify_role_ids"] = permission["role_ids"]
        return result

    @staticmethod
    def _result_summary(result: Any) -> str:
        if result is None:
            return "None"
        message_id = getattr(result, "id", None)
        if message_id:
            return f"{type(result).__name__}(id={message_id})"
        if isinstance(result, dict):
            return f"dict(id={result.get('id') or result.get('message_id') or '-'})"
        return type(result).__name__

    @staticmethod
    async def _send_with_active_retry(
        send_func: Callable[..., Awaitable[Any]],
        payload: dict[str, Any],
    ) -> tuple[Any, dict[str, Any]]:
        try:
            return await send_func(**payload), payload
        except Exception:
            if not payload.get("msg_id"):
                raise
            active_payload = payload.copy()
            active_payload.pop("msg_id", None)
            return await send_func(**active_payload), active_payload

    async def send(self, event: Any, preset: dict[str, Any]) -> str:
        if not self.is_supported_event(event):
            raise RuntimeError("当前会话不是 QQ 官方 Bot 会话")
        raw = getattr(getattr(event, "message_obj", None), "raw_message", None)
        if raw is None:
            raise RuntimeError("无法读取 QQ 官方消息上下文")
        bot = getattr(event, "bot", None)
        api = getattr(bot, "api", None)
        if api is None:
            raise RuntimeError("QQ 官方 Bot API 尚未就绪")

        keyboard = self.build_keyboard(preset)
        content = preset.get("content") or "请选择："
        message_id = str(
            getattr(getattr(event, "message_obj", None), "message_id", None)
            or getattr(raw, "id", None)
            or ""
        )
        group_openid = getattr(raw, "group_openid", None)
        author = getattr(raw, "author", None)
        user_openid = getattr(author, "user_openid", None)
        channel_id = getattr(raw, "channel_id", None)
        guild_id = getattr(raw, "guild_id", None)
        is_v2 = bool(group_openid or user_openid)

        send_func: Callable[..., Awaitable[Any]]
        if group_openid:
            send_func = partial(api.post_group_message, group_openid=group_openid)
            scene = "群聊"
        elif user_openid:
            send_func = partial(api.post_c2c_message, openid=user_openid)
            scene = "C2C 私聊"
        elif channel_id:
            send_func = partial(api.post_message, channel_id=channel_id)
            scene = "频道"
        elif guild_id:
            send_func = partial(api.post_dms, guild_id=guild_id)
            scene = "频道私信"
        else:
            raise RuntimeError("无法识别 QQ 官方消息场景")

        common: dict[str, Any] = {
            "msg_id": message_id or None,
            "keyboard": keyboard,
        }
        if is_v2:
            common["msg_seq"] = random.randint(1, 9999)

        mode = "markdown" if self.message_mode == "auto" else self.message_mode
        payload = common | {"markdown": {"content": content}}
        if is_v2:
            payload["msg_type"] = 2
        if mode == "content":
            payload.pop("markdown")
            payload["content"] = content
            if is_v2:
                payload["msg_type"] = 0

        try:
            result, sent_payload = await self._send_with_active_retry(
                send_func, payload
            )
        except Exception as exc:
            if self.message_mode != "auto" or MARKDOWN_NOT_ALLOWED_ERROR not in str(
                exc
            ):
                raise
            self.log("[QQ官Bot按钮] 原生 Markdown 未获授权，回退到 content 模式。")
            fallback = common | {"content": content}
            if is_v2:
                fallback["msg_type"] = 0
            # 上一次已经尝试过被动和主动发送，回退时直接走主动消息。
            fallback.pop("msg_id", None)
            result, sent_payload = await self._send_with_active_retry(
                send_func, fallback
            )
            mode = "content-fallback"

        row_count = len(keyboard["content"]["rows"])
        button_count = sum(len(row["buttons"]) for row in keyboard["content"]["rows"])
        passive = "msg_id" in sent_payload
        self.log(
            "[QQ官Bot按钮] 发送接口已返回："
            f"scene={scene}, mode={mode}, passive={passive}, "
            f"rows={row_count}, buttons={button_count}, "
            f"result={self._result_summary(result)}。"
            "若正文出现但按钮仍缺失，请检查 QQ 开放平台的消息按钮/内嵌键盘权限。"
        )

        try:
            event._has_send_oper = True
        except Exception:
            pass
        return scene
