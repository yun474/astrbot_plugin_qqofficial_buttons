import json
import types
import unittest
from unittest.mock import patch

from core import sender_web
from core.sender_web import PAGE_SIZE, SenderWebApi


def sender(sender_id, umo, name=""):
    return types.SimpleNamespace(sender_id=sender_id, sender_name=name, umo=umo)


class FakeQuery(dict):
    def get(self, key, default=None):
        return super().get(key, default)


class FakeDB:
    def __init__(self, records):
        self.records = records
        self.calls = []

    async def get_umo_senders(self, search="", limit=50, sender_ids=None, offset=0):
        self.calls.append((search, limit, sender_ids, offset))
        return self.records[offset : offset + limit]


def make_api(db):
    platform = types.SimpleNamespace(
        meta=lambda: types.SimpleNamespace(id="qq-bot", name="qq_official")
    )
    context = types.SimpleNamespace(
        platform_manager=types.SimpleNamespace(get_insts=lambda: [platform]),
    )
    if db is not None:
        context.get_db = lambda: db
    return SenderWebApi(types.SimpleNamespace(context=context))


class SenderWebTests(unittest.IsolatedAsyncioTestCase):
    async def call(self, api, **query):
        with patch.object(
            sender_web, "request", types.SimpleNamespace(query=FakeQuery(query))
        ):
            response = await api.senders()
        return json.loads(response.body)

    async def test_old_astrbot_reports_unsupported(self):
        data = await self.call(make_api(types.SimpleNamespace()))
        self.assertFalse(data["supported"])
        self.assertEqual(data["senders"], [])

    async def test_search_pages_and_keeps_only_qq_platforms(self):
        alias = types.SimpleNamespace(user_alias="", auto_name="测试群")
        records = [
            (sender(f"u{i}", "qq-bot:GroupMessage:g1"), alias)
            for i in range(PAGE_SIZE + 1)
        ]
        records.insert(1, (sender("123456", "napcat:GroupMessage:g2", "小明"), None))
        db = FakeDB(records)
        data = await self.call(make_api(db), search=" 测试 ", page="1")
        self.assertEqual(db.calls[0], ("测试", PAGE_SIZE + 1, None, 0))
        self.assertTrue(data["has_more"])
        self.assertNotIn("123456", [item["sender_id"] for item in data["senders"]])
        self.assertEqual(data["senders"][0]["session_name"], "测试群")
        self.assertTrue(data["senders"][0]["group"])

    async def test_ids_resolve_exact_records(self):
        db = FakeDB([(sender("u1", "qq-bot:FriendMessage:u1"), None)])
        data = await self.call(make_api(db), ids="u1,u1,u2")
        self.assertEqual(db.calls[0], ("", 2, ["u1", "u2"], 0))
        self.assertFalse(data["senders"][0]["group"])
        self.assertEqual(data["senders"][0]["session_name"], "")

    async def test_database_error_suggests_manual_input(self):
        class BrokenDB:
            async def get_umo_senders(self, *args, **kwargs):
                raise RuntimeError("db down")

        with patch.object(sender_web, "logger") as logger:
            data = await self.call(make_api(BrokenDB()))
        logger.exception.assert_called_once()
        self.assertIn("直接添加", data["message"])


if __name__ == "__main__":
    unittest.main()
