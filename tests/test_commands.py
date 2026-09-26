"""Integration tests using AstrBot's real command filters and QQ message events."""

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from botpy.api import BotAPI
from botpy.http import Route

from astrbot.api.platform import PlatformMetadata
from astrbot.core.pipeline.waking_check.stage import WakingCheckStage
from astrbot.core.star.filter.command import CommandFilter
from astrbot.core.star.filter.permission import PermissionType, PermissionTypeFilter
from astrbot.core.star.session_plugin_manager import SessionPluginManager
from astrbot.core.star.star import StarMetadata, star_map
from astrbot.core.star.star_handler import (
    EventType,
    StarHandlerMetadata,
    star_handlers_registry,
)

from core.callbacks import QQOfficialCallbackHandler
from core.commands import build_command_event
from core.models import default_preset
from core.security import create_action_token, parse_action_token
from core.sender import QQOfficialButtonSender
from core.storage import ButtonStorage


class RecordingHttp:
    def __init__(self):
        self.calls = []

    async def request(self, route, **kwargs):
        self.calls.append((route.path.format_map(route.parameters), kwargs["json"]))
        return {"id": "reply"}


class CommandTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.http = RecordingHttp()
        self.client = SimpleNamespace(api=BotAPI(self.http))
        self.events = []
        self.platform_name = "qq_official"
        self.platform = SimpleNamespace(
            meta=lambda: PlatformMetadata(self.platform_name, "test", "qq-test"),
            get_client=lambda: self.client,
            commit_event=self.events.append,
            intents=SimpleNamespace(interaction=False, value=1),
        )
        self.config = {
            "wake_prefix": ["!"],
            "admins_id": ["admin"],
            "platform_settings": {},
        }
        self.context = SimpleNamespace(
            get_config=lambda umo: self.config,
            platform_manager=SimpleNamespace(get_insts=lambda: [self.platform]),
        )
        self.module = "qq_callback_integration_test"
        star_map[self.module] = StarMetadata(name=self.module)
        self.addCleanup(star_map.pop, self.module)

        async def command_handler(_self, event, city: str, days: int = 1):
            yield event.plain_result(f"{city}:{days}")

        self.handler = StarHandlerMetadata(
            event_type=EventType.AdapterMessageEvent,
            handler_full_name=f"{self.module}.weather",
            handler_name="weather",
            handler_module_path=self.module,
            handler=command_handler,
            event_filters=[],
        )
        self.handler.event_filters = [
            CommandFilter("天气", alias={"weather"}, handler_md=self.handler)
        ]
        star_handlers_registry.append(self.handler)
        self.addCleanup(star_handlers_registry.remove, self.handler)

    def interaction(self, **overrides):
        data = dict(
            id="interaction-1",
            event_id="event-1",
            group_openid="group-1",
            group_member_openid="user-1",
            user_openid=None,
            channel_id=None,
            data=SimpleNamespace(
                resolved=SimpleNamespace(user_id=None, button_data="")
            ),
        )
        return SimpleNamespace(**(data | overrides))

    def build(self, value="/天气 北京 3", **overrides):
        return build_command_event(
            self.context, self.platform, self.interaction(**overrides), value
        )

    async def wake(self, event):
        stage = WakingCheckStage()
        await stage.initialize(
            SimpleNamespace(
                astrbot_config=self.config, db_helper=None, astrbot_config_id="test"
            )
        )

        async def keep_handlers(_event, handlers):
            return handlers

        with patch.object(
            SessionPluginManager,
            "filter_handlers_by_session",
            side_effect=keep_handlers,
        ):
            await stage.process(event)

    async def test_native_pipeline_parses_alias_arguments_and_replies_with_event_id(
        self,
    ):
        event = self.build("/weather 北京 3")
        self.assertEqual(event.message_str, "!weather 北京 3")
        self.assertEqual(event.get_sender_id(), "user-1")
        self.assertEqual(event.get_group_id(), "group-1")
        self.assertTrue(event.call_llm)  # Suppresses automatic LLM fallback in AstrBot.
        await self.wake(event)
        self.assertIn(self.handler, event.get_extra("activated_handlers"))
        params = event.get_extra("handlers_parsed_params")[
            self.handler.handler_full_name
        ]
        self.assertEqual(params, {"city": "北京", "days": 3})
        async for result in self.handler.handler(None, event, **params):
            await event.send(result)
        path, payload = self.http.calls[-1]
        self.assertEqual(path, "/v2/groups/group-1/messages")
        self.assertEqual(payload["event_id"], "event-1")
        self.assertNotIn("msg_id", payload)
        self.assertIn("北京:3", str(payload))
        self.assertIs(self.client.api._http, self.http)

    async def test_admin_command_rejects_member_and_accepts_actual_admin(self):
        self.handler.event_filters.append(PermissionTypeFilter(PermissionType.ADMIN))
        denied = self.build()
        await self.wake(denied)
        self.assertTrue(denied.is_stopped())
        self.assertIn("权限不足", str(self.http.calls[-1]))
        allowed = self.build(group_member_openid="admin")
        await self.wake(allowed)
        self.assertTrue(allowed.is_admin())
        self.assertIn(self.handler, allowed.get_extra("activated_handlers"))

    async def test_bad_parameters_use_framework_error_reply(self):
        event = self.build("/天气 北京 invalid")
        await self.wake(event)
        self.assertTrue(event.is_stopped())
        self.assertIn("参数", str(self.http.calls[-1]))
        self.assertEqual(self.http.calls[-1][1]["event_id"], "event-1")

    async def test_custom_prefix_and_bare_commands_preserve_arguments(self):
        for prefixes, value in (
            (["!"], "!天气 北京 3"),
            (["!"], "天气 北京 3"),
            (["云云 "], "云云 天气 北京 3"),
            (["!", "!!"], "!!天气 北京 3"),
            ([""], "天气 北京 3"),
        ):
            with self.subTest(prefixes=prefixes, value=value):
                self.config["wake_prefix"] = prefixes
                event = self.build(value)
                await self.wake(event)
                params = event.get_extra("handlers_parsed_params")[
                    self.handler.handler_full_name
                ]
                self.assertEqual(params, {"city": "北京", "days": 3})
        with self.assertRaisesRegex(ValueError, "内部动作"):
            self.config["wake_prefix"] = ["!"]
            self.build("!qqbtn_action token")

    async def test_subcommand_names_and_empty_wake_prefix(self):
        self.handler.event_filters = [
            CommandFilter(
                "天气", handler_md=self.handler, parent_command_names=["工具"]
            )
        ]
        self.config["wake_prefix"] = []
        event = self.build("/工具 天气 北京 2")
        await self.wake(event)
        self.assertIn(self.handler, event.get_extra("activated_handlers"))
        self.assertEqual(
            event.get_extra("handlers_parsed_params")[self.handler.handler_full_name][
                "days"
            ],
            2,
        )

    async def test_unknown_and_disabled_commands_do_not_create_events(self):
        with self.assertRaisesRegex(ValueError, "不存在"):
            self.build("/not_registered x")
        self.handler.enabled = False
        with self.assertRaisesRegex(ValueError, "停用"):
            self.build()

    async def test_c2c_and_channel_webhook_reply_targets(self):
        self.platform_name = "qq_official_webhook"
        for overrides, path, user in (
            (
                {
                    "group_openid": None,
                    "group_member_openid": None,
                    "user_openid": "private-user",
                },
                "/v2/users/private-user/messages",
                "private-user",
            ),
            (
                {
                    "group_openid": None,
                    "group_member_openid": None,
                    "channel_id": "channel-1",
                    "guild_id": "guild-1",
                    "data": SimpleNamespace(
                        resolved=SimpleNamespace(user_id="channel-user")
                    ),
                },
                "/channels/channel-1/messages",
                "channel-user",
            ),
        ):
            event = self.build(**overrides)
            self.assertEqual(event.get_platform_name(), self.platform_name)
            self.assertEqual(event.get_sender_id(), user)
            await event.send(event.plain_result("ok"))
            self.assertEqual(self.http.calls[-1][0], path)
            self.assertEqual(self.http.calls[-1][1]["event_id"], "event-1")
            self.assertNotIn("msg_id", self.http.calls[-1][1])

    async def test_reply_context_is_local_and_preserves_upload_and_other_targets(self):
        first = self.build()
        second = self.build(event_id="event-2", id="interaction-2")
        await first.bot.api.post_group_message(group_openid="group-1", content="1")
        await second.bot.api.post_group_message(group_openid="group-1", content="2")
        await self.client.api.post_group_message(
            group_openid="group-1", msg_id="real-message", content="3"
        )
        await first.bot.api.post_group_message(
            group_openid="other-group", msg_id="other-message", content="4"
        )
        await first.bot.api._http.request(
            Route("POST", "/v2/groups/{group_openid}/files", group_openid="group-1"),
            json={"url": "https://example.com/image.png"},
        )
        self.assertEqual(
            [call[1].get("event_id") for call in self.http.calls],
            ["event-1", "event-2", None, None, None],
        )
        self.assertEqual(self.http.calls[2][1]["msg_id"], "real-message")
        self.assertEqual(self.http.calls[3][1]["msg_id"], "other-message")
        sender = QQOfficialButtonSender(
            signing_secret="test", action_command="/qqbtn_action"
        )
        preset = default_preset() | {
            "content": "{{at}} ![image](https://example.com/a.png)"
        }
        await sender.send(first, preset)
        payload = self.http.calls[-1][1]
        self.assertTrue(payload["markdown"]["force_verify_image_resource"])
        self.assertEqual(payload["event_id"], "event-1")
        self.assertIn('id="user-1"', payload["markdown"]["content"])

    async def test_callback_acknowledges_and_enqueues_once(self):
        with tempfile.TemporaryDirectory() as temp:
            storage = ButtonStorage(Path(temp) / "buttons.json")
            preset = default_preset()
            preset["rows"][1][0]["action"] = {
                "type": "callback_command",
                "value": "/天气 北京 3",
            }
            await storage.save(preset)
            sender = QQOfficialButtonSender(
                signing_secret=storage.signing_secret, action_command="/qqbtn_action"
            )
            keyboard_action = sender.build_keyboard(preset)["content"]["rows"][1][
                "buttons"
            ][0]["action"]
            self.assertEqual(keyboard_action["type"], 1)
            self.assertEqual(
                parse_action_token(storage.signing_secret, keyboard_action["data"][6:]),
                ("starter_menu", "hello"),
            )
            plugin = SimpleNamespace(
                context=self.context,
                storage=storage,
                sender=sender,
                callback_allowed=AsyncMock(return_value=True),
            )
            callback = QQOfficialCallbackHandler(plugin, lambda text: None)
            callback.bind_available()
            self.addCleanup(callback.unbind)
            interaction = self.interaction()
            token = create_action_token(
                storage.signing_secret, "starter_menu", "hello", preset["rows"][1][0]
            )
            interaction.data.resolved.button_data = f"qqbtn:{token}"
            await self.client.on_interaction_create(interaction)
            await self.client.on_interaction_create(interaction)
            self.assertEqual(len(self.events), 1)
            self.assertEqual(self.http.calls[0][1]["code"], 0)
            self.assertEqual(self.http.calls[-1][1]["code"], 3)
            await self.wake(self.events[0])
            self.assertIn(self.handler, self.events[0].get_extra("activated_handlers"))


if __name__ == "__main__":
    unittest.main()
