from __future__ import annotations

import random
from typing import Any

from .security import create_action_token


SUPPORTED_PLATFORMS = {"qq_official", "qq_official_webhook"}


class QQOfficialButtonSender:
    """Build and send QQ Official inline keyboards for the current event."""

    def __init__(self, *, signing_secret: str, action_command: str) -> None:
        self.signing_secret = signing_secret
        self.action_command = action_command.strip() or "/qqbtn_action"

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
        common = {
            "content": content,
            "msg_id": message_id or None,
            "keyboard": keyboard,
        }
        group_openid = getattr(raw, "group_openid", None)
        author = getattr(raw, "author", None)
        user_openid = getattr(author, "user_openid", None)
        channel_id = getattr(raw, "channel_id", None)
        guild_id = getattr(raw, "guild_id", None)

        if group_openid:
            await api.post_group_message(
                group_openid=group_openid,
                msg_type=0,
                msg_seq=random.randint(1, 9999),
                **common,
            )
            scene = "群聊"
        elif user_openid:
            await api.post_c2c_message(
                openid=user_openid,
                msg_type=0,
                msg_seq=random.randint(1, 9999),
                **common,
            )
            scene = "C2C 私聊"
        elif channel_id:
            await api.post_message(channel_id=channel_id, **common)
            scene = "频道"
        elif guild_id:
            await api.post_dms(guild_id=guild_id, **common)
            scene = "频道私信"
        else:
            raise RuntimeError("无法识别 QQ 官方消息场景")

        try:
            event._has_send_oper = True
        except Exception:
            pass
        return scene
