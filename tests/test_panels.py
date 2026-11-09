import json
import tempfile
import types
from pathlib import Path
import unittest
from unittest.mock import AsyncMock, patch

from botpy.errors import ServerError

from core import bots as bots_module
from core import panels_web
from core.bots import BotError, BotRegistry
from core.panels import (
    PanelError,
    create_panel,
    list_panels,
    normalize_panel,
    text_width,
    update_panel,
)
from core.panels_web import PanelsWebApi


class FakePanelHTTP:
    """记录指令面板接口调用的假 botpy http，按路径和方法返回预设结果。"""

    def __init__(self, responses=None, fail=None):
        self.calls = []
        self.responses = responses or {}
        self.fail = fail or {}

    async def request(self, route, **kwargs):
        path = route.path.format_map(route.parameters)
        self.calls.append((route.method, path, kwargs))
        key = (route.method, path)
        if key in self.fail:
            error = self.fail[key]
            raise error.pop(0) if isinstance(error, list) else error
        response = self.responses.get(key, {})
        return response.pop(0) if isinstance(response, list) else response


def item(name="/菜单", **extra):
    return {"type": "command", "name": name, **extra}


class NormalizeTests(unittest.TestCase):
    def test_width_counts_chinese_as_two(self):
        self.assertEqual(text_width("/菜单"), 5)
        self.assertEqual(text_width("abc"), 3)

    def test_valid_panel_fills_type_and_drops_empty_desc(self):
        data = normalize_panel(
            {
                "scope": "group",
                "items": [{"name": " /菜单 ", "desc": ""}, item("/帮助", desc="查看帮助", only_admin=1)],
                "remark": "主群",
            }
        )
        self.assertEqual(data["target_type"], "all")
        self.assertEqual(data["targets"], [])
        self.assertEqual(
            data["panel"]["items"][0], {"type": "command", "name": "/菜单", "only_admin": False}
        )
        self.assertEqual(data["panel"]["items"][1]["desc"], "查看帮助")
        self.assertTrue(data["panel"]["items"][1]["only_admin"])
        self.assertEqual(data["panel"]["remark"], "主群")

    def test_rejects_over_qq_limits(self):
        with self.assertRaisesRegex(PanelError, "7 个汉字"):
            normalize_panel({"scope": "c2c", "items": [item("一二三四五六七八")]})
        with self.assertRaisesRegex(PanelError, "15 个汉字"):
            normalize_panel({"scope": "c2c", "items": [item(desc="字" * 16)]})
        with self.assertRaisesRegex(PanelError, "最多 20 条"):
            normalize_panel({"scope": "c2c", "items": [item(f"/a{i}") for i in range(21)]})
        with self.assertRaisesRegex(PanelError, "https://"):
            normalize_panel({"scope": "c2c", "items": [{"type": "link", "name": "官网", "link": "http://a.com"}]})

    def test_target_rules(self):
        with self.assertRaisesRegex(PanelError, "只能对所有人"):
            normalize_panel({"scope": "channel", "target_type": "specific", "targets": ["x"], "items": [item()]})
        with self.assertRaisesRegex(PanelError, "至少添加一个"):
            normalize_panel({"scope": "group", "target_type": "specific", "targets": [" "], "items": [item()]})
        data = normalize_panel(
            {"scope": "group", "target_type": "specific", "targets": ["G1", "G1", " G2 "], "items": [item()]}
        )
        self.assertEqual(data["targets"], ["G1", "G2"])

    def test_rejects_empty_and_duplicate_items(self):
        with self.assertRaisesRegex(PanelError, "至少要有一条"):
            normalize_panel({"scope": "group", "items": []})
        with self.assertRaisesRegex(PanelError, "重复"):
            normalize_panel({"scope": "group", "items": [item(), item()]})


class PanelApiTests(unittest.IsolatedAsyncioTestCase):
    async def test_create_sends_first_batch_then_adds_rest(self):
        http = FakePanelHTTP({("POST", "/v2/panels"): {"panel_id": "p1"}})
        targets = [f"G{i}" for i in range(25)]
        data = normalize_panel({"scope": "group", "target_type": "specific", "targets": targets, "items": [item()]})
        panel_id, warning = await create_panel(http, data)
        self.assertEqual((panel_id, warning), ("p1", ""))
        body = http.calls[0][2]["json"]
        self.assertEqual(body["group_openids"], targets[:20])
        self.assertEqual(body["panel"]["items"][0]["type"], "command")
        self.assertEqual(http.calls[1][:2], ("PUT", "/v2/panels/p1/target"))
        self.assertEqual(http.calls[1][2]["json"], {"op": "add", "group_openids": targets[20:]})

    async def test_create_reports_partial_targets_as_warning(self):
        http = FakePanelHTTP(
            {("POST", "/v2/panels"): {"panel_id": "p1"}},
            fail={("PUT", "/v2/panels/p1/target"): ServerError("40030013 超出数量限制")},
        )
        data = normalize_panel(
            {"scope": "c2c", "target_type": "specific", "targets": [f"U{i}" for i in range(21)], "items": [item()]}
        )
        panel_id, warning = await create_panel(http, data)
        self.assertEqual(panel_id, "p1")
        self.assertIn("面板已创建", warning)
        self.assertIn("超出 QQ 的数量限制", warning)

    async def test_update_only_sends_target_changes(self):
        http = FakePanelHTTP()
        data = normalize_panel(
            {"scope": "group", "target_type": "specific", "targets": ["G1", "G3"], "items": [item()]}
        )
        warning = await update_panel(http, "p1", data, {"group_openids": ["G1", "G2"]})
        self.assertEqual(warning, "")
        self.assertEqual(http.calls[0][:2], ("PUT", "/v2/panels/p1"))
        self.assertEqual(set(http.calls[0][2]["json"]), {"panel"})
        self.assertEqual(http.calls[1][2]["json"], {"op": "del", "group_openids": ["G2"]})
        self.assertEqual(http.calls[2][2]["json"], {"op": "add", "group_openids": ["G3"]})

    async def test_update_global_panel_skips_targets(self):
        http = FakePanelHTTP()
        data = normalize_panel({"scope": "dm", "items": [item()]})
        await update_panel(http, "p1", data, {})
        self.assertEqual(len(http.calls), 1)

    async def test_list_follows_cursor_and_fills_scope(self):
        http = FakePanelHTTP(
            {
                ("GET", "/v2/panels"): [
                    {"records": [{"panel_id": "a"}], "next_cursor": "c1", "is_end": False},
                    {"records": [{"panel_id": "b"}], "next_cursor": "", "is_end": True},
                ]
            }
        )
        records = await list_panels(http, "group")
        self.assertEqual([r["panel_id"] for r in records], ["a", "b"])
        self.assertEqual(records[0]["scope"], "group")
        self.assertEqual(http.calls[1][2]["params"]["cursor"], "c1")

    async def test_errors_become_readable(self):
        http = FakePanelHTTP(fail={("GET", "/v2/panels"): ServerError("code 40030020 内容存在安全风险")})
        with self.assertRaisesRegex(PanelError, "安全风险，换个说法"):
            await list_panels(http, "group")
        http = FakePanelHTTP({("GET", "/v2/panels"): None})
        with self.assertRaisesRegex(PanelError, "没有返回结果"):
            await list_panels(http, "group")


class FakeQuery(dict):
    def get(self, key, default=None):
        return super().get(key, default)


def sender(sender_id, umo, name=""):
    return types.SimpleNamespace(sender_id=sender_id, sender_name=name, umo=umo)


def make_api(http=None, db=None):
    def platform(bot_id):
        client = types.SimpleNamespace(api=types.SimpleNamespace(_http=http))
        return types.SimpleNamespace(
            meta=lambda: types.SimpleNamespace(id=bot_id, name="qq_official"),
            get_client=lambda: client,
        )

    context = types.SimpleNamespace(
        platform_manager=types.SimpleNamespace(get_insts=lambda: [platform("bot-a"), platform("bot-b")]),
    )
    if db is not None:
        context.get_db = lambda: db
    bots = BotRegistry(context, Path(tempfile.mkdtemp()) / "bots.json")
    return PanelsWebApi(types.SimpleNamespace(context=context, bots=bots))


class PanelsWebTests(unittest.IsolatedAsyncioTestCase):
    async def call(self, handler, query=None, body=None):
        fake = types.SimpleNamespace(query=FakeQuery(query or {}), json=AsyncMock(return_value=body))
        with patch.object(panels_web, "request", fake):
            response = await handler()
        return response.status_code, json.loads(response.body)

    async def test_list_reports_failed_scope_separately(self):
        http = FakePanelHTTP(
            {("GET", "/v2/panels"): {"records": [{"panel_id": "p1"}], "is_end": True}},
        )
        original = http.request

        async def request(route, **kwargs):
            if kwargs["params"]["scope"] == "channel":
                raise ServerError("当前场景不支持此操作 40030018")
            return await original(route, **kwargs)

        http.request = request
        status, data = await self.call(make_api(http).list_all, {"bot": "bot-a"})
        self.assertEqual(status, 200)
        self.assertEqual(data["scopes"]["group"]["records"][0]["panel_id"], "p1")
        self.assertIn("不支持", data["scopes"]["channel"]["error"])
        self.assertEqual(data["scopes"]["channel"]["records"], [])

    async def test_save_existing_keeps_remote_scope(self):
        http = FakePanelHTTP(
            {("GET", "/v2/panels/p1"): {"panel_id": "p1", "scope": "group", "target_type": "all"}}
        )
        status, data = await self.call(
            make_api(http).save,
            body={"bot": "bot-a", "panel_id": "p1", "scope": "c2c", "target_type": "specific", "targets": ["U1"], "items": [item()]},
        )
        self.assertEqual(status, 200)
        self.assertEqual(data, {"panel_id": "p1", "warning": ""})
        # 页面传来的场景和范围被忽略，按全局面板只改内容。
        self.assertEqual([call[:2] for call in http.calls], [("GET", "/v2/panels/p1"), ("PUT", "/v2/panels/p1")])

    async def test_save_validation_error_is_400(self):
        status, data = await self.call(
            make_api(FakePanelHTTP()).save, body={"bot": "bot-a", "scope": "group", "items": []}
        )
        self.assertEqual(status, 400)

    async def test_unknown_bot_is_400(self):
        status, _ = await self.call(make_api(FakePanelHTTP()).list_all, {"bot": "nope"})
        self.assertEqual(status, 400)

    async def test_targets_filter_by_bot_and_scene(self):
        class FakeDB:
            def __init__(self):
                self.calls = []

            async def get_umo_senders(self, search="", limit=50, sender_ids=None, offset=0):
                self.calls.append(search)
                return [
                    (sender("U4", "bot-b:FriendMessage:U4"), None),
                    (sender("U5", "bot-a:FriendMessage:U5", "小明"), None),
                ]

        groups = AsyncMock(
            return_value=[
                (sender("", "bot-a:GroupMessage:G1"), types.SimpleNamespace(user_alias="", auto_name="一群")),
                (sender("", "bot-a:GroupMessage:U2_G2"), None),
                (sender("", "bot-a:GroupMessage:U3_G1"), None),
            ]
        )
        db = FakeDB()
        api = make_api(db=db)
        with patch.object(panels_web, "group_sessions", groups):
            _, data = await self.call(api.targets, {"bot": "bot-a", "scope": "group"})
            self.assertEqual(groups.await_args.args[1:], ("bot-a:GroupMessage:", panels_web.TARGET_SCAN_LIMIT))
            self.assertEqual([i["sender_id"] for i in data["senders"]], ["G1", "G2"])
            self.assertEqual(data["senders"][0]["session_name"], "一群")
            _, data = await self.call(api.targets, {"bot": "bot-a", "scope": "group", "search": "一群"})
            self.assertEqual([i["sender_id"] for i in data["senders"]], ["G1"])
            _, data = await self.call(api.targets, {"bot": "bot-a", "scope": "group", "ids": "G2,G7"})
            self.assertEqual([i["sender_id"] for i in data["senders"]], ["G2"])
        _, data = await self.call(api.targets, {"bot": "bot-a", "scope": "c2c"})
        self.assertEqual(db.calls[0], "bot-a:FriendMessage:")
        self.assertEqual([i["sender_id"] for i in data["senders"]], ["U5"])

    async def test_targets_for_manual_bot_has_no_records(self):
        db = types.SimpleNamespace(get_umo_senders=AsyncMock())
        _, data = await self.call(make_api(db=db).targets, {"bot": "appid:2002", "scope": "group"})
        self.assertFalse(data["supported"])
        db.get_umo_senders.assert_not_awaited()

    async def test_bot_error_is_reported_once(self):
        api = make_api(FakePanelHTTP())
        with patch.object(panels_web, "list_panels", AsyncMock(side_effect=BotError("获取凭证失败"))):
            status, data = await self.call(api.list_all, {"bot": "bot-a"})
        self.assertEqual(status, 400)
        self.assertIn("获取凭证失败", data["message"])

    async def test_manual_bot_is_used_for_panels(self):
        api = make_api(FakePanelHTTP())
        with patch.object(bots_module, "verify_credentials", AsyncMock()):
            await api.plugin.bots.add("2002", "s3cret")
        manual = FakePanelHTTP({("GET", "/v2/panels/p1"): {"panel_id": "p1"}})
        with patch.object(api.plugin.bots, "http", lambda bot_id: manual if bot_id == "appid:2002" else None):
            status, data = await self.call(api.detail, {"bot": "appid:2002", "id": "p1"})
        self.assertEqual((status, data["panel"]["panel_id"]), (200, "p1"))
        self.assertEqual(manual.calls[0][:2], ("GET", "/v2/panels/p1"))

    async def test_targets_unsupported_on_old_astrbot(self):
        _, data = await self.call(make_api(db=None).targets, {"bot": "bot-a", "scope": "group"})
        self.assertFalse(data["supported"])
