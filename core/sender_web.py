from __future__ import annotations

from typing import Any

from astrbot.api import logger
from astrbot.api.web import error_response, json_response, request

from .sender import SUPPORTED_PLATFORMS

PAGE_SIZE = 50
MAX_RESOLVE_IDS = 100


def umo_sender_search(context: Any) -> Any:
    """返回 AstrBot 的会话发送者查询函数；v4.29.4 之前没有记录，返回 None。"""
    get_db = getattr(context, "get_db", None)
    db = get_db() if get_db else None
    return getattr(db, "get_umo_senders", None)


def session_name(alias: Any) -> str:
    if alias is None:
        return ""
    return alias.user_alias or alias.auto_name or ""


class SenderWebApi:
    """按钮工作台“选择用户”弹窗的后台接口，数据来自 AstrBot 记录的会话发送者。"""

    def __init__(self, plugin: Any) -> None:
        self.plugin = plugin

    def routes(self) -> list[tuple[str, Any, list[str], str]]:
        return [("senders", self.senders, ["GET"], "搜索已记录的 QQ 用户")]

    def _search_func(self) -> Any:
        # AstrBot v4.29.4 起才记录会话发送者，旧版本只能手动填写 OpenID。
        return umo_sender_search(self.plugin.context)

    def _qq_platform_ids(self) -> set[str]:
        return {
            platform.meta().id
            for platform in self.plugin.context.platform_manager.get_insts()
            if platform.meta().name in SUPPORTED_PLATFORMS
        }

    @staticmethod
    def _item(sender: Any, alias: Any) -> dict[str, Any]:
        umo = str(sender.umo or "")
        parts = umo.split(":", 2)
        return {
            "sender_id": str(sender.sender_id),
            "sender_name": sender.sender_name or "",
            "umo": umo,
            "platform": parts[0],
            "group": len(parts) > 1 and parts[1] == "GroupMessage",
            "session_name": session_name(alias),
        }

    async def senders(self):
        search_func = self._search_func()
        if search_func is None:
            return json_response(
                {"supported": False, "senders": [], "page": 1, "has_more": False}
            )
        ids_text = str(request.query.get("ids", "") or "")
        ids = [item for item in dict.fromkeys(ids_text.split(",")) if item][
            :MAX_RESOLVE_IDS
        ]
        try:
            page = max(1, int(request.query.get("page", 1)))
        except (TypeError, ValueError):
            page = 1
        try:
            if ids:
                records = await search_func("", len(ids), ids, offset=0)
                has_more = False
            else:
                records = await search_func(
                    str(request.query.get("search", "") or "").strip()[:512],
                    PAGE_SIZE + 1,
                    None,
                    offset=(page - 1) * PAGE_SIZE,
                )
                has_more = len(records) > PAGE_SIZE
                records = records[:PAGE_SIZE]
        except Exception:
            logger.exception("[QQ官Bot按钮] 读取已记录用户失败")
            return error_response("无法加载用户，可直接添加输入的 OpenID", status_code=500)
        # 指定用户权限只对 QQ 官方机器人有效，其他平台的用户 ID 不展示。
        platforms = self._qq_platform_ids()
        senders = [
            self._item(sender, alias)
            for sender, alias in records
            if str(sender.umo or "").split(":", 1)[0] in platforms
        ]
        return json_response(
            {"supported": True, "senders": senders, "page": page, "has_more": has_more}
        )
