from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

from astrbot.api import logger
from astrbot.api.web import error_response, json_response, request

from .bots import MANUAL_PREFIX, BotError
from .media import MediaError
from .panels import (
    DESC_WIDTH,
    MAX_ITEMS,
    MAX_PANELS,
    NAME_WIDTH,
    REMARK_WIDTH,
    SCOPES,
    TARGET_FIELDS,
    PanelError,
    create_panel,
    delete_panel,
    get_panel,
    list_panels,
    normalize_panel,
    update_panel,
)
from .sender_web import PAGE_SIZE, session_name, umo_sender_search

# 选择生效对象时从会话记录里找：单聊取私聊过的用户，群聊取待过的群。
SCENE_MESSAGE_TYPES = {"c2c": "FriendMessage", "group": "GroupMessage"}
# 一次最多扫描的发送者记录数，够覆盖常见规模，再多就请手动添加。
TARGET_SCAN_LIMIT = 1000
MAX_RESOLVE_IDS = 100


async def group_sessions(db: Any, prefix: str, limit: int) -> list[tuple[Any, Any]]:
    """直接按会话列出群，最近有新成员说话或有人改名的群排前面（AstrBot 只在这两种情况下更新记录时间）。

    AstrBot 的发送者查询按“平台 + 发送者”去重，而同一个机器人下同一个人在各群的 ID 相同，
    他去过的旧群会被挤掉；这里按会话分组查，不会漏群。
    """
    from sqlalchemy import func
    from sqlmodel import col, select

    from astrbot.core.db.po import UmoSender

    query = (
        select(UmoSender.umo)
        .where(col(UmoSender.umo).startswith(prefix, autoescape=True))
        .group_by(UmoSender.umo)
        .order_by(func.max(UmoSender.updated_at).desc())
        .limit(limit)
    )
    async with db.get_db() as session:
        umos = [row[0] for row in (await session.execute(query)).all()]
    get_aliases = getattr(db, "get_umo_aliases", None)
    aliases = {alias.umo: alias for alias in await get_aliases(umos)} if get_aliases and umos else {}
    return [
        (SimpleNamespace(umo=umo, sender_id="", sender_name=""), aliases.get(umo))
        for umo in umos
    ]


class PanelsWebApi:
    """工作台“指令面板”页面的后台接口，数据直接读写 QQ 服务器。"""

    def __init__(self, plugin: Any) -> None:
        self.plugin = plugin

    def routes(self) -> list[tuple[str, Any, list[str], str]]:
        return [
            ("panels/state", self.state, ["GET"], "读取指令面板页面数据"),
            ("panels/list", self.list_all, ["GET"], "列出 QQ 指令面板"),
            ("panels/detail", self.detail, ["GET"], "读取 QQ 指令面板详情"),
            ("panels/save", self.save, ["POST"], "保存 QQ 指令面板"),
            ("panels/delete", self.delete, ["POST"], "删除 QQ 指令面板"),
            ("panels/targets", self.targets, ["GET"], "搜索指令面板可选的用户或群"),
        ]

    def _http(self, bot_id: Any) -> Any:
        return self.plugin.bots.http(str(bot_id or ""))

    @staticmethod
    def _failed(action: str, exc: Exception):
        if isinstance(exc, (PanelError, MediaError)):
            return error_response(str(exc), status_code=400)
        logger.exception(f"[QQ官Bot按钮] 指令面板{action}失败")
        return error_response(f"{action}失败：{exc}", status_code=500)

    async def state(self):
        return json_response(
            {
                "limits": {
                    "max_panels": MAX_PANELS,
                    "max_items": MAX_ITEMS,
                    "name_width": NAME_WIDTH,
                    "desc_width": DESC_WIDTH,
                    "remark_width": REMARK_WIDTH,
                },
                "targets_supported": umo_sender_search(self.plugin.context) is not None,
            }
        )

    async def list_all(self):
        # QQ 要求按场景分别查询；某个场景查不了（比如没开通频道）时单独报错，不影响其他场景。
        try:
            http = self._http(request.query.get("bot", ""))
        except Exception as exc:
            return self._failed("读取", exc)
        results = await asyncio.gather(
            *(list_panels(http, scope) for scope in SCOPES), return_exceptions=True
        )
        # 凭证失效时每个场景都会失败，整体报一次，不在四个场景里重复显示。
        bot_error = next((r for r in results if isinstance(r, BotError)), None)
        if bot_error is not None:
            return self._failed("读取", bot_error)
        scopes: dict[str, dict[str, Any]] = {}
        for scope, result in zip(SCOPES, results):
            if isinstance(result, PanelError):
                scopes[scope] = {"records": [], "error": str(result)}
            elif isinstance(result, BaseException):
                logger.error(f"[QQ官Bot按钮] 读取 {scope} 指令面板失败：{result!r}")
                scopes[scope] = {"records": [], "error": f"读取失败：{result}"}
            else:
                scopes[scope] = {"records": result, "error": ""}
        return json_response({"scopes": scopes})

    async def detail(self):
        panel_id = str(request.query.get("id", "") or "").strip()
        if not panel_id:
            return error_response("缺少面板 ID", status_code=400)
        try:
            http = self._http(request.query.get("bot", ""))
            return json_response({"panel": await get_panel(http, panel_id)})
        except Exception as exc:
            return self._failed("读取", exc)

    async def save(self):
        payload = await request.json(default={})
        if not isinstance(payload, dict):
            return error_response("请求内容必须是对象", status_code=400)
        try:
            http = self._http(payload.get("bot"))
            panel_id = str(payload.get("panel_id") or "").strip()
            if panel_id:
                # 场景和生效范围创建后不能改，以 QQ 上的现状为准。
                current = await get_panel(http, panel_id)
                data = normalize_panel(
                    payload
                    | {
                        "scope": current.get("scope"),
                        "target_type": current.get("target_type") or "all",
                    }
                )
                warning = await update_panel(http, panel_id, data, current)
            else:
                data = normalize_panel(payload)
                panel_id, warning = await create_panel(http, data)
            return json_response({"panel_id": panel_id, "warning": warning})
        except Exception as exc:
            return self._failed("保存", exc)

    async def delete(self):
        payload = await request.json(default={})
        if not isinstance(payload, dict) or not payload.get("panel_id"):
            return error_response("缺少面板 ID", status_code=400)
        try:
            await delete_panel(
                self._http(payload.get("bot")), str(payload["panel_id"]).strip()
            )
            return json_response({"deleted": True})
        except Exception as exc:
            return self._failed("删除", exc)

    @staticmethod
    def _target(scope: str, prefix: str, sender: Any, alias: Any) -> dict[str, Any]:
        umo = str(sender.umo or "")
        if scope == "c2c":
            target_id, name = str(sender.sender_id), sender.sender_name or ""
        else:
            # 开启会话隔离时会话 ID 是“用户_群”，OpenID 不含下划线，取最后一段即为群。
            target_id, name = umo[len(prefix) :].rsplit("_", 1)[-1], ""
        return {
            "sender_id": target_id,
            "sender_name": name,
            "umo": umo,
            "group": scope == "group",
            "session_name": session_name(alias),
        }

    async def targets(self):
        """按机器人和场景列出可选对象，格式与“选择用户”接口一致，方便复用弹窗。"""
        search_func = umo_sender_search(self.plugin.context)
        empty = {"supported": False, "senders": [], "page": 1, "has_more": False}
        if search_func is None:
            return json_response(empty)
        scope = str(request.query.get("scope", "") or "")
        bot = str(request.query.get("bot", "") or "")
        if scope not in TARGET_FIELDS or not bot:
            return error_response("缺少机器人或场景", status_code=400)
        if bot.startswith(MANUAL_PREFIX):
            # 手动添加的机器人不收消息，没有会话记录，页面会提示直接填 ID。
            return json_response(empty)
        prefix = f"{bot}:{SCENE_MESSAGE_TYPES[scope]}:"
        try:
            if scope == "group":
                records = await group_sessions(
                    self.plugin.context.get_db(), prefix, TARGET_SCAN_LIMIT
                )
            else:
                # 私聊每个用户一个会话，按发送者去重不会漏人；会话 ID 也参与搜索，用前缀限定范围。
                records = await search_func(prefix, TARGET_SCAN_LIMIT, None, offset=0)
        except Exception:
            logger.exception("[QQ官Bot按钮] 读取指令面板可选对象失败")
            return error_response("无法加载记录，可直接添加输入的 ID", status_code=500)

        found: dict[str, dict[str, Any]] = {}
        for sender, alias in records:
            if not str(sender.umo or "").startswith(prefix):
                continue
            item = self._target(scope, prefix, sender, alias)
            if item["sender_id"] and item["sender_id"] not in found:
                found[item["sender_id"]] = item

        ids_text = str(request.query.get("ids", "") or "")
        if ids_text:
            ids = [item for item in dict.fromkeys(ids_text.split(",")) if item]
            matched = [found[i] for i in ids[:MAX_RESOLVE_IDS] if i in found]
            return json_response(
                {"supported": True, "senders": matched, "page": 1, "has_more": False}
            )

        keyword = str(request.query.get("search", "") or "").strip().lower()
        items = [
            item
            for item in found.values()
            if not keyword
            or any(
                keyword in str(item[key]).lower()
                for key in ("sender_id", "sender_name", "session_name")
            )
        ]
        try:
            page = max(1, int(request.query.get("page", 1)))
        except (TypeError, ValueError):
            page = 1
        start = (page - 1) * PAGE_SIZE
        return json_response(
            {
                "supported": True,
                "senders": items[start : start + PAGE_SIZE],
                "page": page,
                "has_more": len(items) > start + PAGE_SIZE,
            }
        )
