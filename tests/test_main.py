import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import main  # noqa: E402


class FakeResponse:
    def __init__(self, payload=None, json_error=None):
        self.payload = payload
        self.json_error = json_error

    def raise_for_status(self):
        return None

    def json(self):
        if self.json_error:
            raise self.json_error
        return self.payload


class FakeTextResponse:
    def __init__(self, text):
        self.text = text
        self.encoding = None
        self.apparent_encoding = "utf-8"

    def raise_for_status(self):
        return None


class FakeHttpError(main.requests.HTTPError):
    def __init__(self, status_code):
        super().__init__(f"HTTP {status_code}")
        self.response = type("Response", (), {"status_code": status_code})()


class ConfigTests(unittest.TestCase):
    def load_config_with_env(self, env, **kwargs):
        if not kwargs:
            kwargs = {"require_delivery": True}
        with patch.object(main, "load_dotenv", lambda: None):
            with patch.dict(os.environ, env, clear=True):
                return main.load_config(**kwargs)

    def test_check_feeds_mode_only_requires_rss_feeds(self):
        config = self.load_config_with_env(
            {"RSS_FEEDS": "https://example.com/rss.xml"},
            require_delivery=False,
        )

        self.assertEqual(config["rss_feeds"], ["https://example.com/rss.xml"])
        self.assertEqual(config["deepseek_api_key"], "")
        self.assertEqual(config["feishu_webhook_url"], "")

    def test_dry_run_mode_requires_deepseek_but_not_feishu_webhook(self):
        config = self.load_config_with_env(
            {
                "DEEPSEEK_API_KEY": "sk-real",
                "RSS_FEEDS": "https://example.com/rss.xml",
            },
            require_deepseek=True,
            require_feishu=False,
        )

        self.assertEqual(config["deepseek_api_key"], "sk-real")
        self.assertEqual(config["feishu_webhook_url"], "")

    def test_delivery_mode_rejects_placeholder_secret(self):
        with self.assertRaisesRegex(ValueError, "DEEPSEEK_API_KEY"):
            self.load_config_with_env(
                {
                    "DEEPSEEK_API_KEY": "sk-xxxxxxxxxxxxxxxx",
                    "FEISHU_WEBHOOK_URL": "https://open.feishu.cn/open-apis/bot/v2/hook/real-token",
                    "RSS_FEEDS": "https://example.com/rss.xml",
                }
            )

    def test_delivery_mode_rejects_placeholder_feishu_bot_secret(self):
        with self.assertRaisesRegex(ValueError, "FEISHU_BOT_SECRET"):
            self.load_config_with_env(
                {
                    "DEEPSEEK_API_KEY": "sk-real",
                    "FEISHU_WEBHOOK_URL": "https://open.feishu.cn/open-apis/bot/v2/hook/real-token",
                    "FEISHU_BOT_SECRET": "xxxxxxxx",
                    "RSS_FEEDS": "https://example.com/rss.xml",
                }
            )

    def test_invalid_numeric_config_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "NEWS_HOURS"):
            self.load_config_with_env(
                {
                    "DEEPSEEK_API_KEY": "sk-real",
                    "FEISHU_WEBHOOK_URL": "https://open.feishu.cn/open-apis/bot/v2/hook/real-token",
                    "RSS_FEEDS": "https://example.com/rss.xml",
                    "NEWS_HOURS": "0",
                }
            )

    def test_candidate_count_must_cover_summary_items(self):
        with self.assertRaisesRegex(ValueError, "VALUE_SCORE_CANDIDATES"):
            self.load_config_with_env(
                {
                    "DEEPSEEK_API_KEY": "sk-real",
                    "FEISHU_WEBHOOK_URL": "https://open.feishu.cn/open-apis/bot/v2/hook/real-token",
                    "RSS_FEEDS": "https://example.com/rss.xml",
                    "VALUE_SCORE_CANDIDATES": "2",
                    "MAX_SUMMARY_ITEMS": "3",
                }
            )

    def test_rss_feeds_must_be_http_urls(self):
        with self.assertRaisesRegex(ValueError, "RSS_FEEDS"):
            self.load_config_with_env(
                {
                    "DEEPSEEK_API_KEY": "sk-real",
                    "FEISHU_WEBHOOK_URL": "https://open.feishu.cn/open-apis/bot/v2/hook/real-token",
                    "RSS_FEEDS": "file:///tmp/feed.xml",
                }
            )

    def test_deepseek_thinking_mode_must_be_supported(self):
        with self.assertRaisesRegex(ValueError, "DEEPSEEK_THINKING_MODE"):
            self.load_config_with_env(
                {
                    "DEEPSEEK_API_KEY": "sk-real",
                    "FEISHU_WEBHOOK_URL": "https://open.feishu.cn/open-apis/bot/v2/hook/real-token",
                    "RSS_FEEDS": "https://example.com/rss.xml",
                    "DEEPSEEK_THINKING_MODE": "maybe",
                }
            )

    def test_deepseek_model_must_not_be_empty(self):
        with self.assertRaisesRegex(ValueError, "DEEPSEEK_MODEL"):
            self.load_config_with_env(
                {
                    "DEEPSEEK_API_KEY": "sk-real",
                    "DEEPSEEK_MODEL": " ",
                    "FEISHU_WEBHOOK_URL": "https://open.feishu.cn/open-apis/bot/v2/hook/real-token",
                    "RSS_FEEDS": "https://example.com/rss.xml",
                }
            )

    def test_deepseek_only_check_ignores_unrelated_news_and_feishu_config(self):
        config = self.load_config_with_env(
            {
                "DEEPSEEK_API_KEY": "sk-real",
                "DEEPSEEK_BASE_URL": "https://api.example.com",
                "FEISHU_WEBHOOK_URL": "not-a-url",
                "NEWS_HOURS": "not-a-number",
                "RSS_FEEDS": "file:///tmp/feed.xml",
            },
            require_deepseek=True,
            require_feishu=False,
            require_rss=False,
            require_news_settings=False,
        )

        self.assertEqual(config["deepseek_api_key"], "sk-real")
        self.assertEqual(config["news_hours"], 24)
        self.assertEqual(config["rss_feeds"], ["file:///tmp/feed.xml"])

    def test_feishu_only_check_ignores_unrelated_deepseek_and_news_config(self):
        config = self.load_config_with_env(
            {
                "DEEPSEEK_BASE_URL": "not-a-url",
                "DEEPSEEK_THINKING_MODE": "maybe",
                "FEISHU_WEBHOOK_URL": "https://open.feishu.cn/open-apis/bot/v2/hook/real-token",
                "NEWS_HOURS": "not-a-number",
                "RSS_FEEDS": "file:///tmp/feed.xml",
            },
            require_deepseek=False,
            require_feishu=True,
            require_rss=False,
            require_news_settings=False,
        )

        self.assertEqual(config["feishu_webhook_url"], "https://open.feishu.cn/open-apis/bot/v2/hook/real-token")
        self.assertEqual(config["max_summary_items"], 20)

    def test_lark_webhook_url_is_accepted(self):
        config = self.load_config_with_env(
            {
                "DEEPSEEK_API_KEY": "sk-real",
                "FEISHU_WEBHOOK_URL": "https://open.larksuite.com/open-apis/bot/v2/hook/real-token",
                "RSS_FEEDS": "https://example.com/rss.xml",
            }
        )

        self.assertEqual(config["feishu_webhook_url"], "https://open.larksuite.com/open-apis/bot/v2/hook/real-token")

    def test_feishu_webhook_must_be_bot_webhook_url(self):
        with self.assertRaisesRegex(ValueError, "FEISHU_WEBHOOK_URL"):
            self.load_config_with_env(
                {
                    "DEEPSEEK_API_KEY": "sk-real",
                    "FEISHU_WEBHOOK_URL": "https://example.com/webhook",
                    "RSS_FEEDS": "https://example.com/rss.xml",
                }
            )


class ExternalResponseTests(unittest.TestCase):
    def test_feishu_status_code_failure_is_rejected(self):
        with patch.object(main.requests, "post", return_value=FakeResponse({"StatusCode": 99991663, "msg": "bad sign"})):
            with self.assertRaisesRegex(ValueError, "Feishu webhook failed"):
                main.send_to_feishu("https://example.com/webhook", {"msg_type": "text"})

    def test_feishu_status_code_success_is_accepted(self):
        with patch.object(main.requests, "post", return_value=FakeResponse({"StatusCode": 0, "StatusMessage": "success"})):
            main.send_to_feishu("https://example.com/webhook", {"msg_type": "text"})

    def test_feishu_code_success_is_accepted(self):
        with patch.object(main.requests, "post", return_value=FakeResponse({"code": 0, "msg": "success"})):
            main.send_to_feishu("https://example.com/webhook", {"msg_type": "text"})

    def test_feishu_missing_status_is_rejected(self):
        with patch.object(main.requests, "post", return_value=FakeResponse({"msg": "success"})):
            with self.assertRaisesRegex(ValueError, "missing status code"):
                main.send_to_feishu("https://example.com/webhook", {"msg_type": "text"})

    def test_feishu_non_json_response_is_rejected(self):
        with patch.object(main.requests, "post", return_value=FakeResponse(json_error=ValueError("not json"))):
            with self.assertRaisesRegex(ValueError, "non-JSON"):
                main.send_to_feishu("https://example.com/webhook", {"msg_type": "text"})

    def test_feishu_network_errors_are_wrapped(self):
        with patch.object(main.requests, "post", side_effect=main.requests.Timeout("slow")):
            with self.assertRaisesRegex(ValueError, "Feishu webhook request failed"):
                main.send_to_feishu("https://example.com/webhook", {"msg_type": "text"})

    def test_deepseek_non_json_response_is_rejected(self):
        with patch.object(main.requests, "post", return_value=FakeResponse(json_error=ValueError("not json"))):
            with self.assertRaisesRegex(ValueError, "non-JSON"):
                main.summarize_with_deepseek(
                    base_url="https://api.example.com",
                    api_key="sk-real",
                    model="model",
                    prompt="hello",
                )

    def test_deepseek_request_uses_json_response_format(self):
        captured_payload = {}

        def fake_post(*args, **kwargs):
            captured_payload.update(kwargs["json"])
            return FakeResponse({"choices": [{"message": {"content": "{}"}}]})

        with patch.object(main.requests, "post", side_effect=fake_post):
            self.assertEqual(
                main.summarize_with_deepseek(
                    base_url="https://api.example.com",
                    api_key="sk-real",
                    model="model",
                    prompt="hello",
                ),
                "{}",
            )

        self.assertEqual(captured_payload["response_format"], {"type": "json_object"})
        self.assertEqual(captured_payload["max_tokens"], main.DEEPSEEK_MAX_TOKENS)
        self.assertEqual(captured_payload["thinking"], {"type": "disabled"})

    def test_deepseek_request_allows_smaller_max_tokens(self):
        captured_payload = {}

        def fake_post(*args, **kwargs):
            captured_payload.update(kwargs["json"])
            return FakeResponse({"choices": [{"message": {"content": "{}"}}]})

        with patch.object(main.requests, "post", side_effect=fake_post):
            main.summarize_with_deepseek(
                base_url="https://api.example.com",
                api_key="sk-real",
                model="model",
                prompt="hello",
                max_tokens=64,
            )

        self.assertEqual(captured_payload["max_tokens"], 64)

    def test_check_deepseek_uses_small_json_probe(self):
        captured = {}

        def fake_summarize(**kwargs):
            captured.update(kwargs)
            return '{"ok": true}'

        with patch.object(main, "summarize_with_deepseek", side_effect=fake_summarize), patch("builtins.print"):
            main.check_deepseek(
                {
                    "deepseek_base_url": "https://api.example.com",
                    "deepseek_api_key": "sk-real",
                    "deepseek_model": "model",
                    "deepseek_thinking_mode": "disabled",
                }
            )

        self.assertEqual(captured["max_tokens"], 64)
        self.assertEqual(captured["temperature"], 0)
        self.assertEqual(captured["thinking_mode"], "disabled")

    def test_check_deepseek_wraps_network_errors(self):
        with patch.object(
            main,
            "summarize_with_deepseek",
            side_effect=main.requests.ConnectionError("network down"),
        ):
            with self.assertRaisesRegex(ValueError, "DeepSeek request failed"):
                main.check_deepseek(
                    {
                        "deepseek_base_url": "https://api.example.com",
                        "deepseek_api_key": "sk-real",
                        "deepseek_model": "model",
                        "deepseek_thinking_mode": "disabled",
                    }
                )

    def test_check_deepseek_rejects_non_json_probe_response(self):
        with patch.object(main, "summarize_with_deepseek", return_value="not json"):
            with self.assertRaisesRegex(ValueError, "valid JSON"):
                main.check_deepseek(
                    {
                        "deepseek_base_url": "https://api.example.com",
                        "deepseek_api_key": "sk-real",
                        "deepseek_model": "model",
                        "deepseek_thinking_mode": "disabled",
                    }
                )

    def test_check_deepseek_rejects_unexpected_probe_payload(self):
        with patch.object(main, "summarize_with_deepseek", return_value='{"ok": false}'):
            with self.assertRaisesRegex(ValueError, "unexpected JSON"):
                main.check_deepseek(
                    {
                        "deepseek_base_url": "https://api.example.com",
                        "deepseek_api_key": "sk-real",
                        "deepseek_model": "model",
                        "deepseek_thinking_mode": "disabled",
                    }
                )

    def test_auth_http_status_is_detected(self):
        self.assertTrue(main.is_http_status_error(FakeHttpError(401), main.AUTH_ERROR_STATUS_CODES))
        self.assertTrue(main.is_http_status_error(FakeHttpError(403), main.AUTH_ERROR_STATUS_CODES))
        self.assertFalse(main.is_http_status_error(FakeHttpError(500), main.AUTH_ERROR_STATUS_CODES))

    def test_rss_fetch_falls_back_to_direct_when_proxy_fails(self):
        calls = []

        def fake_get(*args, **kwargs):
            calls.append(kwargs.get("proxies"))
            if len(calls) <= main.RSS_RETRIES:
                raise main.requests.exceptions.ProxyError("proxy down")
            return FakeTextResponse("<rss />")

        with patch.dict(os.environ, {"RSS_PROXY": "http://127.0.0.1:7890"}, clear=True):
            with patch.object(main.requests, "get", side_effect=fake_get):
                self.assertEqual(main.fetch_url_text("https://example.com/rss.xml"), "<rss />")

        self.assertEqual(
            calls[: main.RSS_RETRIES],
            [{"http": "http://127.0.0.1:7890", "https": "http://127.0.0.1:7890"}] * main.RSS_RETRIES,
        )
        self.assertIsNone(calls[main.RSS_RETRIES])


class DigestParsingTests(unittest.TestCase):
    def article(self, link="https://example.com/real", source="Trusted Source", value_score=4.2):
        return main.Article(
            title="Original title",
            link=link,
            source=source,
            published_at=None,
            summary="Original summary",
            feed_url="https://example.com/rss.xml",
            value_score=value_score,
        )

    def test_parse_feed_articles_skips_non_http_links(self):
        feed_text = """
        <rss>
          <channel>
            <title>Example Feed</title>
            <item><title>Bad link</title><link>javascript:alert(1)</link></item>
            <item><title>Good link</title><link>https://example.com/good</link></item>
          </channel>
        </rss>
        """

        articles = main.parse_feed_articles(
            "https://example.com/rss.xml",
            feed_text,
            main.datetime(2000, 1, 1, tzinfo=main.UTC8),
        )

        self.assertEqual([article.link for article in articles], ["https://example.com/good"])

    def test_digest_parser_rejects_links_not_in_source_articles(self):
        text = """
        {
          "overview": "overview",
          "items": [
            {
              "title": "Injected title",
              "summary": "Injected summary",
              "why": "Injected why",
              "value_score": "5/5",
              "source": "Injected source",
              "link": "https://evil.example/phishing"
            }
          ]
        }
        """

        digest = main.parse_digest_response(text, [self.article()], max_items=1)

        self.assertEqual(digest["items"][0]["title"], "Original title")
        self.assertEqual(digest["items"][0]["link"], "https://example.com/real")

    def test_digest_parser_uses_original_source_metadata_for_accepted_links(self):
        text = """
        {
          "overview": "overview",
          "items": [
            {
              "title": "Rewritten title",
              "summary": "Rewritten summary",
              "why": "Watch this",
              "value_score": "1/5",
              "source": "Spoofed source",
              "link": "https://example.com/real"
            }
          ]
        }
        """

        digest = main.parse_digest_response(text, [self.article()], max_items=1)

        self.assertEqual(digest["items"][0]["title"], "Rewritten title")
        self.assertEqual(digest["items"][0]["source"], "Trusted Source")
        self.assertEqual(digest["items"][0]["value_score"], "4.2/5")


class MainFlowTests(unittest.TestCase):
    def test_check_config_validates_delivery_config_without_network_or_send(self):
        config = {
            "deepseek_api_key": "sk-real",
            "deepseek_base_url": "https://api.example.com",
            "deepseek_model": "model",
            "deepseek_thinking_mode": "disabled",
            "feishu_webhook_url": "https://open.feishu.cn/open-apis/bot/v2/hook/real-token",
            "feishu_bot_secret": "",
            "news_hours": 24,
            "max_articles": 80,
            "max_summary_items": 20,
            "value_score_candidates": 60,
            "rss_feeds": ["https://example.com/rss.xml"],
        }

        with patch.object(sys, "argv", ["main.py", "--check-config", "--check-feeds"]):
            with patch.object(main, "load_config", return_value=config) as load_config:
                with patch.object(main, "fetch_articles") as fetch_articles:
                    with patch.object(main, "send_to_feishu") as send_to_feishu:
                        with patch("builtins.print") as mocked_print:
                            main.main()

        load_config.assert_called_once_with(
            require_deepseek=True,
            require_feishu=True,
            require_rss=True,
            require_news_settings=True,
        )
        fetch_articles.assert_not_called()
        send_to_feishu.assert_not_called()
        mocked_print.assert_any_call("Config check passed (1 RSS sources, model model, thinking disabled, 20 summary items).")

    def test_check_deepseek_does_not_require_rss_or_feishu(self):
        config = {
            "deepseek_api_key": "sk-real",
            "deepseek_base_url": "https://api.example.com",
            "deepseek_model": "model",
            "deepseek_thinking_mode": "disabled",
            "feishu_webhook_url": "",
            "feishu_bot_secret": "",
            "news_hours": 24,
            "max_articles": 80,
            "max_summary_items": 20,
            "value_score_candidates": 60,
            "rss_feeds": [],
        }

        with patch.object(sys, "argv", ["main.py", "--check-deepseek"]):
            with patch.object(main, "load_config", return_value=config) as load_config:
                with patch.object(main, "check_deepseek") as check_deepseek:
                    main.main()

        load_config.assert_called_once_with(
            require_deepseek=True,
            require_feishu=False,
            require_rss=False,
            require_news_settings=False,
        )
        check_deepseek.assert_called_once_with(config)

    def test_check_feishu_sends_probe_without_rss_or_deepseek(self):
        config = {
            "deepseek_api_key": "",
            "deepseek_base_url": "https://api.example.com",
            "deepseek_model": "model",
            "deepseek_thinking_mode": "disabled",
            "feishu_webhook_url": "https://open.feishu.cn/open-apis/bot/v2/hook/real-token",
            "feishu_bot_secret": "",
            "news_hours": 24,
            "max_articles": 80,
            "max_summary_items": 20,
            "value_score_candidates": 60,
            "rss_feeds": [],
        }

        with patch.object(sys, "argv", ["main.py", "--check-feishu"]):
            with patch.object(main, "load_config", return_value=config) as load_config:
                with patch.object(main, "check_feishu") as check_feishu:
                    main.main()

        load_config.assert_called_once_with(
            require_deepseek=False,
            require_feishu=True,
            require_rss=False,
            require_news_settings=False,
        )
        check_feishu.assert_called_once_with(config)

    def test_check_feeds_fails_when_no_articles_are_found(self):
        config = {
            "deepseek_api_key": "",
            "deepseek_base_url": "https://api.example.com",
            "deepseek_model": "model",
            "deepseek_thinking_mode": "disabled",
            "feishu_webhook_url": "",
            "feishu_bot_secret": "",
            "news_hours": 24,
            "max_articles": 80,
            "max_summary_items": 20,
            "value_score_candidates": 60,
            "rss_feeds": ["https://example.com/rss.xml"],
        }

        with patch.object(sys, "argv", ["main.py", "--check-feeds"]):
            with patch.object(main, "load_config", return_value=config):
                with patch.object(main, "fetch_articles", return_value=[]):
                    with patch("builtins.print"):
                        with self.assertRaisesRegex(ValueError, "0 articles"):
                            main.main()

    def test_check_feeds_fails_when_too_few_articles_are_found(self):
        config = {
            "deepseek_api_key": "",
            "deepseek_base_url": "https://api.example.com",
            "deepseek_model": "model",
            "deepseek_thinking_mode": "disabled",
            "feishu_webhook_url": "",
            "feishu_bot_secret": "",
            "news_hours": 24,
            "max_articles": 80,
            "max_summary_items": 20,
            "value_score_candidates": 60,
            "rss_feeds": ["https://example.com/rss.xml"],
        }
        articles = [
            main.Article(
                title=f"Article {index}",
                link=f"https://example.com/{index}",
                source="Example",
                published_at=None,
                summary="Summary",
                feed_url="https://example.com/rss.xml",
            )
            for index in range(9)
        ]

        with patch.object(sys, "argv", ["main.py", "--check-feeds"]):
            with patch.object(main, "load_config", return_value=config):
                with patch.object(main, "fetch_articles", return_value=articles):
                    with patch("builtins.print"):
                        with self.assertRaisesRegex(ValueError, "expected at least 10"):
                            main.main()

    def test_check_feeds_threshold_respects_small_max_articles(self):
        self.assertEqual(main.minimum_feed_check_articles(5), 5)
        self.assertEqual(main.minimum_feed_check_articles(80), 10)

    def test_dry_run_with_no_articles_skips_feishu_send(self):
        config = {
            "deepseek_api_key": "sk-real",
            "deepseek_base_url": "https://api.example.com",
            "deepseek_model": "model",
            "deepseek_thinking_mode": "disabled",
            "feishu_webhook_url": "",
            "feishu_bot_secret": "",
            "news_hours": 24,
            "max_articles": 80,
            "max_summary_items": 20,
            "value_score_candidates": 60,
            "rss_feeds": ["https://example.com/rss.xml"],
        }

        with patch.object(sys, "argv", ["main.py", "--dry-run"]):
            with patch.object(main, "load_config", return_value=config):
                with patch.object(main, "fetch_articles", return_value=[]):
                    with patch.object(main, "send_to_feishu") as send_to_feishu:
                        with patch("builtins.print") as mocked_print:
                            main.main()

        send_to_feishu.assert_not_called()
        mocked_print.assert_any_call("Dry run built empty-state card from 0 source articles. Feishu send skipped.")


if __name__ == "__main__":
    unittest.main()
