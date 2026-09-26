import tempfile
import types
import unittest
from unittest.mock import AsyncMock
from pathlib import Path

from core.callbacks import QQOfficialCallbackHandler
from core.models import default_preset
from core.security import create_action_token
from core.sender import QQOfficialButtonSender
from core.storage import ButtonStorage


class FakeAPI:
    def __init__(self):
        self.calls = []

    async def on_interaction_result(self, interaction_id, code):
        self.calls.append(("ack", interaction_id, code))

    async def post_group_message(self, **kwargs):
        self.calls.append(("send", kwargs))
        return {"id": "sent-1"}


class CallbackTests(unittest.IsolatedAsyncioTestCase):
    async def test_old_callback_cannot_execute_changed_action_or_permission(self):
        old = self.interaction()
        preset = self.handler.plugin.storage.get("starter_menu")
        preset["rows"][1][0]["action"]["value"] = "new action"
        await self.handler.plugin.storage.save(preset)
        await self.handler.handle(self.api, old)
        self.assertEqual(self.api.calls, [("ack", "click-1", 1)])
        old = self.interaction(event_id="click-2")
        preset["rows"][1][0]["permission"]["type"] = 1
        await self.handler.plugin.storage.save(preset)
        await self.handler.handle(self.api, old)
        self.assertEqual(self.api.calls[-1], ("ack", "click-2", 1))

    async def test_disabled_functions_reject_existing_callback(self):
        self.handler.plugin.allow_functions = False
        await self.handler.handle(self.api, self.interaction())
        self.assertEqual(self.api.calls, [("ack", "click-1", 4)])

    async def test_unloaded_callback_in_another_plugins_chain_is_inert(self):
        received = []

        async def previous(interaction):
            received.append(interaction.id)

        self.client.on_interaction_create = previous
        self.handler.bind_available()
        bound = self.client.on_interaction_create

        async def another_plugin(interaction):
            await bound(interaction)

        self.client.on_interaction_create = another_plugin
        self.handler.unbind()
        await self.client.on_interaction_create(self.interaction())
        self.assertEqual(self.api.calls, [])
        self.assertEqual(received, ["click-1"])

    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        storage = ButtonStorage(Path(self.temp.name) / "buttons.json")
        preset = default_preset()
        preset["rows"][1][0]["action"] = {"type": "callback_text", "value": "回调成功"}
        await storage.save(preset)
        self.api = FakeAPI()
        self.client = types.SimpleNamespace(api=self.api, intents=0)
        platform = types.SimpleNamespace(
            meta=lambda: types.SimpleNamespace(name="qq_official", id="qq-test"),
            get_client=lambda: self.client,
            intents=types.SimpleNamespace(interaction=False, value=1),
        )
        context = types.SimpleNamespace(
            platform_manager=types.SimpleNamespace(get_insts=lambda: [platform])
        )
        plugin = types.SimpleNamespace(
            context=context,
            callback_allowed=AsyncMock(return_value=True),
            storage=storage,
            sender=QQOfficialButtonSender(
                signing_secret=storage.signing_secret, action_command="/qqbtn_action"
            ),
        )
        self.platform = platform
        self.handler = QQOfficialCallbackHandler(plugin, lambda _message: None)

    def interaction(self, *, user="user-1", event_id="click-1"):
        token = create_action_token(
            self.handler.plugin.storage.signing_secret,
            "starter_menu",
            "hello",
            self.handler.plugin.storage.get("starter_menu")["rows"][1][0],
        )
        return types.SimpleNamespace(
            id=event_id,
            event_id=event_id,
            group_openid="group-1",
            group_member_openid=user,
            user_openid=None,
            data=types.SimpleNamespace(
                resolved=types.SimpleNamespace(
                    button_data=f"qqbtn:{token}", user_id=None
                )
            ),
        )

    async def test_bind_ack_send_and_unbind(self):
        self.handler.bind_available()
        self.assertTrue(self.platform.intents.interaction)
        self.assertEqual(self.client.intents, self.platform.intents.value)
        await self.client.on_interaction_create(self.interaction())
        self.assertEqual(self.api.calls[0], ("ack", "click-1", 0))
        self.assertEqual(self.api.calls[1][0], "send")
        self.assertEqual(self.api.calls[1][1]["event_id"], "click-1")
        self.assertEqual(self.api.calls[1][1]["content"], "回调成功")
        self.handler.unbind()
        self.assertFalse(hasattr(self.client, "on_interaction_create"))

    async def test_duplicate_click_is_acknowledged_without_repeating_action(self):
        await self.handler.handle(self.api, self.interaction())
        await self.handler.handle(self.api, self.interaction())
        self.assertEqual(self.api.calls[-1], ("ack", "click-1", 3))
        self.assertEqual(sum(call[0] == "send" for call in self.api.calls), 1)

    async def test_specified_user_is_checked_again(self):
        preset = self.handler.plugin.storage.get("starter_menu")
        preset["rows"][1][0]["permission"] = {
            "type": 0,
            "user_ids": ["allowed"],
            "role_ids": [],
        }
        await self.handler.plugin.storage.save(preset)
        await self.handler.handle(self.api, self.interaction(user="other"))
        self.assertEqual(self.api.calls, [("ack", "click-1", 4)])

    async def test_callback_opens_another_menu(self):
        target = default_preset()
        target["id"] = "next_menu"
        target["triggers"] = []
        await self.handler.plugin.storage.save(target)
        preset = self.handler.plugin.storage.get("starter_menu")
        preset["rows"][1][0]["action"] = {
            "type": "callback_preset",
            "value": "next_menu",
        }
        await self.handler.plugin.storage.save(preset)
        await self.handler.handle(self.api, self.interaction())
        self.assertEqual(self.api.calls[0], ("ack", "click-1", 0))
        self.assertIn("keyboard", self.api.calls[1][1])
        self.assertEqual(self.api.calls[1][1]["event_id"], "click-1")

    async def test_foreign_callbacks_reach_previous_handler(self):
        received = []

        async def previous(interaction):
            received.append(interaction.id)

        self.client.on_interaction_create = previous
        self.handler.bind_available()
        foreign = self.interaction()
        foreign.data.resolved.button_data = "another-plugin"
        await self.client.on_interaction_create(foreign)
        self.assertEqual(received, ["click-1"])
        self.handler.unbind()
        self.assertIs(self.client.on_interaction_create, previous)


if __name__ == "__main__":
    unittest.main()
