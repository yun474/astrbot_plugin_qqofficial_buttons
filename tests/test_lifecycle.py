import importlib.util
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from astrbot.core.pipeline.waking_check.stage import build_unique_session_id
from astrbot.core.platform.message_session import MessageSession
from astrbot.core.platform.message_type import MessageType
from astrbot.core.star.filter.permission import PermissionType, PermissionTypeFilter
from astrbot.core.star.star_handler import star_handlers_registry

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = "buttons_lifecycle_test_plugin"
package = types.ModuleType(PACKAGE)
package.__path__ = [str(ROOT)]
sys.modules[PACKAGE] = package
spec = importlib.util.spec_from_file_location(f"{PACKAGE}.main", ROOT / "main.py")
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)


class LifecycleTests(unittest.IsolatedAsyncioTestCase):
    async def test_unique_callback_session_matches_qq_pipeline_permissions(self):
        config = {
            "plugin_set": ["*"],
            "platform_settings": {"unique_session": True},
        }
        self.context.get_config = lambda umo: config
        for adapter in ("qq_official", "qq_official_webhook"):
            for group_field in ("group_openid", "channel_id"):
                with self.subTest(adapter=adapter, group_field=group_field):
                    platform = types.SimpleNamespace(
                        meta=lambda: types.SimpleNamespace(id="qq-test", name=adapter)
                    )
                    interaction = types.SimpleNamespace(
                        **{
                            group_field: "group",
                            "data": types.SimpleNamespace(
                                resolved=types.SimpleNamespace(user_id="user")
                            ),
                        }
                    )
                    event = types.SimpleNamespace(
                        get_platform_name=lambda: adapter,
                        get_sender_id=lambda: "user",
                        get_group_id=lambda: "group",
                    )
                    umo = str(
                        MessageSession(
                            "qq-test",
                            MessageType.GROUP_MESSAGE,
                            build_unique_session_id(event),
                        )
                    )
                    settings = config["platform_settings"]
                    settings.update(enable_id_white_list=False, id_whitelist=[])
                    with (
                        patch(
                            "astrbot.core.star.session_llm_manager.SessionServiceManager.is_session_enabled",
                            new_callable=AsyncMock,
                            side_effect=lambda key: key != umo,
                        ) as session,
                        patch(
                            "astrbot.core.star.session_plugin_manager.SessionPluginManager.is_plugin_enabled_for_session",
                            new_callable=AsyncMock,
                            return_value=True,
                        ) as plugin,
                    ):
                        self.assertFalse(
                            await self.plugin.callback_allowed(platform, interaction)
                        )
                        session.assert_awaited_with(umo)
                        session.side_effect = None
                        session.return_value = True
                        plugin.side_effect = lambda key, name: key != umo
                        self.assertFalse(
                            await self.plugin.callback_allowed(platform, interaction)
                        )
                        plugin.assert_awaited_with(umo, module.PLUGIN_NAME)
                        plugin.side_effect = None
                        plugin.return_value = True
                        settings.update(enable_id_white_list=True, id_whitelist=[umo])
                        self.assertTrue(
                            await self.plugin.callback_allowed(platform, interaction)
                        )
                        settings["id_whitelist"] = ["qq-test:GroupMessage:user_group"]
                        self.assertFalse(
                            await self.plugin.callback_allowed(platform, interaction)
                        )

    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.context = types.SimpleNamespace(
            registered_web_apis=[],
            add_llm_tools=lambda tool: None,
            platform_manager=types.SimpleNamespace(get_insts=lambda: []),
        )
        self.context.register_web_api = lambda *args: (
            self.context.registered_web_apis.append(args)
        )
        with patch.object(
            module.StarTools, "get_data_dir", return_value=self.temp.name
        ):
            self.plugin = module.QQOfficialButtonsPlugin(self.context)
        self.sync = patch(
            "astrbot.core.star.command_management.sync_command_configs",
            new_callable=AsyncMock,
        )
        self.sync_mock = self.sync.start()
        self.addCleanup(self.sync.stop)
        self.permissions = patch(
            "astrbot.api.sp.global_get", new_callable=AsyncMock, return_value={}
        )
        self.permission_store = self.permissions.start()
        self.addCleanup(self.permissions.stop)

    async def asyncTearDown(self):
        await self.plugin.terminate()
        self.temp.cleanup()

    async def test_refresh_preserves_command_filters_and_unload_removes_routes(self):
        await self.plugin.initialize()
        self.sync_mock.assert_not_awaited()
        handler = self.plugin._trigger_handlers[0]
        permission = PermissionTypeFilter(PermissionType.ADMIN)
        handler.event_filters.append(permission)
        handler.enabled = False
        await self.plugin._refresh_trigger_commands()
        self.assertIs(self.plugin._trigger_handlers[0], handler)
        self.assertIn(permission, handler.event_filters)
        self.assertFalse(handler.enabled)
        self.assertEqual(sum(h is handler for h in star_handlers_registry), 1)
        await self.plugin.terminate()
        self.assertEqual(self.context.registered_web_apis, [])
        self.assertNotIn(handler, list(star_handlers_registry))

    async def test_saved_admin_permission_is_restored_after_dynamic_registration(self):
        self.plugin._register_trigger_commands()
        handler = self.plugin._trigger_handlers[0]
        self.permission_store.return_value = {
            module.PLUGIN_NAME: {handler.handler_name: {"permission": "admin"}}
        }
        await self.plugin._refresh_trigger_commands()
        filters = [
            f for f in handler.event_filters if isinstance(f, PermissionTypeFilter)
        ]
        self.assertEqual(len(filters), 1)
        self.assertEqual(filters[0].permission_type, PermissionType.ADMIN)

    async def test_native_callbacks_respect_session_plugin_and_whitelist_settings(self):
        config = {"plugin_set": ["*"], "admins_id": [], "platform_settings": {}}
        self.context.get_config = lambda umo: config
        platform = types.SimpleNamespace(
            meta=lambda: types.SimpleNamespace(id="qq-test")
        )
        interaction = types.SimpleNamespace(
            group_openid="group", group_member_openid="user"
        )
        with (
            patch(
                "astrbot.core.star.session_llm_manager.SessionServiceManager.is_session_enabled",
                new_callable=AsyncMock,
                return_value=True,
            ) as session,
            patch(
                "astrbot.core.star.session_plugin_manager.SessionPluginManager.is_plugin_enabled_for_session",
                new_callable=AsyncMock,
                return_value=True,
            ) as plugin,
        ):
            self.assertTrue(await self.plugin.callback_allowed(platform, interaction))
            config["plugin_set"] = []
            self.assertFalse(await self.plugin.callback_allowed(platform, interaction))
            config["plugin_set"] = ["*"]
            config["platform_settings"] = {
                "enable_id_white_list": True,
                "id_whitelist": ["another"],
            }
            self.assertFalse(await self.plugin.callback_allowed(platform, interaction))
            config["platform_settings"]["id_whitelist"] = ["group"]
            self.assertTrue(await self.plugin.callback_allowed(platform, interaction))
            plugin.return_value = False
            self.assertFalse(await self.plugin.callback_allowed(platform, interaction))
            plugin.return_value = True
            session.return_value = False
            self.assertFalse(await self.plugin.callback_allowed(platform, interaction))
