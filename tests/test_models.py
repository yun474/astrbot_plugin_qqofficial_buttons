import unittest

from core.models import ButtonValidationError, default_preset, normalize_preset


class ModelTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
