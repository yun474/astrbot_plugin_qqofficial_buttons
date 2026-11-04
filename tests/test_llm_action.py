import types
import unittest
from datetime import datetime, timedelta, timezone

from core.llm_action import (
    MAX_REPLY,
    clean_reply,
    datetime_reminder,
    generate_reply,
    render_prompt,
)
from core.models import ButtonValidationError, default_preset, normalize_preset


class FakeResponse:
    def __init__(self, text):
        self.completion_text = text


class FakeProvider:
    def __init__(self, reply="今天也要好好吃饭。", error=None):
        self.reply = reply
        self.error = error
        self.calls = []

    async def text_chat(self, **kwargs):
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        return FakeResponse(self.reply)


class FakeContext:
    def __init__(self, provider):
        self.provider = provider
        self.umos = []

    async def get_using_provider_async(self, umo=None):
        self.umos.append(umo)
        return self.provider


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

    def test_prompt_length_is_limited(self):
        normalize_preset(preset_with_llm_button("字" * 500))
        with self.assertRaisesRegex(ButtonValidationError, "500"):
            normalize_preset(preset_with_llm_button("字" * 501))

    def test_empty_prompt_is_rejected(self):
        with self.assertRaises(ButtonValidationError):
            normalize_preset(preset_with_llm_button("   "))


class CleanReplyTests(unittest.TestCase):
    def test_blank_reply_becomes_empty(self):
        for value in (None, "", "   \n "):
            self.assertEqual(clean_reply(value), "")

    def test_long_reply_is_truncated(self):
        reply = clean_reply("啊" * (MAX_REPLY + 50))
        self.assertEqual(len(reply), MAX_REPLY + 1)
        self.assertTrue(reply.endswith("…"))


class GenerateReplyTests(unittest.IsolatedAsyncioTestCase):
    async def test_uses_session_model_and_prompt(self):
        provider = FakeProvider("别熬夜，早点睡。")
        context = FakeContext(provider)
        reply = await generate_reply(context, " 说一句晚安 ", umo="qq_official:GroupMessage:g1")
        self.assertEqual(reply, "别熬夜，早点睡。")
        self.assertEqual(context.umos, ["qq_official:GroupMessage:g1"])
        self.assertEqual(provider.calls[0]["prompt"], "说一句晚安")
        self.assertTrue(provider.calls[0]["system_prompt"])

    async def test_missing_provider_raises(self):
        with self.assertRaisesRegex(RuntimeError, "对话模型"):
            await generate_reply(FakeContext(None), "说一句晚安")

    async def test_empty_prompt_raises(self):
        with self.assertRaisesRegex(RuntimeError, "提示词"):
            await generate_reply(FakeContext(FakeProvider()), "   ")

    async def test_blank_completion_returns_empty_string(self):
        self.assertEqual(
            await generate_reply(FakeContext(FakeProvider("   ")), "说句话"),
            "",
        )

    async def test_old_astrbot_falls_back_to_sync_provider_getter(self):
        provider = FakeProvider("旧版本也能说话。")
        umos = []

        def get_using_provider(umo=None):
            umos.append(umo)
            return provider

        context = types.SimpleNamespace(get_using_provider=get_using_provider)
        reply = await generate_reply(context, "说一句", umo="qq:GroupMessage:g1")
        self.assertEqual(reply, "旧版本也能说话。")
        self.assertEqual(umos, ["qq:GroupMessage:g1"])


class RenderPromptTests(unittest.TestCase):
    def test_user_placeholder_is_replaced_on_demand(self):
        self.assertEqual(
            render_prompt(" 夸夸 {user} ", user="openid-1"), "夸夸 openid-1"
        )
        self.assertEqual(render_prompt(" 来一句每日一言 "), "来一句每日一言")


class DatetimeReminderTests(unittest.IsolatedAsyncioTestCase):
    def config(self, enabled=True, tz="Asia/Shanghai"):
        return {
            "provider_settings": {"datetime_system_prompt": enabled},
            "timezone": tz,
        }

    def test_follows_astrbot_format(self):
        now = datetime(2026, 11, 5, 9, 5, tzinfo=timezone(timedelta(hours=8), "CST"))
        self.assertEqual(
            datetime_reminder(self.config(), now=now),
            "Current datetime: 2026-11-05 09:05 (CST), Weekday: Thursday",
        )

    def test_disabled_switch_or_missing_config_adds_nothing(self):
        self.assertEqual(datetime_reminder(self.config(enabled=False)), "")
        self.assertEqual(datetime_reminder(None), "")

    def test_uses_configured_timezone_and_survives_bad_value(self):
        self.assertIn("(CST)", datetime_reminder(self.config()))
        self.assertTrue(datetime_reminder(self.config(tz="Not/AZone")))

    async def test_reminder_is_appended_to_system_prompt(self):
        provider = FakeProvider()
        await generate_reply(FakeContext(provider), "说一句", config=self.config())
        self.assertIn("Current datetime:", provider.calls[0]["system_prompt"])
        provider = FakeProvider()
        await generate_reply(
            FakeContext(provider), "说一句", config=self.config(enabled=False)
        )
        self.assertNotIn("Current datetime:", provider.calls[0]["system_prompt"])


if __name__ == "__main__":
    unittest.main()
