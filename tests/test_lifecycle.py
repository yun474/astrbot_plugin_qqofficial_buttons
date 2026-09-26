import importlib.util
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

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
