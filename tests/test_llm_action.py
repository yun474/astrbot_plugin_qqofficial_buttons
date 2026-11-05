import unittest

from core.commands import render_prompt
from core.models import ButtonValidationError, default_preset, normalize_preset


def preset_with_llm_button(value="点我就要说一句每日一言"):
    preset = default_preset()
    preset["rows"][0][0]["action"] = {"type": "callback_llm", "value": value}
    return preset


class CallbackLlmModelTests(unittest.TestCase):
    def test_action_type_is_accepted_and_kept(self):
        action = {"type": "callback_llm", "value": "说一句每日一言"}
        preset = preset_with_llm_button(action["value"])
        self.assertEqual(
            normalize_preset(preset)["rows"][0][0]["action"],
            action | {"at_user": False},
        )

    def test_at_user_switch_is_kept_only_for_llm_button(self):
        preset = preset_with_llm_button()
        preset["rows"][0][0]["action"]["at_user"] = True
        self.assertIs(
            normalize_preset(preset)["rows"][0][0]["action"]["at_user"], True
        )
        # 其他按钮不保存该字段，签名与旧菜单保持一致。
        preset = default_preset()
        preset["rows"][0][0]["action"] = {
            "type": "callback_text",
            "value": "你好",
            "at_user": True,
        }
        self.assertEqual(
            normalize_preset(preset)["rows"][0][0]["action"],
            {"type": "callback_text", "value": "你好"},
        )

    def test_function_button_switch_disables_it(self):
        with self.assertRaisesRegex(ButtonValidationError, "功能按钮"):
            normalize_preset(preset_with_llm_button(), allow_functions=False)

    def test_prompt_follows_common_action_length_limit(self):
        # 提示词不再单独限制，与其他按钮动作内容一样最多 1000 字。
        normalize_preset(preset_with_llm_button("字" * 1000))
        with self.assertRaises(ButtonValidationError):
            normalize_preset(preset_with_llm_button("字" * 1001))

    def test_empty_prompt_is_rejected(self):
        with self.assertRaises(ButtonValidationError):
            normalize_preset(preset_with_llm_button("   "))


class RenderPromptTests(unittest.TestCase):
    def test_user_placeholder_is_replaced_on_demand(self):
        self.assertEqual(
            render_prompt(" 夸夸 {user} ", user="openid-1"), "夸夸 openid-1"
        )
        self.assertEqual(render_prompt(" 来一句每日一言 "), "来一句每日一言")


if __name__ == "__main__":
    unittest.main()
