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

    def interaction(self, *, user="user-1", event_id="click-1", token_user=""):
        token = create_action_token(
            self.handler.plugin.storage.signing_secret,
            "starter_menu",
            "hello",
            self.handler.plugin.storage.get("starter_menu")["rows"][1][0],
            user=token_user,
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

    async def set_hello(self, *, action=None, permission_type=None):
        preset = self.handler.plugin.storage.get("starter_menu")
        button = preset["rows"][1][0]
        if action is not None:
            button["action"] = action
        if permission_type is not None:
            button["permission"] = {"type": permission_type, "user_ids": [], "role_ids": []}
        await self.handler.plugin.storage.save(preset)

    def enable_llm(self, reply="今天也要好好吃饭。", *, error=None, cooldown=0):
        provider = types.SimpleNamespace(calls=[])

        async def text_chat(**kwargs):
            provider.calls.append(kwargs)
            if error:
                raise error
            return types.SimpleNamespace(completion_text=reply)

        async def get_provider(umo=None):
            provider.umo = umo
            return provider

        provider.text_chat = text_chat
        plugin = self.handler.plugin
        plugin.context.get_using_provider_async = get_provider
        plugin.llm_cooldown = cooldown
        plugin.callback_session = lambda platform, interaction: (
            "qq-test:GroupMessage:group-1",
            {"admins_id": ["boss"]},
        )
        plugin.is_bot_admin = lambda user, config: user in config["admins_id"]
        return provider

    async def test_trigger_only_callback_accepts_only_bound_user(self):
        await self.set_hello(permission_type=10)
        await self.handler.handle(
            self.api, self.interaction(user="owner", token_user="owner")
        )
        self.assertEqual(self.api.calls[0], ("ack", "click-1", 0))
        await self.handler.handle(
            self.api,
            self.interaction(user="other", token_user="owner", event_id="click-2"),
        )
        self.assertEqual(self.api.calls[-1], ("ack", "click-2", 4))
        # 未绑定触发者的签名不能用于仅触发者按钮。
        await self.handler.handle(
            self.api, self.interaction(user="owner", event_id="click-3")
        )
        self.assertEqual(self.api.calls[-1], ("ack", "click-3", 4))

    async def test_forged_trigger_user_breaks_signature(self):
        await self.set_hello(permission_type=10)
        interaction = self.interaction(user="other", token_user="owner")
        signature = interaction.data.resolved.button_data.split(".")[1]
        forged = create_action_token("wrong", "starter_menu", "hello", None, user="other")
        interaction.data.resolved.button_data = (
            f"qqbtn:{forged.split('.')[0]}.{signature}"
        )
        await self.handler.handle(self.api, interaction)
        self.assertEqual(self.api.calls, [("ack", "click-1", 1)])

    async def test_bot_admin_callback_checks_admins_id(self):
        self.enable_llm()
        await self.set_hello(permission_type=11)
        await self.handler.handle(
            self.api, self.interaction(user="boss"), platform=self.platform
        )
        self.assertEqual(self.api.calls[0], ("ack", "click-1", 0))
        await self.handler.handle(
            self.api,
            self.interaction(user="member", event_id="click-2"),
            platform=self.platform,
        )
        # AstrBot 管理员总是由插件拦截，没配置过拒绝语时回复默认提示。
        self.assertEqual(self.api.calls[-2], ("ack", "click-2", 0))
        self.assertEqual(
            self.api.calls[-1][1]["content"], "这个按钮没给你操作权限，别乱戳啦。"
        )

    async def deny_hello(self, **fields):
        preset = self.handler.plugin.storage.get("starter_menu")
        button = preset["rows"][1][0]
        button["permission"] = {"type": 10, "user_ids": [], "role_ids": []}
        button["intercept"] = True
        button.update(fields)
        await self.handler.plugin.storage.save(preset)

    async def test_denied_click_sends_default_reply_without_signature_change(self):
        # 先拿到旧签名，再开启拦截：拦截开关不进签名，旧菜单仍能点。
        await self.set_hello(permission_type=10)
        old = self.interaction(user="other", token_user="owner")
        await self.deny_hello()
        await self.handler.handle(self.api, old)
        self.assertEqual(self.api.calls[0], ("ack", "click-1", 0))
        self.assertEqual(
            self.api.calls[1][1]["content"], "这个按钮没给你操作权限，别乱戳啦。"
        )

    async def test_denied_click_picks_custom_reply_and_mentions(self):
        await self.deny_hello(deny_replies=["{{at}} 这不是你的菜单"])
        await self.handler.handle(
            self.api, self.interaction(user="other", token_user="owner")
        )
        self.assertEqual(
            self.api.calls[1][1]["content"],
            '<qqbot-at-user id="other" /> 这不是你的菜单',
        )

    async def test_empty_deny_replies_reject_silently(self):
        await self.deny_hello(deny_replies=[])
        await self.handler.handle(
            self.api, self.interaction(user="other", token_user="owner")
        )
        self.assertEqual(self.api.calls, [("ack", "click-1", 4)])

    async def test_deny_reply_cooldown_silences_repeated_clicks(self):
        from core.deny import DenyCooldown

        self.handler.plugin.deny_cooldown = DenyCooldown(10)
        await self.deny_hello()
        for event_id in ("click-1", "click-2"):
            await self.handler.handle(
                self.api,
                self.interaction(user="other", token_user="owner", event_id=event_id),
            )
        self.assertEqual(self.api.calls[-1], ("ack", "click-2", 4))
        self.assertEqual(sum(call[0] == "send" for call in self.api.calls), 1)
        # 拦截不影响本人正常使用。
        await self.handler.handle(
            self.api,
            self.interaction(user="owner", token_user="owner", event_id="click-3"),
        )
        self.assertEqual(self.api.calls[-1][1]["content"], "回调成功")

    async def test_llm_callback_renders_prompt_and_mentions_clicker(self):
        provider = self.enable_llm()
        await self.set_hello(
            action={"type": "callback_llm", "value": "夸夸 {user}", "at_user": True}
        )
        await self.handler.handle(
            self.api, self.interaction(user="clicker"), platform=self.platform
        )
        self.assertEqual(self.api.calls[0], ("ack", "click-1", 0))
        self.assertEqual(provider.calls[0]["prompt"], "夸夸 clicker")
        self.assertEqual(provider.umo, "qq-test:GroupMessage:group-1")
        self.assertEqual(
            self.api.calls[1][1]["content"],
            '<qqbot-at-user id="clicker" /> 今天也要好好吃饭。',
        )

    async def test_llm_callback_without_switch_does_not_mention(self):
        self.enable_llm()
        await self.set_hello(action={"type": "callback_llm", "value": "夸夸 {user}"})
        await self.handler.handle(
            self.api, self.interaction(user="clicker"), platform=self.platform
        )
        self.assertEqual(self.api.calls[1][1]["content"], "今天也要好好吃饭。")

    async def test_llm_failure_hides_error_details(self):
        self.enable_llm(error=RuntimeError("secret upstream detail"))
        await self.set_hello(action={"type": "callback_llm", "value": "说一句"})
        await self.handler.handle(self.api, self.interaction(), platform=self.platform)
        content = self.api.calls[1][1]["content"]
        self.assertNotIn("secret", content)
        self.assertEqual(content, "我这边没想出来要说啥，稍后再戳一次吧。")

    async def test_llm_cooldown_reports_too_frequent(self):
        provider = self.enable_llm(cooldown=10)
        await self.set_hello(action={"type": "callback_llm", "value": "说一句"})
        await self.handler.handle(self.api, self.interaction(), platform=self.platform)
        await self.handler.handle(
            self.api, self.interaction(event_id="click-2"), platform=self.platform
        )
        self.assertEqual(self.api.calls[-1], ("ack", "click-2", 2))
        await self.handler.handle(
            self.api,
            self.interaction(user="user-2", event_id="click-3"),
            platform=self.platform,
        )
        self.assertEqual(self.api.calls[-2], ("ack", "click-3", 0))
        self.assertEqual(len(provider.calls), 2)


if __name__ == "__main__":
    unittest.main()
