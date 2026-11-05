from __future__ import annotations

import base64
from typing import Any

from astrbot.api import logger
from astrbot.api.web import error_response, json_response, request

from .media import (
    IMAGE_TYPES,
    MAX_IMAGE_BYTES,
    MediaError,
    bot_http,
    delete_image,
    list_images,
    upload_image,
)
from .sender import SUPPORTED_PLATFORMS


class MediaWebApi:
    """工作台素材库使用的后台接口：素材增删查与本机图片目录浏览。"""

    def __init__(self, plugin: Any) -> None:
        self.plugin = plugin

    def routes(self) -> list[tuple[str, Any, list[str], str]]:
        return [
            ("media/state", self.state, ["GET"], "读取素材库数据"),
            ("media/list", self.list_media, ["GET"], "列出 QQ 素材库图片"),
            # 页面上传接口不能带查询参数，机器人 ID 放在路径里，"_" 表示默认机器人。
            ("media/upload/<bot>", self.upload, ["POST"], "上传图片到 QQ 素材库"),
            ("media/delete", self.delete, ["POST"], "删除 QQ 素材库图片"),
            ("media/local/upload", self.local_upload, ["POST"], "上传图片到本机图片目录"),
            ("media/local/preview", self.local_preview, ["GET"], "预览本机图片"),
        ]

    def _platforms(self) -> list[Any]:
        return [
            platform
            for platform in self.plugin.context.platform_manager.get_insts()
            if platform.meta().name in SUPPORTED_PLATFORMS
        ]

    def _http(self, bot_id: str) -> Any:
        platforms = self._platforms()
        if not platforms:
            raise MediaError("没有已连接的 QQ 官方机器人")
        for platform in platforms:
            if not bot_id or platform.meta().id == bot_id:
                return bot_http(platform)
        raise MediaError("所选机器人不存在或已断开")

    @staticmethod
    def _failed(action: str, exc: Exception):
        if isinstance(exc, MediaError):
            return error_response(str(exc), status_code=400)
        logger.exception(f"[QQ官Bot按钮] 素材库{action}失败")
        return error_response(f"{action}失败：{exc}", status_code=500)

    async def state(self):
        local = self.plugin.local_images
        return json_response(
            {
                "bots": [
                    {"id": platform.meta().id, "name": platform.meta().name}
                    for platform in self._platforms()
                ],
                "local_dir": str(local.directory),
                "local_images": local.list(),
                "max_bytes": MAX_IMAGE_BYTES,
                "formats": sorted({suffix.lstrip(".") for suffix in IMAGE_TYPES}),
            }
        )

    async def list_media(self):
        try:
            result = await list_images(
                self._http(request.query.get("bot", "")),
                request.query.get("cursor", ""),
            )
            return json_response(
                {
                    "images": result.get("images") or [],
                    "next_cursor": result.get("next_cursor") or "",
                    "total": result.get("total", 0),
                }
            )
        except Exception as exc:
            return self._failed("读取", exc)

    @staticmethod
    async def _received_file() -> tuple[str, bytes]:
        files = await request.files()
        file = files.get("file")
        if file is None:
            raise MediaError("没有收到图片文件")
        data = await file.read(MAX_IMAGE_BYTES + 1)
        return str(getattr(file, "filename", "") or "image.png"), data

    async def upload(self, bot: str = "_"):
        try:
            name, data = await self._received_file()
            result = await upload_image(
                self._http("" if bot == "_" else bot), name, data
            )
            return json_response({"image": result})
        except Exception as exc:
            return self._failed("上传", exc)

    async def local_upload(self):
        # 只写入固定的图片目录，文件名和内容在 LocalImages.save 中校验。
        try:
            name, data = await self._received_file()
            return json_response({"image": self.plugin.local_images.save(name, data)})
        except Exception as exc:
            return self._failed("上传", exc)

    async def delete(self):
        payload = await request.json(default={})
        if not isinstance(payload, dict) or not payload.get("image_id"):
            return error_response("缺少图片 ID", status_code=400)
        try:
            await delete_image(
                self._http(str(payload.get("bot") or "")), str(payload["image_id"])
            )
            return json_response({"deleted": True})
        except Exception as exc:
            return self._failed("删除", exc)

    async def local_preview(self):
        try:
            name, data = self.plugin.local_images.read(request.query.get("name", ""))
            content_type = IMAGE_TYPES[name[name.rfind(".") :].lower()]
            encoded = base64.b64encode(data).decode("ascii")
            return json_response({"data_url": f"data:{content_type};base64,{encoded}"})
        except Exception as exc:
            return self._failed("预览", exc)
