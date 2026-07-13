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

    async def post_c2c_message(self, **kwargs):
        self.calls.append(("c2c", kwargs))

    async def post_message(self, **kwargs):
        self.calls.append(("channel", kwargs))

    async def post_dms(self, **kwargs):
        self.calls.append(("dm", kwargs))


class FakeEvent:
    def __init__(self, raw):
        self.message_obj = types.SimpleNamespace(raw_message=raw, message_id="msg-1")
        self.bot = types.SimpleNamespace(api=FakeAPI())
        self._has_send_oper = False

    def get_platform_name(self):
        return "qq_official"


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
        self.assertTrue(event._has_send_oper)

    def test_keyboard_maps_actions_and_signs_functions(self):
        sender = QQOfficialButtonSender(
            signing_secret="secret", action_command="/qqbtn_action"
        )
        keyboard = sender.build_keyboard(normalize_preset(default_preset()))
        buttons = [
            button for row in keyboard["content"]["rows"] for button in row["buttons"]
        ]
        self.assertEqual(buttons[0]["action"]["type"], 2)
        self.assertEqual(buttons[1]["action"]["type"], 0)
        function_data = buttons[2]["action"]["data"]
        token = function_data.split(" ", 1)[1]
        self.assertEqual(parse_action_token("secret", token), ("starter_menu", "hello"))


if __name__ == "__main__":
    unittest.main()
