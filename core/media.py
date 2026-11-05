from __future__ import annotations

import hashlib
import re
from collections.abc import Callable
from pathlib import Path
from typing import Any

MEDIA_PREFIX = "qqbot-media://"
LOCAL_PREFIX = "local://"
MAX_IMAGE_BYTES = 10 * 1024 * 1024
IMAGE_TYPES = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
}
# 本机图片只允许直接放在图片目录下的文件名，不能带路径分隔符或跳出目录。
LOCAL_NAME = re.compile(r"^[^\\/:*?\"<>|()\s\x00-\x1f]{1,100}$")
# 正文 Markdown 里引用的本机图片：![说明](local://文件名)
LOCAL_IN_MARKDOWN = re.compile(r"\]\(local://([^)\s]+)\)")
# 本机文件名里不允许出现的字符，上传时替换成下划线。
UNSAFE_NAME_CHARS = re.compile(r"[\\/:*?\"<>|()\s\x00-\x1f]")


class MediaError(RuntimeError):
    """素材库操作失败，信息可直接展示给后台用户。"""


def local_name(url: str) -> str:
    """校验 local:// 地址并返回文件名；格式不对时抛出 MediaError。"""
    name = str(url or "").removeprefix(LOCAL_PREFIX)
    suffix = Path(name).suffix.lower()
    if (
        not LOCAL_NAME.fullmatch(name)
        or name in {".", ".."}
        or name.startswith(".")
        or suffix not in IMAGE_TYPES
    ):
        raise MediaError(
            "本机图片只能填写图片目录里的文件名，如 local://banner.png，"
            "支持 png、jpg、gif、webp"
        )
    return name


def is_media_url(url: str) -> bool:
    return str(url or "").startswith(MEDIA_PREFIX)


def is_local_url(url: str) -> bool:
    return str(url or "").startswith(LOCAL_PREFIX)


def _media_route(method: str, path: str, **parameters: Any) -> Any:
    from botpy.http import Route

    class MediaRoute(Route):
        # 素材管理接口按官方文档使用 api.bot.qq.com。
        DOMAIN = "api.bot.qq.com"

    return MediaRoute(method, path, **parameters)


def bot_http(platform: Any) -> Any:
    client = platform.get_client() if hasattr(platform, "get_client") else platform.client
    return client.api._http


def looks_like_image(suffix: str, data: bytes) -> bool:
    """按文件头确认内容与扩展名一致，避免把其他文件改个后缀就存进图片目录。"""
    if suffix == ".png":
        return data.startswith(b"\x89PNG\r\n\x1a\n")
    if suffix in {".jpg", ".jpeg"}:
        return data.startswith(b"\xff\xd8\xff")
    if suffix == ".gif":
        return data.startswith((b"GIF87a", b"GIF89a"))
    if suffix == ".webp":
        return data[:4] == b"RIFF" and data[8:12] == b"WEBP"
    return False


class LocalImages:
    """插件数据目录下的本机图片文件夹。"""

    def __init__(self, directory: str | Path) -> None:
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)

    def path(self, url_or_name: str) -> Path:
        name = local_name(url_or_name)
        path = (self.directory / name).resolve()
        if path.parent != self.directory.resolve():
            raise MediaError("本机图片必须直接放在图片目录里")
        return path

    def read(self, url_or_name: str) -> tuple[str, bytes]:
        path = self.path(url_or_name)
        if not path.is_file():
            # 这条提示可能随发送失败发到群里，只写文件名，不暴露服务器路径。
            raise MediaError(
                f"本机图片不存在：{path.name}，请管理员放回素材库的本机图片目录"
            )
        size = path.stat().st_size
        if size > MAX_IMAGE_BYTES:
            raise MediaError(f"本机图片 {path.name} 超过 10MB")
        return path.name, path.read_bytes()

    def check(self, url_or_name: str) -> None:
        self.read(url_or_name)

    @staticmethod
    def _item(path: Path) -> dict[str, Any]:
        stat = path.stat()
        return {
            "name": path.name,
            "url": f"{LOCAL_PREFIX}{path.name}",
            "size": stat.st_size,
            "modified_at": int(stat.st_mtime),
        }

    def _scan(self) -> tuple[list[Path], list[str]]:
        """返回可用的图片文件，以及因文件名不合规而无法引用的图片文件名。"""
        usable, skipped = [], []
        for path in sorted(self.directory.iterdir(), key=lambda item: item.name):
            if not path.is_file() or path.suffix.lower() not in IMAGE_TYPES:
                continue
            # 以点开头的是系统隐藏文件（如 macOS 的 ._ 文件），不算用户放的图片。
            if path.name.startswith("."):
                continue
            try:
                local_name(path.name)
            except MediaError:
                skipped.append(path.name)
                continue
            usable.append(path)
        return usable, skipped

    def list(self) -> list[dict[str, Any]]:
        return [self._item(path) for path in self._scan()[0]]

    def skipped(self) -> list[str]:
        """手动放进目录、文件名含空格括号等字符的图片，用于提示用户改名。"""
        return self._scan()[1]

    def save(self, file_name: str, data: bytes) -> dict[str, Any]:
        """把后台上传的图片存进图片目录；重名时自动加序号，不覆盖已有文件。"""
        # 只取文件名本身，丢弃浏览器可能带上的路径，再替换掉不能用的字符。
        raw = str(file_name or "").replace("\\", "/").rsplit("/", 1)[-1]
        suffix = Path(raw).suffix.lower()
        if suffix not in IMAGE_TYPES:
            raise MediaError("只支持 png、jpg、gif、webp 图片")
        if not data:
            raise MediaError("图片内容为空")
        if len(data) > MAX_IMAGE_BYTES:
            raise MediaError("图片不能超过 10MB")
        if not looks_like_image(suffix, data):
            raise MediaError("文件内容与图片格式不符，请上传真实的图片文件")
        stem = UNSAFE_NAME_CHARS.sub("_", raw[: -len(suffix)]).lstrip(".")[:80] or "image"
        for index in range(1000):
            name = f"{stem}{suffix}" if index == 0 else f"{stem}-{index}{suffix}"
            path = self.path(name)
            try:
                # 独占创建，同名文件已存在时换下一个序号，避免并发上传互相覆盖。
                with path.open("xb") as handle:
                    handle.write(data)
            except FileExistsError:
                continue
            return self._item(path)
        raise MediaError("同名图片太多，请改个文件名再上传")


async def _request(http: Any, method: str, path: str, **kwargs: Any) -> Any:
    parameters = kwargs.pop("parameters", {})
    result = await http.request(_media_route(method, path, **parameters), **kwargs)
    if result is None and method != "DELETE":
        raise MediaError("QQ 素材接口没有返回结果，可能是请求超时，请稍后重试")
    return result


async def upload_image(http: Any, file_name: str, data: bytes) -> dict[str, Any]:
    """按官方三步流程上传图片：prepare → PUT 预签名地址 → complete。"""
    import aiohttp

    suffix = Path(file_name).suffix.lower()
    content_type = IMAGE_TYPES.get(suffix)
    if content_type is None:
        raise MediaError("只支持 png、jpg、gif、webp 图片")
    if not data:
        raise MediaError("图片内容为空")
    if len(data) > MAX_IMAGE_BYTES:
        raise MediaError("图片不能超过 10MB")
    md5 = hashlib.md5(data).hexdigest()
    prepare = await _request(
        http,
        "POST",
        "/v2/media-images/prepare",
        json={
            "file_name": file_name,
            "file_size": len(data),
            "content_type": content_type,
            "md5": md5,
            "sha1": hashlib.sha1(data).hexdigest(),
        },
    )
    timeout = aiohttp.ClientTimeout(total=60)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.put(
            prepare["presigned_url"],
            data=data,
            headers={"Content-Type": content_type},
        ) as response:
            if response.status >= 300:
                raise MediaError(f"图片上传到 QQ 存储失败：HTTP {response.status}")
            etag = str(response.headers.get("ETag") or "").strip('"') or md5
    return await _request(
        http,
        "POST",
        "/v2/media-images/complete",
        json={"upload_id": prepare["upload_id"], "md5": etag},
    )


async def list_images(http: Any, cursor: str = "") -> dict[str, Any]:
    params = {"cursor": cursor} if cursor else None
    return await _request(http, "GET", "/v2/media-images", params=params)


async def delete_image(http: Any, image_id: str) -> None:
    await _request(
        http,
        "DELETE",
        "/v2/media-images/{image_id}/delete",
        parameters={"image_id": image_id},
    )


class TemporaryImages:
    """把本机图片临时上传为素材，发送后立即删除，不长期占用额度。"""

    def __init__(
        self,
        http: Any,
        local: LocalImages,
        log: Callable[[str], None],
    ) -> None:
        self.http = http
        self.local = local
        self.log = log
        self.uploaded: dict[str, dict[str, Any]] = {}

    async def resolve(self, url: str) -> str:
        """把 local:// 地址换成临时素材链接；同一次发送里重复引用只上传一次。"""
        name = local_name(url)
        if name not in self.uploaded:
            file_name, data = self.local.read(name)
            try:
                self.uploaded[name] = await upload_image(self.http, file_name, data)
            except MediaError:
                raise
            except Exception as exc:
                # botpy 只透出错误文字，不一定带错误码，这里统一提示最常见的额度原因。
                raise MediaError(
                    f"本机图片 {file_name} 临时上传失败：{exc}；"
                    "如果素材库已满 100 张，请先在素材库删除一些图片"
                ) from exc
        return self.uploaded[name]["url"]

    async def apply(self, preset: dict[str, Any]) -> dict[str, Any]:
        """返回替换好临时链接的菜单副本，原菜单不变。"""
        updates: dict[str, Any] = {}
        image_url = preset.get("image_url") or ""
        if is_local_url(image_url):
            updates["image_url"] = await self.resolve(image_url)
        content = preset.get("content") or ""
        names = list(dict.fromkeys(LOCAL_IN_MARKDOWN.findall(content)))
        for name in names:
            content = content.replace(
                f"](local://{name})", f"]({await self.resolve(name)})"
            )
        if names:
            updates["content"] = content
        return preset | updates if updates else preset

    async def cleanup(self) -> None:
        # 已发出的消息由平台转存副本，删除素材不影响聊天记录。
        for item in self.uploaded.values():
            try:
                await delete_image(self.http, item["image_id"])
            except Exception as exc:
                self.log(
                    f"[QQ官Bot按钮] 临时素材 {item.get('image_id')} 删除失败，"
                    f"可在工作台的素材库中手动删除：{exc}"
                )
        self.uploaded.clear()


def has_local_images(preset: dict[str, Any]) -> bool:
    return is_local_url(preset.get("image_url") or "") or bool(
        LOCAL_IN_MARKDOWN.search(preset.get("content") or "")
    )


def check_local_images(preset: dict[str, Any], local: LocalImages) -> None:
    """保存菜单时确认引用的本机图片都存在，避免发送时才发现。"""
    image_url = preset.get("image_url") or ""
    if is_local_url(image_url):
        local.check(image_url)
    for name in LOCAL_IN_MARKDOWN.findall(preset.get("content") or ""):
        local.check(name)
