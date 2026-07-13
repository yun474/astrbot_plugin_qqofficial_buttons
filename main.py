from __future__ import annotations

from pathlib import Path
from typing import Any

from astrbot import logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.star import Context, Star, StarTools
from astrbot.api.web import error_response, json_response, request
from astrbot.core.config.astrbot_config import AstrBotConfig

from .core.models import ButtonValidationError
from .core.security import parse_action_token
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
        )
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

    @filter.command("按钮", alias={"qq按钮", "buttonmenu"})
    async def button_command(self, event: AstrMessageEvent, preset_id: str = ""):
        """发送 QQ 官 Bot 按钮组。用法：/按钮 <按钮组ID>"""
        if not preset_id:
            presets = [item for item in self.storage.list() if item["enabled"]]
            if not presets:
                yield event.plain_result("还没有可用按钮组，先去插件页面新建一个吧。")
                return
            lines = ["可用按钮组："]
            lines.extend(f"- {item['id']}：{item['name']}" for item in presets)
            lines.append("用法：/按钮 按钮组ID")
            yield event.plain_result("\n".join(lines))
            return
        preset = self.storage.get(preset_id)
        if not preset or not preset["enabled"]:
            yield event.plain_result(f"没找到可用按钮组：{preset_id}")
            return
        try:
            await self.sender.send(event, preset)
            event.stop_event()
        except Exception as exc:
            logger.exception("[QQ官Bot按钮] 命令发送失败")
            yield event.plain_result(f"按钮没发出去：{exc}")

    @filter.command("qqbtn_action")
    async def internal_action_command(self, event: AstrMessageEvent, token: str = ""):
        """处理按钮内部动作，请勿手动调用。"""
        parsed = parse_action_token(self.storage.signing_secret, token)
        if parsed is None:
            yield event.plain_result("这个按钮动作无效或已损坏。")
            event.stop_event()
            return
        preset_id, button_id = parsed
        preset = self.storage.get(preset_id)
        button = self._find_button(preset, button_id) if preset else None
        if not preset or not preset["enabled"] or button is None:
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
                ],
            }
        )

    async def web_save_preset(self):
        payload = await request.json(default={})
        try:
            saved = await self.storage.save(payload)
            return json_response({"preset": saved, "message": "保存成功"})
        except ButtonValidationError as exc:
            return error_response(str(exc), status_code=400)
        except Exception:
            logger.exception("[QQ官Bot按钮] WebUI 保存失败")
            return error_response("保存失败，请查看 AstrBot 日志", status_code=500)

    async def web_delete_preset(self):
        payload = await request.json(default={})
        preset_id = str((payload or {}).get("id") or "").strip()
        if not preset_id:
            return error_response("缺少按钮组 ID")
        deleted = await self.storage.delete(preset_id)
        if not deleted:
            return error_response("按钮组不存在", status_code=404)
        return json_response({"deleted": True})

    async def web_duplicate_preset(self):
        payload = await request.json(default={})
        preset_id = str((payload or {}).get("id") or "").strip()
        duplicated = await self.storage.duplicate(preset_id)
        if duplicated is None:
            return error_response("按钮组不存在", status_code=404)
        return json_response({"preset": duplicated})

    async def web_import_presets(self):
        payload = await request.json(default={})
        presets = payload.get("presets") if isinstance(payload, dict) else None
        try:
            imported = await self.storage.replace_all(presets)
            return json_response({"presets": imported, "count": len(imported)})
        except (ValueError, ButtonValidationError) as exc:
            return error_response(str(exc), status_code=400)
        except Exception:
            logger.exception("[QQ官Bot按钮] WebUI 导入失败")
            return error_response("导入失败，请查看 AstrBot 日志", status_code=500)

    async def terminate(self) -> None:
        logger.info("[QQ官Bot按钮] 插件已卸载。")
