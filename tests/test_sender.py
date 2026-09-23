import types
import unittest

from core.models import default_preset, normalize_preset
from core.security import parse_action_token
from core.sender import QQOfficialButtonSender


class FakeAPI:
    def __init__(self):
        self.calls = []

    async def post_group_message(self, **kwargs):
        self.calls.append(("group", kwargs))
        return {"id": "sent-1"}

    async def post_c2c_message(self, **kwargs):
        self.calls.append(("c2c", kwargs))

    async def post_message(self, **kwargs):
        self.calls.append(("channel", kwargs))

    async def post_dms(self, **kwargs):
        self.calls.append(("dm", kwargs))

    async def on_interaction_result(self, interaction_id, code):
        self.calls.append(("ack", {"id": interaction_id, "code": code}))


class FakeEvent:
    def __init__(self, raw):
        self.message_obj = types.SimpleNamespace(raw_message=raw, message_id="msg-1")
        self.bot = types.SimpleNamespace(api=FakeAPI())
        self._has_send_oper = False

    def get_platform_name(self):
        return "qq_official"


class MarkdownRejectedAPI(FakeAPI):
    async def post_group_message(self, **kwargs):
        self.calls.append(("group", kwargs))
        if "markdown" in kwargs:
            raise RuntimeError("不允许发送原生 markdown")
        return {"id": "fallback-1"}


class SenderTests(unittest.IsolatedAsyncioTestCase):
    async def test_group_send_uses_current_target(self):
        event = FakeEvent(
            types.SimpleNamespace(group_openid="group-openid", id="msg-1")
        )
        sender = QQOfficialButtonSender(
            signing_secret="secret", action_command="/qqbtn_action"
        )
        scene = await sender.send(event, normalize_preset(default_preset()))
        self.assertEqual(scene, "群聊")
        kind, payload = event.bot.api.calls[0]
        self.assertEqual(kind, "group")
        self.assertEqual(payload["group_openid"], "group-openid")
        self.assertNotIn("openid", payload)
        self.assertEqual(payload["msg_type"], 2)
        self.assertEqual(payload["markdown"]["content"], "想做什么？点下面就行。")
        self.assertNotIn("content", payload)
        self.assertIn("keyboard", payload)
        self.assertTrue(event._has_send_oper)

    async def test_content_mode_is_available_for_compatibility(self):
        event = FakeEvent(
            types.SimpleNamespace(group_openid="group-openid", id="msg-1")
        )
        sender = QQOfficialButtonSender(
            signing_secret="secret",
            action_command="/qqbtn_action",
            message_mode="content",
        )
        await sender.send(event, normalize_preset(default_preset()))
        payload = event.bot.api.calls[0][1]
        self.assertEqual(payload["msg_type"], 0)
        self.assertIn("content", payload)
        self.assertNotIn("markdown", payload)

    async def test_auto_mode_falls_back_when_markdown_is_not_allowed(self):
        event = FakeEvent(
            types.SimpleNamespace(group_openid="group-openid", id="msg-1")
        )
        event.bot.api = MarkdownRejectedAPI()
        sender = QQOfficialButtonSender(
            signing_secret="secret", action_command="/qqbtn_action"
        )
        await sender.send(event, normalize_preset(default_preset()))
        calls = event.bot.api.calls
        self.assertEqual(len(calls), 3)
        self.assertIn("markdown", calls[0][1])
        self.assertNotIn("msg_id", calls[1][1])
        self.assertEqual(calls[2][1]["msg_type"], 0)
        self.assertIn("content", calls[2][1])
        self.assertIn("keyboard", calls[2][1])

    def test_keyboard_maps_actions_and_signs_functions(self):
        sender = QQOfficialButtonSender(
            signing_secret="secret", action_command="/qqbtn_action"
        )
        keyboard = sender.build_keyboard(normalize_preset(default_preset()))
        buttons = [
            button for row in keyboard["content"]["rows"] for button in row["buttons"]
        ]
        self.assertEqual(buttons[0]["action"]["type"], 2)
        self.assertIn("unsupport_tips", buttons[0]["action"])
        self.assertEqual(buttons[1]["action"]["type"], 0)
        function_data = buttons[2]["action"]["data"]
        token = function_data.split(" ", 1)[1]
        self.assertEqual(parse_action_token("secret", token), ("starter_menu", "hello"))

    async def test_native_callback_and_image_are_sent(self):
        preset = default_preset()
        preset["image_url"] = "https://example.com/menu.png"
        preset["image_width"] = 640
        preset["image_height"] = 360
        preset["rows"][1][0]["action"] = {"type": "callback_text", "value": "你好"}
        preset = normalize_preset(preset)
        event = FakeEvent(types.SimpleNamespace(group_openid="group-openid", id="msg-1"))
        sender = QQOfficialButtonSender(signing_secret="secret", action_command="/qqbtn_action")
        await sender.send(event, preset)
        payload = event.bot.api.calls[0][1]
        self.assertIn("![菜单图片 #640px #360px](https://example.com/menu.png)", payload["markdown"]["content"])
        action = payload["keyboard"]["content"]["rows"][1]["buttons"][0]["action"]
        self.assertEqual(action["type"], 1)
        self.assertNotIn("enter", action)
        self.assertEqual(parse_action_token("secret", action["data"][6:]), ("starter_menu", "hello"))

        interaction = types.SimpleNamespace(group_openid="group-openid", event_id="event-1")
        await sender.send_interaction(event.bot.api, interaction, preset)
        self.assertEqual(event.bot.api.calls[1][1]["event_id"], "event-1")
        self.assertNotIn("msg_id", event.bot.api.calls[1][1])


if __name__ == "__main__":
    unittest.main()
