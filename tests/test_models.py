import unittest

from core.models import ButtonValidationError, default_preset, normalize_preset


class ModelTests(unittest.TestCase):
    def test_default_visited_label_accepts_full_length_titles(self):
        for size in (30, 31, 32):
            for visited in (None, ""):
                with self.subTest(size=size, visited=visited):
                    preset = default_preset()
                    button = preset["rows"][0][0]
                    button["label"] = "字" * size
                    button.pop("visited_label")
                    if visited is not None:
                        button["visited_label"] = visited
                    result = normalize_preset(preset)["rows"][0][0]
                    expected = button["label"] + " ✓" if size <= 30 else button["label"]
                    self.assertEqual(result["visited_label"], expected)
        button["visited_label"] = "字" * 33
        with self.assertRaisesRegex(ButtonValidationError, "点击后文字"):
            normalize_preset(preset)

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

    def test_bot_admin_permission_requires_plugin_action(self):
        preset = default_preset()
        preset["rows"][1][0]["permission"] = {"type": 11}
        preset["rows"][0][0]["permission"] = {"type": 10}
        normalize_preset(preset)
        preset["rows"][0][1]["permission"] = {"type": 11}
        with self.assertRaisesRegex(ButtonValidationError, "AstrBot 管理员"):
            normalize_preset(preset)

    def test_plugin_intercept_fields_are_kept_only_when_effective(self):
        preset = default_preset()
        hello = preset["rows"][1][0]
        hello["permission"] = {"type": 10}
        hello["intercept"] = True
        hello["deny_replies"] = ["不给点", " ", "{{at}} 走开", "不给点"]
        result = normalize_preset(preset)["rows"][1][0]
        self.assertIs(result["intercept"], True)
        self.assertEqual(result["deny_replies"], ["不给点", "{{at}} 走开"])

        # 没开插件拦截时拒绝语不生效，不保存；普通指令按钮插件拦不到，开关也丢弃。
        hello.pop("intercept")
        self.assertNotIn("deny_replies", normalize_preset(preset)["rows"][1][0])
        command = preset["rows"][0][0]
        command.update(permission={"type": 10}, intercept=True, deny_replies=["x"])
        result = normalize_preset(preset)["rows"][0][0]
        self.assertNotIn("intercept", result)
        self.assertNotIn("deny_replies", result)

    def test_bot_admin_deny_replies_default_empty_and_limits(self):
        preset = default_preset()
        hello = preset["rows"][1][0]
        hello["permission"] = {"type": 11}
        # 没配置过的按钮不写字段，沿用旧版默认提示。
        self.assertNotIn("deny_replies", normalize_preset(preset)["rows"][1][0])
        hello["deny_replies"] = []
        self.assertEqual(normalize_preset(preset)["rows"][1][0]["deny_replies"], [])
        hello["deny_replies"] = ["字" * 501]
        with self.assertRaisesRegex(ButtonValidationError, "拒绝语"):
            normalize_preset(preset)
        hello["deny_replies"] = [str(i) for i in range(21)]
        with self.assertRaisesRegex(ButtonValidationError, "拒绝语"):
            normalize_preset(preset)

    def test_unknown_permission_type_is_rejected(self):
        preset = default_preset()
        preset["rows"][0][0]["permission"] = {"type": 4}
        with self.assertRaisesRegex(ButtonValidationError, "权限类型"):
            normalize_preset(preset)

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
