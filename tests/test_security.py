import unittest

from core.security import create_action_token, parse_action_token


class SecurityTests(unittest.TestCase):
    def test_round_trip(self):
        token = create_action_token("secret", "menu", "button")
        self.assertEqual(parse_action_token("secret", token), ("menu", "button"))

    def test_tampered_token_is_rejected(self):
        token = create_action_token("secret", "menu", "button")
        self.assertIsNone(parse_action_token("secret", token + "x"))
        self.assertIsNone(parse_action_token("wrong", token))


if __name__ == "__main__":
    unittest.main()
