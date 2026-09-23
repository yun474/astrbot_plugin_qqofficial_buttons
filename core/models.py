from __future__ import annotations

import copy
import re
import uuid
from typing import Any
from urllib.parse import urlparse


class ButtonValidationError(ValueError):
    """Raised when a button preset is unsafe or malformed."""


ACTION_TYPES = {
    "command", "input", "link", "send_text", "show_preset",
    "callback_text", "callback_preset",
}
FUNCTION_ACTIONS = {"send_text", "show_preset", "callback_text", "callback_preset"}
STYLE_VALUES = {0, 1, 3, 4}
ID_PATTERN = re.compile(r"^[a-zA-Z0-9_-]{1,48}$")
TRIGGER_PATTERN = re.compile(r"^/[a-zA-Z0-9_\u4e00-\u9fff-]{1,32}$")


def new_id(prefix: str = "item") -> str:
    return f"{prefix}_{uuid.uuid4().hex[:10]}"


def default_preset() -> dict[str, Any]:
    return {
        "id": "starter_menu",
        "name": "云云的快捷菜单",
        "description": "一个可以直接修改的示例按钮组",
        "content": "想做什么？点下面就行。",
        "image_url": "",
        "image_width": 600,
        "image_height": 300,
        "triggers": [],
        "enabled": True,
        "expose_to_llm": True,
        "rows": [
            [
                {
                    "id": "help",
                    "label": "看看帮助",
                    "visited_label": "帮助已发送",
                    "style": 1,
                    "action": {"type": "command", "value": "/help"},
                    "permission": {"type": 2, "user_ids": [], "role_ids": []},
                },
                {
                    "id": "docs",
                    "label": "AstrBot 文档",
                    "visited_label": "已打开文档",
                    "style": 0,
                    "action": {
                        "type": "link",
                        "value": "https://docs.astrbot.app/",
                    },
                    "permission": {"type": 2, "user_ids": [], "role_ids": []},
                },
            ],
            [
                {
                    "id": "hello",
                    "label": "和云云打招呼",
                    "visited_label": "打过招呼啦",
                    "style": 1,
                    "action": {
                        "type": "send_text",
                        "value": "主人好呀，云云今天也在认真干活。",
                    },
                    "permission": {"type": 2, "user_ids": [], "role_ids": []},
                }
            ],
        ],
    }


def _clean_text(value: Any, field: str, *, maximum: int, required: bool = False) -> str:
    text = str(value or "").strip()
    if required and not text:
        raise ButtonValidationError(f"{field} 不能为空")
    if len(text) > maximum:
        raise ButtonValidationError(f"{field} 不能超过 {maximum} 个字符")
    return text


def _clean_string_list(value: Any, field: str, maximum: int = 100) -> list[str]:
    if value in (None, ""):
        return []
    if not isinstance(value, list):
        raise ButtonValidationError(f"{field} 必须是列表")
    result = []
    for item in value:
        item_text = str(item).strip()
        if item_text and item_text not in result:
            result.append(item_text)
    if len(result) > maximum:
        raise ButtonValidationError(f"{field} 数量不能超过 {maximum}")
    return result


def normalize_permission(raw: Any) -> dict[str, Any]:
    raw = raw if isinstance(raw, dict) else {}
    try:
        permission_type = int(raw.get("type", 2))
    except (TypeError, ValueError) as exc:
        raise ButtonValidationError("按钮权限类型无效") from exc
    if permission_type not in {0, 1, 2, 3}:
        raise ButtonValidationError("按钮权限类型只能是 0、1、2、3")
    result = {
        "type": permission_type,
        "user_ids": _clean_string_list(raw.get("user_ids"), "指定用户"),
        "role_ids": _clean_string_list(raw.get("role_ids"), "指定身份组"),
    }
    if permission_type == 0 and not result["user_ids"]:
        raise ButtonValidationError("指定用户权限至少需要一个用户 OpenID")
    if permission_type == 3 and not result["role_ids"]:
        raise ButtonValidationError("身份组权限至少需要一个身份组 ID")
    return result


def normalize_button(
    raw: Any,
    *,
    allow_http_links: bool = False,
    allow_functions: bool = True,
) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise ButtonValidationError("按钮必须是对象")
    button_id = _clean_text(raw.get("id") or new_id("btn"), "按钮 ID", maximum=48)
    if not ID_PATTERN.fullmatch(button_id):
        raise ButtonValidationError("按钮 ID 只能包含字母、数字、下划线和短横线")
    label = _clean_text(raw.get("label"), "按钮文字", maximum=32, required=True)
    visited_label = _clean_text(
        raw.get("visited_label") or f"{label} ✓",
        "点击后文字",
        maximum=32,
    )
    try:
        style = int(raw.get("style", 0))
    except (TypeError, ValueError) as exc:
        raise ButtonValidationError("按钮样式无效") from exc
    if style not in STYLE_VALUES:
        raise ButtonValidationError("按钮样式不受支持")

    action = raw.get("action")
    if not isinstance(action, dict):
        raise ButtonValidationError(f"按钮“{label}”缺少动作")
    action_type = str(action.get("type") or "").strip()
    if action_type not in ACTION_TYPES:
        raise ButtonValidationError(f"按钮“{label}”的动作类型无效")
    if action_type in FUNCTION_ACTIONS and not allow_functions:
        raise ButtonValidationError("配置已禁止插件功能按钮")
    value = _clean_text(
        action.get("value"), "按钮动作内容", maximum=1000, required=True
    )
    if action_type == "link":
        parsed = urlparse(value)
        allowed_schemes = {"https"} | ({"http"} if allow_http_links else set())
        if parsed.scheme.lower() not in allowed_schemes or not parsed.netloc:
            protocol = "HTTP/HTTPS" if allow_http_links else "HTTPS"
            raise ButtonValidationError(f"链接按钮必须使用有效的 {protocol} 地址")
    if action_type in {"show_preset", "callback_preset"} and not ID_PATTERN.fullmatch(value):
        raise ButtonValidationError("目标按钮组 ID 无效")

    return {
        "id": button_id,
        "label": label,
        "visited_label": visited_label,
        "style": style,
        "action": {"type": action_type, "value": value},
        "permission": normalize_permission(raw.get("permission")),
    }


def normalize_preset(
    raw: Any,
    *,
    max_rows: int = 5,
    max_per_row: int = 5,
    allow_http_links: bool = False,
    allow_functions: bool = True,
) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise ButtonValidationError("按钮组必须是对象")
    preset_id = _clean_text(raw.get("id") or new_id("menu"), "按钮组 ID", maximum=48)
    if not ID_PATTERN.fullmatch(preset_id):
        raise ButtonValidationError("按钮组 ID 只能包含字母、数字、下划线和短横线")
    image_url = _clean_text(raw.get("image_url"), "图片 URL", maximum=1000)
    if image_url:
        parsed_image = urlparse(image_url)
        if parsed_image.scheme.lower() != "https" or not parsed_image.netloc:
            raise ButtonValidationError("图片必须使用公网 HTTPS URL")
    try:
        image_width = int(raw.get("image_width", 600))
        image_height = int(raw.get("image_height", 300))
    except (TypeError, ValueError) as exc:
        raise ButtonValidationError("图片宽高必须是整数") from exc
    if not 1 <= image_width <= 4096 or not 1 <= image_height <= 4096:
        raise ButtonValidationError("图片宽高必须在 1～4096 像素之间")
    triggers = _clean_string_list(raw.get("triggers"), "自定义指令", maximum=20)
    for trigger in triggers:
        if not TRIGGER_PATTERN.fullmatch(trigger):
            raise ButtonValidationError("自定义指令须以 / 开头，只能包含中英文、数字、下划线和短横线")
        if trigger in {"/按钮", "/qq按钮", "/buttonmenu", "/qqbtn_action"}:
            raise ButtonValidationError(f"自定义指令与插件内置指令冲突：{trigger}")
    rows = raw.get("rows")
    if not isinstance(rows, list) or not rows:
        raise ButtonValidationError("按钮组至少需要一行按钮")
    if len(rows) > max_rows:
        raise ButtonValidationError(f"按钮组最多允许 {max_rows} 行")

    clean_rows: list[list[dict[str, Any]]] = []
    seen_button_ids: set[str] = set()
    for row_index, row in enumerate(rows, 1):
        if not isinstance(row, list) or not row:
            raise ButtonValidationError(f"第 {row_index} 行不能为空")
        if len(row) > max_per_row:
            raise ButtonValidationError(f"每行最多允许 {max_per_row} 个按钮")
        clean_row = []
        for raw_button in row:
            button = normalize_button(
                raw_button,
                allow_http_links=allow_http_links,
                allow_functions=allow_functions,
            )
            if button["id"] in seen_button_ids:
                raise ButtonValidationError(f"按钮 ID 重复：{button['id']}")
            seen_button_ids.add(button["id"])
            clean_row.append(button)
        clean_rows.append(clean_row)

    return {
        "id": preset_id,
        "name": _clean_text(raw.get("name"), "按钮组名称", maximum=64, required=True),
        "description": _clean_text(raw.get("description"), "按钮组说明", maximum=240),
        "content": _clean_text(raw.get("content"), "消息正文", maximum=2000),
        "image_url": image_url,
        "image_width": image_width,
        "image_height": image_height,
        "triggers": triggers,
        "enabled": bool(raw.get("enabled", True)),
        "expose_to_llm": bool(raw.get("expose_to_llm", False)),
        "rows": clean_rows,
    }


def clone_preset(preset: dict[str, Any]) -> dict[str, Any]:
    cloned = copy.deepcopy(preset)
    cloned["id"] = new_id("menu")
    cloned["name"] = f"{cloned['name']} - 副本"
    cloned["triggers"] = []
    for row in cloned["rows"]:
        for button in row:
            button["id"] = new_id("btn")
    return cloned
