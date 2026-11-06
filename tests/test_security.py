import unittest

from core.security import (
    action_token_user,
    button_token_matches,
    create_action_token,
    parse_action_token,
)


class SecurityTests(unittest.TestCase):
    def test_round_trip(self):
        token = create_action_token("secret", "menu", "button")
        self.assertEqual(parse_action_token("secret", token), ("menu", "button"))

    def test_tampered_token_is_rejected(self):
        token = create_action_token("secret", "menu", "button")
        self.assertIsNone(parse_action_token("secret", token + "x"))
        self.assertIsNone(parse_action_token("wrong", token))
        self.assertIsNone(parse_action_token("secret", "?.bad"))

    def test_trigger_user_is_bound_into_signature(self):
        button = {
            "id": "button",
            "action": {"type": "callback_text", "value": "hi"},
            "permission": {"type": 10, "user_ids": [], "role_ids": []},
        }
        token = create_action_token("secret", "menu", "button", button, user="owner")
        self.assertEqual(parse_action_token("secret", token), ("menu", "button"))
        self.assertEqual(action_token_user("secret", token), "owner")
        self.assertTrue(button_token_matches("secret", token, "menu", button))
        plain = create_action_token("secret", "menu", "button", button)
        self.assertEqual(action_token_user("secret", plain), "")
        self.assertNotEqual(plain, token)


if __name__ == "__main__":
    unittest.main()
