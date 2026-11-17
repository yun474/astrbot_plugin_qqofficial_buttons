from __future__ import annotations

from typing import Any

from astrbot.api import logger
from astrbot.api.web import error_response, json_response, request

from .bots import BotError


class BotsWebApi:
    """工作台“选择机器人”弹窗的后台接口，素材库和指令面板共用。"""

    def __init__(self, plugin: Any) -> None:
        self.plugin = plugin

    def routes(self) -> list[tuple[str, Any, list[str], str]]:
        return [
            ("bots/list", self.list_bots, ["GET"], "列出可操作的 QQ 官方机器人"),
            ("bots/add", self.add, ["POST"], "手动添加 QQ 官方机器人"),
            ("bots/delete", self.delete, ["POST"], "删除手动添加的 QQ 官方机器人"),
        ]

    @staticmethod
    def _failed(action: str, exc: Exception):
        if isinstance(exc, BotError):
            return error_response(str(exc), status_code=400)
        logger.exception(f"[QQ官Bot按钮] {action}机器人失败")
        return error_response(f"{action}失败：{exc}", status_code=500)

    async def list_bots(self):
        return json_response({"bots": self.plugin.bots.list()})

    async def add(self):
        payload = await request.json(default={})
        if not isinstance(payload, dict):
            return error_response("请求内容必须是对象", status_code=400)
        try:
            bot = await self.plugin.bots.add(
                payload.get("appid"), payload.get("secret"), payload.get("remark")
            )
            return json_response({"bot": bot, "bots": self.plugin.bots.list()})
        except Exception as exc:
            return self._failed("添加", exc)

    async def delete(self):
        payload = await request.json(default={})
        if not isinstance(payload, dict):
            return error_response("请求内容必须是对象", status_code=400)
        try:
            await self.plugin.bots.remove(payload.get("id"))
            return json_response({"bots": self.plugin.bots.list()})
        except Exception as exc:
            return self._failed("删除", exc)
