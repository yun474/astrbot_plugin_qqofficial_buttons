import json
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from core import bots as bots_module
from core import bots_web
from core.bots import BotError, BotRegistry
from core.bots_web import BotsWebApi


def platform(bot_id, appid, name="qq_official"):
    http = object()
    client = types.SimpleNamespace(api=types.SimpleNamespace(_http=http))
    return types.SimpleNamespace(
        appid=appid,
        meta=lambda: types.SimpleNamespace(id=bot_id, name=name),
        get_client=lambda: client,
        http=http,
    )


def make_context(*platforms):
    return types.SimpleNamespace(
        platform_manager=types.SimpleNamespace(get_insts=lambda: list(platforms))
    )


class BotRegistryTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "bots.json"
        self.connected = platform("bot-a", "1001")
        self.other = types.SimpleNamespace(meta=lambda: types.SimpleNamespace(id="tg", name="telegram"))
        self.registry = BotRegistry(make_context(self.connected, self.other), self.path)
        self.verify = patch.object(bots_module, "verify_credentials", AsyncMock())
        self.verify_mock = self.verify.start()

    def tearDown(self):
        self.verify.stop()
        self.tmp.cleanup()

    async def test_add_saves_secret_but_list_hides_it(self):
        bot = await self.registry.add(" 2002 ", "s3cret", "测试号")
        self.assertEqual(bot, {"id": "appid:2002", "kind": "manual", "appid": "2002", "name": "测试号"})
        self.verify_mock.assert_awaited_once_with("2002", "s3cret")
        self.assertEqual(
            [item["id"] for item in self.registry.list()], ["bot-a", "appid:2002"]
        )
        self.assertNotIn("s3cret", json.dumps(self.registry.list()))
        saved = json.loads(self.path.read_text(encoding="utf-8"))
        self.assertEqual(saved["bots"][0]["secret"], "s3cret")
        # 重启后还能读回来。
        again = BotRegistry(make_context(), self.path)
        self.assertEqual(again.list()[0]["id"], "appid:2002")

    async def test_add_same_appid_updates(self):
        await self.registry.add("2002", "old", "旧")
        await self.registry.add("2002", "new", "新")
        manual = [bot for bot in self.registry.list() if bot["kind"] == "manual"]
        self.assertEqual(len(manual), 1)
        self.assertEqual(manual[0]["name"], "新")
        self.assertEqual(json.loads(self.path.read_text("utf-8"))["bots"][0]["secret"], "new")

    async def test_add_rejects_bad_input_and_connected_bot(self):
        with self.assertRaisesRegex(BotError, "一串数字"):
            await self.registry.add("abc", "s")
        with self.assertRaisesRegex(BotError, "AppSecret"):
            await self.registry.add("2002", " ")
        with self.assertRaisesRegex(BotError, "已经连接"):
            await self.registry.add("1001", "s")
        self.verify_mock.assert_not_awaited()
        self.assertFalse(self.path.exists())

    async def test_failed_verification_saves_nothing(self):
        self.verify_mock.side_effect = BotError("AppID 或密钥不对")
        with self.assertRaisesRegex(BotError, "密钥不对"):
            await self.registry.add("2002", "wrong")
        self.assertEqual(len(self.registry.list()), 1)
        self.assertFalse(self.path.exists())

    async def test_http_picks_connected_or_manual_client(self):
        self.assertIs(self.registry.http(""), self.connected.http)
        self.assertIs(self.registry.http("bot-a"), self.connected.http)
        with self.assertRaisesRegex(BotError, "不存在或已断开"):
            self.registry.http("bot-x")
        with self.assertRaisesRegex(BotError, "已被删除"):
            self.registry.http("appid:2002")
        await self.registry.add("2002", "s3cret")
        client = self.registry.http("appid:2002")
        self.assertEqual(client._token.app_id, "2002")
        # 同一个机器人复用一个连接。
        self.assertIs(self.registry.http("appid:2002"), client)
        await self.registry.close()

    async def test_no_connected_bot_hint(self):
        registry = BotRegistry(make_context(), self.path)
        with self.assertRaisesRegex(BotError, "手动添加"):
            registry.http("")

    async def test_remove_closes_client(self):
        await self.registry.add("2002", "s3cret")
        client = self.registry.http("appid:2002")
        client.close = AsyncMock()
        await self.registry.remove("appid:2002")
        client.close.assert_awaited_once()
        self.assertEqual([bot["id"] for bot in self.registry.list()], ["bot-a"])
        self.assertEqual(json.loads(self.path.read_text("utf-8")), {"bots": []})
        with self.assertRaisesRegex(BotError, "只能删除手动添加"):
            await self.registry.remove("bot-a")

    async def test_expired_secret_becomes_readable_error(self):
        await self.registry.add("2002", "s3cret")
        client = self.registry.http("appid:2002")
        with patch.object(client._token, "check_token", AsyncMock(side_effect=RuntimeError("{'code': 100016}"))):
            with self.assertRaisesRegex(BotError, "获取凭证失败"):
                await client.check_session()

    def test_broken_file_is_ignored(self):
        self.path.write_text("{oops", encoding="utf-8")
        logs = []
        registry = BotRegistry(make_context(), self.path, logs.append)
        self.assertEqual(registry.list(), [])
        self.assertEqual(len(logs), 1)


class VerifyTests(unittest.IsolatedAsyncioTestCase):
    async def test_token_failure_is_explained(self):
        with patch("botpy.robot.Token.update_access_token", AsyncMock(side_effect=RuntimeError("invalid appid"))):
            with self.assertRaisesRegex(BotError, "没有通过验证"):
                await bots_module.verify_credentials("1", "x")


class FakeQuery(dict):
    pass


class BotsWebTests(unittest.IsolatedAsyncioTestCase):
    async def call(self, handler, body=None):
        fake = types.SimpleNamespace(query=FakeQuery(), json=AsyncMock(return_value=body))
        with patch.object(bots_web, "request", fake):
            response = await handler()
        return response.status_code, json.loads(response.body)

    async def test_add_and_delete_never_return_secret(self):
        with tempfile.TemporaryDirectory() as tmp:
            registry = BotRegistry(make_context(), Path(tmp) / "bots.json")
            api = BotsWebApi(types.SimpleNamespace(bots=registry))
            with patch.object(bots_module, "verify_credentials", AsyncMock()):
                status, data = await self.call(api.add, {"appid": "2002", "secret": "s3cret"})
            self.assertEqual(status, 200)
            self.assertEqual(data["bot"]["id"], "appid:2002")
            self.assertNotIn("s3cret", json.dumps(data))
            status, data = await self.call(api.add, {"appid": "x", "secret": "s"})
            self.assertEqual(status, 400)
            status, data = await self.call(api.delete, {"id": "appid:2002"})
            self.assertEqual((status, data["bots"]), (200, []))
