import unittest

from core.models import ButtonValidationError, default_preset, normalize_preset


class ModelTests(unittest.TestCase):
    def test_callback_command_preserves_arguments_and_requires_command(self):
        preset = default_preset()
        action = {"type": "callback_command", "value": "/天气 北京 3"}
        preset["rows"][0][0]["action"] = action
        self.assertEqual(normalize_preset(preset)["rows"][0][0]["action"], action)
        with self.assertRaisesRegex(ButtonValidationError, "功能按钮"):
            normalize_preset(preset, allow_functions=False)
        for invalid in ("/", "/ 天气", "/qqbtn_action token", "qqbtn_action token"):
            action["value"] = invalid
            with self.subTest(value=invalid), self.assertRaises(ButtonValidationError):
                normalize_preset(preset)

    def test_default_preset_is_valid(self):
        preset = normalize_preset(default_preset())
        self.assertEqual(preset["id"], "starter_menu")
        self.assertEqual(len(preset["rows"]), 2)

    def test_http_link_is_rejected_by_default(self):
        preset = default_preset()
        preset["rows"][0][1]["action"]["value"] = "http://example.com"
        with self.assertRaisesRegex(ButtonValidationError, "HTTPS"):
            normalize_preset(preset)

    def test_duplicate_button_id_is_rejected(self):
        preset = default_preset()
        preset["rows"][1][0]["id"] = preset["rows"][0][0]["id"]
        with self.assertRaisesRegex(ButtonValidationError, "重复"):
            normalize_preset(preset)

    def test_function_actions_can_be_disabled(self):
        with self.assertRaisesRegex(ButtonValidationError, "功能按钮"):
            normalize_preset(default_preset(), allow_functions=False)

    def test_specific_user_permission_requires_openid(self):
        preset = default_preset()
        preset["rows"][0][0]["permission"] = {"type": 0, "user_ids": []}
        with self.assertRaisesRegex(ButtonValidationError, "OpenID"):
            normalize_preset(preset)

    def test_markdown_image_and_triggers_are_normalized(self):
        preset = default_preset()
        preset["content"] = "# 菜单\n**欢迎**"
        preset["image_url"] = "https://example.com/menu.png"
        preset["image_width"] = 640
        preset["image_height"] = 360
        preset["triggers"] = ["/导航", "/menu"]
        normalized = normalize_preset(preset)
        self.assertEqual(normalized["triggers"], ["/导航", "/menu"])
        self.assertEqual(normalized["image_width"], 640)

    def test_invalid_image_and_trigger_are_rejected(self):
        preset = default_preset()
        preset["image_url"] = "http://example.com/menu.png"
        with self.assertRaisesRegex(ButtonValidationError, "HTTPS"):
            normalize_preset(preset)
        preset["image_url"] = ""
        preset["triggers"] = ["导航"]
        with self.assertRaisesRegex(ButtonValidationError, "自定义指令"):
            normalize_preset(preset)


if __name__ == "__main__":
    unittest.main()
