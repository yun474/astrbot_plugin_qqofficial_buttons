import hashlib
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from core import media
from core.media import (
    LocalImages,
    MediaError,
    TemporaryImages,
    check_local_images,
    local_name,
    upload_image,
)
from core.models import ButtonValidationError, default_preset, normalize_preset
from core.sender import QQOfficialButtonSender

PNG = b"\x89PNG\r\n\x1a\nfake"


class FakeMediaHTTP:
    """记录素材接口调用的假 botpy http。"""

    def __init__(self):
        self.calls = []

    async def request(self, route, **kwargs):
        path = route.path.format_map(route.parameters)
        self.calls.append((route.method, path, kwargs))
        if path.endswith("/prepare"):
            return {"upload_id": "up-1", "presigned_url": "https://cos.example/put", "expires_in": 3600}
        if path.endswith("/complete"):
            return {"image_id": "img-1", "url": "qqbot-media://image/v1/tok", "ttl": 7776000}
        return {}


class FakeResponse:
    status = 200
    headers = {"ETag": '"etag-md5"'}

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False


class FakeSession:
    puts = []

    def __init__(self, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    def put(self, url, *, data, headers):
        FakeSession.puts.append((url, data, headers))
        return FakeResponse()


class LocalNameTests(unittest.TestCase):
    def test_accepts_plain_image_names(self):
        for name in ("banner.png", "菜单-1.JPG", "a_b.webp", "x.gif"):
            with self.subTest(name=name):
                self.assertEqual(local_name(f"local://{name}"), name)

    def test_rejects_paths_and_other_files(self):
        for name in ("../a.png", "sub/a.png", "sub\\a.png", ".hide.png", "a.txt", "a b.png", "C:a.png", ""):
            with self.subTest(name=name), self.assertRaises(MediaError):
                local_name(f"local://{name}")


class LocalImagesTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.local = LocalImages(Path(self.temp.name) / "images")

    def tearDown(self):
        self.temp.cleanup()

    def test_read_list_and_missing(self):
        (self.local.directory / "banner.png").write_bytes(PNG)
        (self.local.directory / "note.txt").write_text("x")
        self.assertEqual(self.local.read("local://banner.png"), ("banner.png", PNG))
        self.assertEqual([item["url"] for item in self.local.list()], ["local://banner.png"])
        with self.assertRaisesRegex(MediaError, "不存在"):
            self.local.read("local://missing.png")

    def test_check_covers_image_field_and_content(self):
        (self.local.directory / "a.png").write_bytes(PNG)
        check_local_images({"image_url": "local://a.png", "content": "![x](local://a.png)"}, self.local)
        with self.assertRaises(MediaError):
            check_local_images({"image_url": "", "content": "![x](local://b.png)"}, self.local)


class ModelImageTests(unittest.TestCase):
    def preset(self, url):
        preset = default_preset()
        preset["image_url"] = url
        return preset

    def test_media_and_local_urls_are_accepted(self):
        for url in ("qqbot-media://image/v1/tok", "local://banner.png", "https://example.com/a.png"):
            with self.subTest(url=url):
                self.assertEqual(normalize_preset(self.preset(url))["image_url"], url)

    def test_bad_urls_are_rejected(self):
        for url in ("local://../a.png", "qqbot-media://", "http://example.com/a.png", "file:///a.png"):
            with self.subTest(url=url), self.assertRaises(ButtonValidationError):
                normalize_preset(self.preset(url))


class UploadTests(unittest.IsolatedAsyncioTestCase):
    async def test_three_step_upload(self):
        http = FakeMediaHTTP()
        FakeSession.puts = []
        with patch("aiohttp.ClientSession", FakeSession):
            result = await upload_image(http, "banner.png", PNG)
        self.assertEqual(result["url"], "qqbot-media://image/v1/tok")
        prepare = http.calls[0][2]["json"]
        self.assertEqual(http.calls[0][1], "/v2/media-images/prepare")
        self.assertEqual(prepare["content_type"], "image/png")
        self.assertEqual(prepare["md5"], hashlib.md5(PNG).hexdigest())
        self.assertEqual(FakeSession.puts[0][2], {"Content-Type": "image/png"})
        self.assertEqual(http.calls[1][2]["json"], {"upload_id": "up-1", "md5": "etag-md5"})

    async def test_rejects_unsupported_or_oversized(self):
        with self.assertRaises(MediaError):
            await upload_image(FakeMediaHTTP(), "a.bmp", PNG)
        with self.assertRaises(MediaError):
            await upload_image(FakeMediaHTTP(), "a.png", b"x" * (media.MAX_IMAGE_BYTES + 1))


class TemporaryImagesTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.local = LocalImages(Path(self.temp.name))
        (self.local.directory / "a.png").write_bytes(PNG)
        self.logs = []

    async def asyncTearDown(self):
        self.temp.cleanup()

    async def test_apply_uploads_once_and_cleanup_deletes(self):
        upload = AsyncMock(return_value={"image_id": "img-1", "url": "qqbot-media://image/v1/t"})
        delete = AsyncMock()
        with patch.object(media, "upload_image", upload), patch.object(media, "delete_image", delete):
            temporary = TemporaryImages("http", self.local, self.logs.append)
            preset = {"image_url": "local://a.png", "content": "看图 ![x](local://a.png)"}
            result = await temporary.apply(preset)
            self.assertEqual(result["image_url"], "qqbot-media://image/v1/t")
            self.assertEqual(result["content"], "看图 ![x](qqbot-media://image/v1/t)")
            self.assertEqual(preset["image_url"], "local://a.png")
            upload.assert_awaited_once()
            await temporary.cleanup()
        delete.assert_awaited_once_with("http", "img-1")

    async def test_cleanup_failure_is_logged_not_raised(self):
        upload = AsyncMock(return_value={"image_id": "img-1", "url": "qqbot-media://image/v1/t"})
        delete = AsyncMock(side_effect=RuntimeError("boom"))
        with patch.object(media, "upload_image", upload), patch.object(media, "delete_image", delete):
            temporary = TemporaryImages("http", self.local, self.logs.append)
            await temporary.apply({"image_url": "local://a.png"})
            await temporary.cleanup()
        self.assertIn("img-1", self.logs[0])

    async def test_upload_failure_hints_quota(self):
        with patch.object(media, "upload_image", AsyncMock(side_effect=RuntimeError("limit"))):
            temporary = TemporaryImages("http", self.local, self.logs.append)
            with self.assertRaisesRegex(MediaError, "100 张"):
                await temporary.apply({"image_url": "local://a.png"})


class FakeAPI:
    def __init__(self):
        self.calls = []
        self._http = "media-http"

    async def post_group_message(self, **kwargs):
        self.calls.append(kwargs)
        return {"id": "sent-1"}


class SenderMediaTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.local = LocalImages(Path(self.temp.name))
        (self.local.directory / "a.png").write_bytes(PNG)
        self.raw = types.SimpleNamespace(group_openid="group", group_member_openid="user")

    async def asyncTearDown(self):
        self.temp.cleanup()

    def preset(self, url):
        preset = normalize_preset(default_preset())
        preset["image_url"] = url
        return preset

    async def send(self, url, mode="auto"):
        sender = QQOfficialButtonSender(
            signing_secret="secret",
            action_command="/qqbtn_action",
            message_mode=mode,
            local_images=self.local,
        )
        api = FakeAPI()
        upload = AsyncMock(return_value={"image_id": "img-1", "url": "qqbot-media://image/v1/t"})
        delete = AsyncMock()
        with patch.object(media, "upload_image", upload), patch.object(media, "delete_image", delete):
            await sender.send_interaction(api, self.raw, self.preset(url))
        return api, upload, delete

    async def test_local_image_uploads_sends_then_deletes(self):
        api, upload, delete = await self.send("local://a.png")
        self.assertIn("(qqbot-media://image/v1/t)", api.calls[0]["markdown"]["content"])
        upload.assert_awaited_once()
        delete.assert_awaited_once_with("media-http", "img-1")

    async def test_content_mode_skips_upload_and_link(self):
        api, upload, _ = await self.send("local://a.png", mode="content")
        upload.assert_not_awaited()
        self.assertNotIn("local://", api.calls[0]["content"])

    async def test_media_link_is_used_as_is(self):
        api, upload, _ = await self.send("qqbot-media://image/v1/keep")
        upload.assert_not_awaited()
        self.assertIn("(qqbot-media://image/v1/keep)", api.calls[0]["markdown"]["content"])


if __name__ == "__main__":
    unittest.main()


class ToolLocalImageTests(unittest.IsolatedAsyncioTestCase):
    async def test_llm_content_cannot_reference_local_images(self):
        from core.tool import QQOfficialButtonsTool

        plugin = types.SimpleNamespace(enable_dynamic_buttons=False, max_rows=5, allow_functions=True)
        tool = QQOfficialButtonsTool(plugin)
        context = types.SimpleNamespace(context=types.SimpleNamespace(event=None))
        result = await tool.call(context, preset_id="menu", content="看 ![x](local://a.png)")
        self.assertIn("local://", result)
        self.assertTrue(result.startswith("error"))
