"""工作台可操作的机器人：AstrBot 里已连接的 QQ 官方机器人，加上手动填写 AppID 和密钥的机器人。

手动添加的机器人只用于素材库和指令面板这类后台管理接口，不会收发消息。
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

from .media import MediaError, bot_http
from .sender import SUPPORTED_PLATFORMS
from .storage import write_json_atomic

# 手动添加的机器人在页面上的 ID 带这个前缀，和已连接机器人的平台 ID 区分开。
MANUAL_PREFIX = "appid:"
REQUEST_TIMEOUT = 20
APPID_LENGTH = 32
SECRET_LENGTH = 128
REMARK_LENGTH = 30


class BotError(MediaError):
    """机器人选择或凭证有问题，信息可直接展示给后台用户。"""


def qq_platforms(context: Any) -> list[Any]:
    """列出 AstrBot 里已连接的 QQ 官方机器人平台实例。"""
    return [
        platform
        for platform in context.platform_manager.get_insts()
        if platform.meta().name in SUPPORTED_PLATFORMS
    ]


def connected_bots(context: Any) -> list[dict[str, str]]:
    return [
        {
            "id": platform.meta().id,
            "kind": "connected",
            "appid": str(getattr(platform, "appid", "") or ""),
            "name": platform.meta().name,
        }
        for platform in qq_platforms(context)
    ]


async def verify_credentials(appid: str, secret: str) -> None:
    """用 AppID 和密钥向 QQ 换一次凭证，换不到就说明填错了。"""
    import aiohttp
    from botpy.robot import Token

    try:
        await Token(app_id=appid, secret=secret).update_access_token()
    except (asyncio.TimeoutError, aiohttp.ClientError) as exc:
        raise BotError(f"连不上 QQ 验证服务器，请检查网络后再试：{str(exc) or '超时'}") from exc
    except Exception as exc:
        raise BotError(f"AppID 或密钥不对，QQ 没有通过验证：{exc}") from exc


def _create_http(appid: str, secret: str) -> Any:
    import aiohttp
    from botpy.http import BotHttp

    class ManualBotHttp(BotHttp):
        async def check_session(self) -> None:
            # botpy 换凭证失败时抛的是笼统的 RuntimeError，这里翻译成看得懂的提示。
            try:
                await super().check_session()
            except (asyncio.TimeoutError, aiohttp.ClientError) as exc:
                raise BotError(
                    f"机器人 {appid} 连不上 QQ 验证服务器，请检查网络后再试：{str(exc) or '超时'}"
                ) from exc
            except Exception as exc:
                raise BotError(
                    f"机器人 {appid} 获取凭证失败，密钥可能已重置，请删除后重新添加：{exc}"
                ) from exc

    return ManualBotHttp(timeout=REQUEST_TIMEOUT, app_id=appid, secret=secret)


class BotRegistry:
    """按页面传来的机器人 ID 取 botpy 的 http 客户端，并保存手动添加的机器人。"""

    def __init__(self, context: Any, path: Path, log: Any = None) -> None:
        self.context = context
        self.path = path
        self.log = log
        self._manual = self._load()
        self._clients: dict[str, Any] = {}
        self._lock = asyncio.Lock()

    def _load(self) -> list[dict[str, str]]:
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return []
        except (OSError, ValueError) as exc:
            if self.log:
                self.log(f"[QQ官Bot按钮] 读取手动添加的机器人失败，已忽略：{exc}")
            return []
        bots = raw.get("bots") if isinstance(raw, dict) else None
        return [
            {
                "appid": str(item["appid"]),
                "secret": str(item["secret"]),
                "remark": str(item.get("remark") or ""),
            }
            for item in bots or []
            if isinstance(item, dict) and item.get("appid") and item.get("secret")
        ]

    def _find_manual(self, appid: str) -> dict[str, str] | None:
        return next((item for item in self._manual if item["appid"] == appid), None)

    def list(self) -> list[dict[str, str]]:
        """页面用的机器人列表，密钥不会出现在这里。"""
        return connected_bots(self.context) + [
            {
                "id": MANUAL_PREFIX + item["appid"],
                "kind": "manual",
                "appid": item["appid"],
                "name": item["remark"],
            }
            for item in self._manual
        ]

    def http(self, bot_id: str) -> Any:
        """留空表示第一个已连接的机器人，与之前只有下拉框时的行为一致。"""
        bot_id = str(bot_id or "")
        if bot_id.startswith(MANUAL_PREFIX):
            appid = bot_id[len(MANUAL_PREFIX) :]
            item = self._find_manual(appid)
            if item is None:
                raise BotError("所选机器人已被删除，请重新选择")
            if appid not in self._clients:
                self._clients[appid] = _create_http(appid, item["secret"])
            return self._clients[appid]
        platforms = qq_platforms(self.context)
        for platform in platforms:
            if not bot_id or platform.meta().id == bot_id:
                return bot_http(platform)
        if not platforms and not bot_id:
            raise BotError("没有已连接的 QQ 官方机器人，可以在“选择机器人”里手动添加")
        raise BotError("所选机器人不存在或已断开，请重新选择")

    async def add(self, appid: Any, secret: Any, remark: Any = "") -> dict[str, str]:
        """验证通过才保存；同一个 AppID 再添加一次就是更新密钥和备注。"""
        appid = str(appid or "").strip()
        secret = str(secret or "").strip()
        remark = str(remark or "").strip()
        if not appid.isdigit() or len(appid) > APPID_LENGTH:
            raise BotError("AppID 是一串数字，可以在 QQ 开放平台的开发设置里找到")
        if not secret or len(secret) > SECRET_LENGTH or any(c.isspace() for c in secret):
            raise BotError("请填写正确的 AppSecret（机器人密钥）")
        if len(remark) > REMARK_LENGTH:
            raise BotError(f"备注最多 {REMARK_LENGTH} 个字")
        if any(bot["appid"] == appid for bot in connected_bots(self.context)):
            raise BotError("这个机器人已经连接在 AstrBot 里了，直接在列表里选它就行")
        await verify_credentials(appid, secret)
        async with self._lock:
            item = {"appid": appid, "secret": secret, "remark": remark}
            current = self._find_manual(appid)
            manual = [item if bot is current else bot for bot in self._manual]
            if current is None:
                manual.append(item)
            write_json_atomic(self.path, {"bots": manual})
            self._manual = manual
            await self._close_client(appid)
        return next(bot for bot in self.list() if bot["id"] == MANUAL_PREFIX + appid)

    async def remove(self, bot_id: Any) -> None:
        bot_id = str(bot_id or "")
        if not bot_id.startswith(MANUAL_PREFIX):
            raise BotError("只能删除手动添加的机器人，已连接的机器人请在 AstrBot 里管理")
        appid = bot_id[len(MANUAL_PREFIX) :]
        async with self._lock:
            manual = [item for item in self._manual if item["appid"] != appid]
            if len(manual) != len(self._manual):
                write_json_atomic(self.path, {"bots": manual})
                self._manual = manual
            await self._close_client(appid)

    async def _close_client(self, appid: str) -> None:
        client = self._clients.pop(appid, None)
        if client is not None:
            await client.close()

    async def close(self) -> None:
        for appid in list(self._clients):
            await self._close_client(appid)
