from __future__ import annotations

from hashlib import sha1
from pathlib import Path
from typing import Any

from astrbot import logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.star import Context, Star, StarTools
from astrbot.api.web import error_response, json_response, request
from astrbot.core.config.astrbot_config import AstrBotConfig
from astrbot.core.star.filter.command import CommandFilter
from astrbot.core.star.filter.platform_adapter_type import PlatformAdapterTypeFilter
from astrbot.core.star.star_handler import (
    EventType,
    StarHandlerMetadata,
    star_handlers_registry,
)

from .core.callbacks import QQOfficialCallbackHandler
from .core.models import ButtonValidationError
from .core.security import button_token_matches, parse_action_token
from .core.sender import QQOfficialButtonSender
from .core.storage import ButtonStorage
from .core.tool import QQOfficialButtonsTool


PLUGIN_NAME = "astrbot_plugin_qqofficial_buttons"


class QQOfficialButtonsPlugin(Star):
    def __init__(self, context: Context, config: AstrBotConfig | None = None) -> None:
        super().__init__(context)
        self.config = config or {}
        self.max_rows = self._int_config("max_rows", 5, 1, 5)
        self.max_per_row = self._int_config("max_buttons_per_row", 5, 1, 5)
        self.allow_http_links = bool(self.config.get("allow_http_links", False))
        self.allow_functions = bool(self.config.get("enable_function_buttons", True))
        self.enable_dynamic_buttons = bool(
            self.config.get("enable_llm_dynamic_buttons", False)
        )
        self.force_verify_image_resource = bool(
            self.config.get("force_verify_image_resource", True)
        )
        self.image_retry_attempts = self._int_config("image_retry_attempts", 3, 1, 10)
        message_mode = str(self.config.get("keyboard_message_mode", "auto"))

        data_dir = Path(StarTools.get_data_dir(PLUGIN_NAME))
        self.storage = ButtonStorage(
            data_dir / "buttons.json",
            max_rows=self.max_rows,
            max_per_row=self.max_per_row,
            allow_http_links=self.allow_http_links,
            allow_functions=self.allow_functions,
        )
        self.sender = QQOfficialButtonSender(
            signing_secret=self.storage.signing_secret,
            action_command="/qqbtn_action",
            message_mode=message_mode,
            allow_functions=self.allow_functions,
            allow_http_links=self.allow_http_links,
            force_verify_image_resource=self.force_verify_image_resource,
            image_retry_attempts=self.image_retry_attempts,
            log=logger.info,
        )
        self._trigger_handlers: list[StarHandlerMetadata] = []
        self.callbacks = QQOfficialCallbackHandler(self, logger.info)
        context.add_llm_tools(QQOfficialButtonsTool(self))
        self._register_web_apis(context)
        logger.info("[QQ官Bot按钮] 插件加载完成，云云把按钮工具摆好啦。")

    def _int_config(self, key: str, default: int, minimum: int, maximum: int) -> int:
        try:
            value = int(self.config.get(key, default))
        except (TypeError, ValueError):
            value = default
        return min(max(value, minimum), maximum)

    def _register_web_apis(self, context: Context) -> None:
        apis = [
            ("state", self.web_state, ["GET"], "读取按钮编辑器数据"),
            ("preset/save", self.web_save_preset, ["POST"], "保存按钮组"),
            ("preset/delete", self.web_delete_preset, ["POST"], "删除按钮组"),
            ("preset/duplicate", self.web_duplicate_preset, ["POST"], "复制按钮组"),
            ("presets/import", self.web_import_presets, ["POST"], "导入按钮组"),
        ]
        for endpoint, handler, methods, description in apis:
            context.register_web_api(
                f"/{PLUGIN_NAME}/{endpoint}", handler, methods, description
            )

    async def initialize(self) -> None:
        self._register_trigger_commands()
        await self._restore_trigger_permissions()
        self.callbacks.bind_available()

    @filter.on_platform_loaded(priority=1000)
    async def on_platform_loaded(self) -> None:
        self.callbacks.bind_available()

    async def callback_allowed(self, platform: Any, interaction: Any) -> bool:
        from astrbot.core.platform.message_session import MessageSession
        from astrbot.core.platform.message_type import MessageType
        from astrbot.core.star.session_llm_manager import SessionServiceManager
        from astrbot.core.star.session_plugin_manager import SessionPluginManager

        group = getattr(interaction, "group_openid", None) or getattr(
            interaction, "channel_id", None
        )
        resolved = getattr(getattr(interaction, "data", None), "resolved", None)
        user = (
            getattr(interaction, "group_member_openid", None)
            or getattr(interaction, "user_openid", None)
            or getattr(resolved, "user_id", None)
        )
        if platform is None or not user:
            return False
        message_type = (
            MessageType.GROUP_MESSAGE if group else MessageType.FRIEND_MESSAGE
        )
        session = MessageSession(platform.meta().id, message_type, str(group or user))
        config = self.context.get_config(str(session))
        enabled = config.get("plugin_set", ["*"])
        if enabled != ["*"] and PLUGIN_NAME not in enabled:
            return False
        settings = config.get("platform_settings", {})
        if group and settings.get("unique_session", False):
            session.session_id = f"{user}_{group}"
        umo = str(session)
        whitelist = {
            str(value).strip()
            for value in settings.get("id_whitelist", [])
            if str(value).strip()
        }
        exempt_key = (
            "wl_ignore_admin_on_group" if group else "wl_ignore_admin_on_friend"
        )
        exempt = str(user) in config.get("admins_id", []) and settings.get(
            exempt_key, False
        )
        if settings.get("enable_id_white_list") and whitelist and not exempt:
            if umo not in whitelist and str(group or "") not in whitelist:
                return False
        return await SessionServiceManager.is_session_enabled(
            umo
        ) and await SessionPluginManager.is_plugin_enabled_for_session(umo, PLUGIN_NAME)

    def _register_trigger_commands(self) -> None:
        existing = {handler.handler_name: handler for handler in self._trigger_handlers}
        self._trigger_handlers = []

        module = type(self).__module__
        platforms = (
            filter.PlatformAdapterType.QQOFFICIAL
            | filter.PlatformAdapterType.QQOFFICIAL_WEBHOOK
        )
        for preset in self.storage.list():
            if not preset["enabled"]:
                continue
            for trigger in preset["triggers"]:
                preset_id = preset["id"]
                name = (
                    f"menu_{sha1(f'{preset_id}:{trigger}'.encode()).hexdigest()[:16]}"
                )

                if name in existing:
                    handler = existing.pop(name)
                    handler.desc = f"发送按钮组：{preset['name']}"
                    self._trigger_handlers.append(handler)
                    continue

                async def handle(event: AstrMessageEvent, *, _preset_id=preset_id):
                    current = self.storage.get(_preset_id)
                    if not current or not current["enabled"]:
                        return
                    try:
                        await self.sender.send(event, current)
                        event.stop_event()
                    except Exception as exc:
                        logger.exception("[QQ官Bot按钮] 自定义指令发送失败")
                        yield event.plain_result(f"菜单没发出去：{exc}")

                handler = StarHandlerMetadata(
                    event_type=EventType.AdapterMessageEvent,
                    handler_full_name=f"{module}_{name}",
                    handler_name=name,
                    handler_module_path=module,
                    handler=handle,
                    event_filters=[],
                    desc=f"发送按钮组：{preset['name']}",
                    extras_configs={"priority": 10},
                )
                handler.event_filters = [
                    PlatformAdapterTypeFilter(platforms),
                    CommandFilter(trigger[1:], handler_md=handler),
                ]
                star_handlers_registry.append(handler)
                self._trigger_handlers.append(handler)

        for handler in existing.values():
            star_handlers_registry.remove(handler)

    async def _refresh_trigger_commands(self) -> None:
        from astrbot.core.star.command_management import sync_command_configs

        self._register_trigger_commands()
        await self._restore_trigger_permissions()
        await sync_command_configs()

    async def _restore_trigger_permissions(self) -> None:
        from astrbot.api import sp
        from astrbot.core.star.filter.permission import (
            PermissionType,
            PermissionTypeFilter,
        )

        # Dynamic handlers are created after AstrBot's normal permission restoration.
        permissions = (await sp.global_get("alter_cmd", {})).get(PLUGIN_NAME, {})
        for handler in self._trigger_handlers:
            saved = permissions.get(handler.handler_name, {}).get("permission")
            if not saved:
                continue
            permission = PermissionType.__members__.get(saved.upper())
            if permission is None:
                raise RuntimeError(f"无法恢复菜单权限：{saved}")
            current = next(
                (
                    f
                    for f in handler.event_filters
                    if isinstance(f, PermissionTypeFilter)
                ),
                None,
            )
            if current:
                current.permission_type = permission
            else:
                handler.event_filters.append(PermissionTypeFilter(permission))

    @filter.command("qqbtn_action")
    async def internal_action_command(self, event: AstrMessageEvent, token: str = ""):
        """处理按钮内部动作，请勿手动调用。"""
        if not self.allow_functions or not self.sender.is_supported_event(event):
            event.stop_event()
            return
        parsed = parse_action_token(self.storage.signing_secret, token)
        if parsed is None:
            yield event.plain_result("这个按钮动作无效或已损坏。")
            event.stop_event()
            return
        preset_id, button_id = parsed
        preset = self.storage.get(preset_id)
        button = self._find_button(preset, button_id) if preset else None
        if (
            not preset
            or not preset["enabled"]
            or button is None
            or not button_token_matches(
                self.storage.signing_secret, token, preset_id, button
            )
        ):
            yield event.plain_result("这个按钮对应的功能已经不存在啦。")
            event.stop_event()
            return
        if not self._button_allowed(event, button):
            yield event.plain_result("这个按钮没给你操作权限，别乱戳啦。")
            event.stop_event()
            return

        action = button["action"]
        if action["type"] == "send_text":
            yield event.plain_result(action["value"])
        elif action["type"] == "show_preset":
            target = self.storage.get(action["value"])
            if not target or not target["enabled"]:
                yield event.plain_result("目标按钮组不存在或已停用。")
            else:
                try:
                    await self.sender.send(event, target)
                except Exception as exc:
                    logger.exception("[QQ官Bot按钮] 跳转按钮组失败")
                    yield event.plain_result(f"目标按钮组没发出去：{exc}")
        else:
            yield event.plain_result("这个内部动作类型不受支持。")
        event.stop_event()

    @staticmethod
    def _find_button(
        preset: dict[str, Any] | None, button_id: str
    ) -> dict[str, Any] | None:
        if not preset:
            return None
        for row in preset["rows"]:
            for button in row:
                if button["id"] == button_id:
                    return button
        return None

    @staticmethod
    def _button_allowed(event: AstrMessageEvent, button: dict[str, Any]) -> bool:
        permission = button["permission"]
        permission_type = permission["type"]
        if permission_type == 2:
            return True
        if permission_type == 1:
            return getattr(event, "role", None) == "admin"
        if permission_type == 0:
            return str(event.get_sender_id()) in permission.get("user_ids", [])
        if permission_type == 3:
            raw = getattr(getattr(event, "message_obj", None), "raw_message", None)
            member = getattr(raw, "member", None)
            roles = {str(role) for role in (getattr(member, "roles", None) or [])}
            return bool(roles.intersection(permission.get("role_ids", [])))
        return False

    async def web_state(self):
        return json_response(
            {
                "presets": self.storage.list(),
                "limits": {
                    "max_rows": self.max_rows,
                    "max_buttons_per_row": self.max_per_row,
                    "allow_http_links": self.allow_http_links,
                    "enable_function_buttons": self.allow_functions,
                    "enable_llm_dynamic_buttons": self.enable_dynamic_buttons,
                },
                "actions": [
                    {
                        "value": "command",
                        "label": "发送指令",
                        "hint": "点击后立即发送文字或 /指令",
                    },
                    {
                        "value": "input",
                        "label": "填入输入框",
                        "hint": "点击后只填入文字，由用户确认发送",
                    },
                    {"value": "link", "label": "打开链接", "hint": "打开 HTTPS 网页"},
                    {
                        "value": "send_text",
                        "label": "回复固定文字",
                        "hint": "由插件回复预设内容",
                    },
                    {
                        "value": "show_preset",
                        "label": "打开另一按钮组",
                        "hint": "发送另一个按钮组",
                    },
                    {
                        "value": "callback_text",
                        "label": "原生回调：回复文字",
                        "hint": "QQ 直接推送点击事件，插件确认后回复固定文字",
                    },
                    {
                        "value": "callback_preset",
                        "label": "原生回调：打开菜单",
                        "hint": "QQ 直接推送点击事件，插件确认后发送另一个菜单",
                    },
                    {
                        "value": "callback_command",
                        "label": "原生回调：执行指令",
                        "hint": "以点击者身份执行，可省略前缀；自行发送 HTTP 或依赖真实消息 ID 的插件可能不兼容，请改用发送指令",
                    },
                ],
            }
        )

    async def web_save_preset(self):
        payload = await request.json(default={})
        try:
            saved = await self.storage.save(payload)
            await self._refresh_trigger_commands()
            return json_response({"preset": saved, "message": "保存成功"})
        except ButtonValidationError as exc:
            return error_response(str(exc), status_code=400)
        except Exception:
            logger.exception("[QQ官Bot按钮] WebUI 保存失败")
            return error_response("保存失败，请查看 AstrBot 日志", status_code=500)

    async def web_delete_preset(self):
        payload = await request.json(default={})
        if not isinstance(payload, dict):
            return error_response("请求内容必须是对象", status_code=400)
        preset_id = str(payload.get("id") or "").strip()
        if not preset_id:
            return error_response("缺少按钮组 ID")
        deleted = await self.storage.delete(preset_id)
        if not deleted:
            return error_response("按钮组不存在", status_code=404)
        await self._refresh_trigger_commands()
        return json_response({"deleted": True})

    async def web_duplicate_preset(self):
        payload = await request.json(default={})
        if not isinstance(payload, dict):
            return error_response("请求内容必须是对象", status_code=400)
        preset_id = str(payload.get("id") or "").strip()
        duplicated = await self.storage.duplicate(preset_id)
        if duplicated is None:
            return error_response("按钮组不存在", status_code=404)
        await self._refresh_trigger_commands()
        return json_response({"preset": duplicated})

    async def web_import_presets(self):
        payload = await request.json(default={})
        presets = payload.get("presets") if isinstance(payload, dict) else None
        try:
            imported = await self.storage.replace_all(presets)
            await self._refresh_trigger_commands()
            return json_response({"presets": imported, "count": len(imported)})
        except (ValueError, ButtonValidationError) as exc:
            return error_response(str(exc), status_code=400)
        except Exception:
            logger.exception("[QQ官Bot按钮] WebUI 导入失败")
            return error_response("导入失败，请查看 AstrBot 日志", status_code=500)

    async def terminate(self) -> None:
        for handler in self._trigger_handlers:
            star_handlers_registry.remove(handler)
        self._trigger_handlers.clear()
        self.callbacks.unbind()
        self.context.registered_web_apis[:] = [
            api
            for api in self.context.registered_web_apis
            if getattr(api[1], "__self__", None) is not self
        ]
        logger.info("[QQ官Bot按钮] 插件已卸载。")
