import argparse
import base64
import hashlib
import hmac
import json
import os
import re
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from html import unescape
from typing import Iterable
from urllib.parse import urlparse

import feedparser
import requests
from dotenv import load_dotenv


UTC8 = timezone(timedelta(hours=8))
DEEPSEEK_CHAT_COMPLETIONS_PATH = "/chat/completions"
REQUEST_TIMEOUT_SECONDS = 30
DEEPSEEK_TIMEOUT_SECONDS = 60
DEEPSEEK_MAX_TOKENS = 12000
RSS_TIMEOUT_SECONDS = 12
RSS_RETRIES = 2
RSS_FETCH_WORKERS = 8
AUTH_ERROR_STATUS_CODES = {401, 403}
FEISHU_WEBHOOK_HOSTS = {"open.feishu.cn", "open.larksuite.com"}
REQUEST_HEADERS = {
    "User-Agent": "daily-news-feishu/1.0",
}
CARD_TITLE = "\u4eca\u5929\u8fd9\u51e0\u4ef6\u4e8b"
CARD_OVERVIEW = "\u5148\u8bf4\u4eba\u8bdd"
CARD_REASON = "\u522b\u88ab\u5e26\u8dd1"
CARD_SOURCE = "\u6765\u6e90"
CARD_OPEN = "\u67e5\u770b\u539f\u6587"
CARD_VALUE = "\u4ef7\u503c\u5206"
CARD_FOOTER = "\u6570\u636e\u6765\u6e90\uff1aRSS \u805a\u5408 + DeepSeek \u4ef7\u503c\u8bc4\u5206\u4e0e\u89e3\u8bfb"
EMPTY_MESSAGE = "\u6700\u8fd1 24 \u5c0f\u65f6\u5185\u6ca1\u6709\u6293\u5230\u53ef\u7528\u65b0\u95fb\uff0c\u8bf7\u68c0\u67e5 RSS \u914d\u7f6e\u6216\u7f51\u7edc\u8fde\u63a5\u3002"
DOMESTIC_HINTS = (
    "people.com.cn",
    "chinadaily.com.cn",
)
LOW_VALUE_PATTERNS = (
    "live updates",
    "here's the latest",
    "what to know",
    "photos",
    "video",
    "\u76f4\u64ad",
    "\u6eda\u52a8",
    "\u56fe\u96c6",
    "\u89c6\u9891",
    "\u4e00\u56fe\u8bfb\u61c2",
    "\u5b66\u4e60\u5361",
    "\u5f3a\u8c03",
    "\u6307\u51fa",
    "\u63a8\u8fdb",
    "\u8d4b\u80fd",
    "\u8c03\u7814",
    "\u4f1a\u89c1",
)
HIGH_VALUE_PATTERNS = (
    "policy",
    "court",
    "lawsuit",
    "tariff",
    "sanction",
    "election",
    "war",
    "attack",
    "ceasefire",
    "inflation",
    "rates",
    "exports",
    "imports",
    "ai",
    "chip",
    "semiconductor",
    "\u653f\u7b56",
    "\u6cd5\u9662",
    "\u5224\u51b3",
    "\u5236\u88c1",
    "\u5173\u7a0e",
    "\u9009\u4e3e",
    "\u8d22\u62a5",
    "\u76d1\u7ba1",
    "\u7f5a\u6b3e",
    "\u4e8b\u6545",
    "\u88ad\u51fb",
    "\u505c\u706b",
    "\u901a\u80c0",
    "\u82af\u7247",
)


@dataclass
class Article:
    title: str
    link: str
    source: str
    published_at: datetime | None
    summary: str
    feed_url: str
    value_score: float = 0.0
    value_reason: str = ""
    spin_risk: str = ""


def uses_placeholder(value: str) -> bool:
    lowered = value.lower()
    return (
        not value
        or "xxxxxxxx" in lowered
        or "your_" in lowered
        or value == "sk-xxxxxxxxxxxxxxxx"
        or value.startswith("https://open.feishu.cn/open-apis/bot/v2/hook/xxxxxxxx")
    )


def parse_positive_int_env(name: str, default: int) -> int:
    raw_value = os.getenv(name, str(default)).strip()
    try:
        value = int(raw_value)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer.") from exc
    if value <= 0:
        raise ValueError(f"{name} must be greater than 0.")
    return value


def is_http_url(value: str) -> bool:
    parsed = urlparse(value)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def is_feishu_webhook_url(value: str) -> bool:
    parsed = urlparse(value)
    return (
        parsed.scheme == "https"
        and parsed.netloc.lower() in FEISHU_WEBHOOK_HOSTS
        and parsed.path.startswith("/open-apis/bot/v2/hook/")
        and len(parsed.path.rsplit("/", 1)[-1]) > 0
    )


def load_config(
    require_delivery: bool = True,
    require_deepseek: bool | None = None,
    require_feishu: bool | None = None,
    require_rss: bool = True,
    require_news_settings: bool = True,
) -> dict:
    if require_deepseek is None:
        require_deepseek = require_delivery
    if require_feishu is None:
        require_feishu = require_delivery

    load_dotenv()

    config = {
        "deepseek_api_key": os.getenv("DEEPSEEK_API_KEY", "").strip(),
        "deepseek_base_url": os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com").strip().rstrip("/"),
        "deepseek_model": os.getenv("DEEPSEEK_MODEL", "deepseek-v4-flash").strip(),
        "deepseek_thinking_mode": os.getenv("DEEPSEEK_THINKING_MODE", "disabled").strip().lower(),
        "feishu_webhook_url": os.getenv("FEISHU_WEBHOOK_URL", "").strip(),
        "feishu_bot_secret": os.getenv("FEISHU_BOT_SECRET", "").strip(),
        "news_hours": parse_positive_int_env("NEWS_HOURS", 24) if require_news_settings else 24,
        "max_articles": parse_positive_int_env("MAX_ARTICLES", 80) if require_news_settings else 80,
        "max_summary_items": parse_positive_int_env("MAX_SUMMARY_ITEMS", 20) if require_news_settings else 20,
        "value_score_candidates": parse_positive_int_env("VALUE_SCORE_CANDIDATES", 60) if require_news_settings else 60,
        "rss_feeds": [
            item.strip()
            for item in os.getenv("RSS_FEEDS", "").split(",")
            if item.strip()
        ],
    }

    if require_rss:
        if not config["rss_feeds"]:
            raise ValueError("Missing required config: RSS_FEEDS")
        invalid_feeds = [feed for feed in config["rss_feeds"] if not is_http_url(feed)]
        if invalid_feeds:
            raise ValueError(f"RSS_FEEDS contains invalid URL(s): {', '.join(invalid_feeds[:3])}")
    if require_deepseek:
        if not is_http_url(config["deepseek_base_url"]):
            raise ValueError("DEEPSEEK_BASE_URL must be an http(s) URL.")
        if not config["deepseek_model"]:
            raise ValueError("DEEPSEEK_MODEL must not be empty.")
        if config["deepseek_thinking_mode"] not in {"enabled", "disabled"}:
            raise ValueError("DEEPSEEK_THINKING_MODE must be either enabled or disabled.")
    if require_news_settings and config["value_score_candidates"] < config["max_summary_items"]:
        raise ValueError("VALUE_SCORE_CANDIDATES must be greater than or equal to MAX_SUMMARY_ITEMS.")

    required = []
    if require_deepseek:
        required.append("deepseek_api_key")
    if require_feishu:
        required.append("feishu_webhook_url")
    if required:
        missing = [key for key in required if not config[key]]
        if missing:
            raise ValueError(f"Missing required config: {', '.join(missing)}")
    if require_deepseek:
        if uses_placeholder(config["deepseek_api_key"]):
            raise ValueError("DEEPSEEK_API_KEY still looks like a placeholder.")
    if require_feishu:
        if uses_placeholder(config["feishu_webhook_url"]):
            raise ValueError("FEISHU_WEBHOOK_URL still looks like a placeholder.")
        if not is_feishu_webhook_url(config["feishu_webhook_url"]):
            raise ValueError("FEISHU_WEBHOOK_URL must be a Feishu/Lark bot webhook URL.")
        if config["feishu_bot_secret"] and uses_placeholder(config["feishu_bot_secret"]):
            raise ValueError("FEISHU_BOT_SECRET still looks like a placeholder.")

    return config


def parse_datetime(entry) -> datetime | None:
    candidates = [
        getattr(entry, "published", None),
        getattr(entry, "updated", None),
        entry.get("published"),
        entry.get("updated"),
    ]
    for value in candidates:
        if not value:
            continue
        try:
            dt = parsedate_to_datetime(value)
            return dt.astimezone(UTC8) if dt.tzinfo else dt.replace(tzinfo=UTC8)
        except (TypeError, ValueError, IndexError):
            continue
    return None


def clean_text(value: str) -> str:
    value = unescape(value or "")
    value = re.sub(r"<[^>]+>", " ", value)
    value = re.sub(r"\s+", " ", value).strip()
    return value


def strip_code_fences(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z0-9_+-]*\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    return text.strip()


def is_http_status_error(exc: requests.RequestException, status_codes: set[int]) -> bool:
    response = getattr(exc, "response", None)
    status_code = getattr(response, "status_code", None)
    return status_code in status_codes


def build_rss_proxies() -> dict[str, str] | None:
    proxy = os.getenv("RSS_PROXY", "").strip()
    if not proxy:
        return None
    return {
        "http": proxy,
        "https": proxy,
    }


def build_rss_proxy_options() -> list[dict[str, str] | None]:
    proxies = build_rss_proxies()
    return [proxies, None] if proxies else [None]


def fetch_url_text(url: str) -> str:
    last_error: Exception | None = None
    for proxies in build_rss_proxy_options():
        for attempt in range(RSS_RETRIES):
            try:
                response = requests.get(
                    url,
                    headers=REQUEST_HEADERS,
                    proxies=proxies,
                    timeout=RSS_TIMEOUT_SECONDS,
                )
                response.raise_for_status()
                response.encoding = response.encoding or response.apparent_encoding or "utf-8"
                return response.text
            except Exception as exc:
                last_error = exc
                if attempt == RSS_RETRIES - 1:
                    break
    assert last_error is not None
    raise last_error


def expand_feed_sources(feed_sources: Iterable[str]) -> list[str]:
    expanded: list[str] = []
    seen: set[str] = set()

    for source in feed_sources:
        if source.lower().endswith(".opml") or "opml" in source.lower():
            try:
                opml_text = fetch_url_text(source)
                root = ET.fromstring(opml_text)
            except Exception as exc:
                print(f"Warning: failed to load OPML source {source}: {exc}")
                continue

            for outline in root.findall(".//outline"):
                xml_url = (outline.attrib.get("xmlUrl") or "").strip()
                if xml_url and xml_url not in seen:
                    seen.add(xml_url)
                    expanded.append(xml_url)
            continue

        if source not in seen:
            seen.add(source)
            expanded.append(source)

    return expanded


def source_priority(article: Article) -> int:
    combined = f"{article.feed_url} {article.link} {article.source}".lower()
    return 1 if any(hint in combined for hint in DOMESTIC_HINTS) else 0


def article_text(article: Article) -> str:
    return f"{article.title} {article.summary} {article.source}".lower()


def rule_value_score(article: Article) -> float:
    text = article_text(article)
    score = 3.0
    score += sum(0.35 for pattern in HIGH_VALUE_PATTERNS if pattern.lower() in text)
    score -= sum(0.45 for pattern in LOW_VALUE_PATTERNS if pattern.lower() in text)
    if article.summary:
        score += 0.25
    if article.published_at:
        score += 0.15
    return max(1.0, min(5.0, score))


def filter_rule_noise(articles: list[Article], max_candidates: int) -> list[Article]:
    scored = [(rule_value_score(article), article) for article in articles]
    scored.sort(
        key=lambda item: (
            item[0],
            article_sort_time(item[1]),
        ),
        reverse=True,
    )
    ordered_articles = [article for _, article in scored]
    domestic_articles = [article for article in ordered_articles if source_priority(article)]
    global_articles = [article for article in ordered_articles if not source_priority(article)]
    if domestic_articles and global_articles:
        target_global = min(len(global_articles), max_candidates // 2)
        target_domestic = min(len(domestic_articles), max_candidates - target_global)
        candidates = domestic_articles[:target_domestic] + global_articles[:target_global]
        selected_ids = {id(article) for article in candidates}
        candidates.extend(article for article in ordered_articles if id(article) not in selected_ids)
        candidates = candidates[:max_candidates]
    else:
        candidates = ordered_articles[:max_candidates]
    for article in candidates:
        if article.value_score <= 0:
            article.value_score = rule_value_score(article)
            article.value_reason = "\u89c4\u5219\u7c97\u8bc4\u4fdd\u7559\uff1a\u8fd9\u6761\u6709\u4e00\u5b9a\u4fe1\u606f\u91cf\uff0c\u4f46\u4ecd\u8981\u770b\u540e\u7eed\u7ec6\u8282\u3002"
            article.spin_risk = "medium"
    return candidates


def article_sort_time(article: Article) -> datetime:
    return article.published_at or datetime.min.replace(tzinfo=UTC8)


def select_balanced_articles(articles: list[Article], max_articles: int) -> list[Article]:
    sorted_articles = sorted(articles, key=article_sort_time, reverse=True)
    domestic_articles = [article for article in sorted_articles if source_priority(article)]
    global_articles = [article for article in sorted_articles if not source_priority(article)]

    if not domestic_articles or not global_articles:
        return sorted_articles[:max_articles]

    target_global = min(len(global_articles), max_articles // 2)
    target_domestic = min(len(domestic_articles), max_articles - target_global)
    selected = domestic_articles[:target_domestic] + global_articles[:target_global]

    selected_ids = {id(article) for article in selected}
    selected.extend(article for article in sorted_articles if id(article) not in selected_ids)
    return sorted(selected[:max_articles], key=article_sort_time, reverse=True)


def select_diverse_scored_articles(articles: list[Article], max_items: int) -> list[Article]:
    sorted_articles = sorted(
        articles,
        key=lambda article: (
            article.value_score,
            rule_value_score(article),
            article_sort_time(article),
        ),
        reverse=True,
    )
    selected: list[Article] = []
    source_counts: dict[str, int] = {}
    domestic_count = 0
    global_count = 0
    target_each_side = max_items // 3

    for article in sorted_articles:
        if len(selected) >= max_items:
            break
        source_key = article.source.lower()
        if source_counts.get(source_key, 0) >= 5:
            continue
        is_domestic = bool(source_priority(article))
        if is_domestic and domestic_count >= max_items - target_each_side and global_count < target_each_side:
            continue
        if not is_domestic and global_count >= max_items - target_each_side and domestic_count < target_each_side:
            continue
        selected.append(article)
        source_counts[source_key] = source_counts.get(source_key, 0) + 1
        if is_domestic:
            domestic_count += 1
        else:
            global_count += 1

    selected_ids = {id(article) for article in selected}
    for article in sorted_articles:
        if len(selected) >= max_items:
            break
        if id(article) not in selected_ids:
            selected.append(article)
            selected_ids.add(id(article))

    return selected


def parse_feed_articles(feed_url: str, feed_text: str, cutoff: datetime) -> list[Article]:
    parsed = feedparser.parse(feed_text)
    feed_title = clean_text(parsed.feed.get("title", feed_url))
    articles: list[Article] = []
    for entry in parsed.entries:
        published_at = parse_datetime(entry)
        if published_at and published_at < cutoff:
            continue

        title = clean_text(entry.get("title", ""))
        link = entry.get("link", "").strip()
        summary = clean_text(entry.get("summary", "") or entry.get("description", ""))

        if not title or not is_http_url(link):
            continue

        articles.append(
            Article(
                title=title,
                link=link,
                source=feed_title,
                published_at=published_at,
                summary=summary[:500],
                feed_url=feed_url,
            )
        )
    return articles


def fetch_articles(feed_sources: Iterable[str], since_hours: int, max_articles: int) -> list[Article]:
    cutoff = datetime.now(UTC8) - timedelta(hours=since_hours)
    articles: list[Article] = []
    feed_urls = expand_feed_sources(feed_sources)

    if not feed_urls:
        return []

    max_workers = min(len(feed_urls), RSS_FETCH_WORKERS)
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_url = {executor.submit(fetch_url_text, feed_url): feed_url for feed_url in feed_urls}
        for future in as_completed(future_to_url):
            feed_url = future_to_url[future]
            try:
                articles.extend(parse_feed_articles(feed_url, future.result(), cutoff))
            except Exception as exc:
                print(f"Warning: failed to load feed {feed_url}: {exc}")

    deduped = deduplicate_articles(articles)
    return select_balanced_articles(deduped, max_articles)


def deduplicate_articles(articles: Iterable[Article]) -> list[Article]:
    seen: set[str] = set()
    result: list[Article] = []
    for article in articles:
        normalized_title = re.sub(r"\W+", "", article.title.lower())
        if normalized_title in seen:
            continue
        seen.add(normalized_title)
        result.append(article)
    return result


def build_value_score_prompt(articles: list[Article]) -> str:
    serialized_articles = []
    for index, article in enumerate(articles, start=1):
        published = article.published_at.strftime("%Y-%m-%d %H:%M %z") if article.published_at else "unknown"
        domestic = "yes" if source_priority(article) else "no"
        serialized_articles.append(
            f"[{index}]\n"
            f"Title: {article.title}\n"
            f"Source: {article.source}\n"
            f"Published: {published}\n"
            f"DomesticPriority: {domestic}\n"
            f"RuleScore: {rule_value_score(article):.2f}\n"
            f"Summary: {article.summary or 'N/A'}"
        )

    return (
        "You are ranking news for one busy reader who wants signal, not noise.\n"
        "Score each article by real information value, not official importance or clickbait heat.\n"
        "Use this rubric:\n"
        "- 5: major new development with broad policy, market, technology, geopolitical, or daily-life impact.\n"
        "- 4: clearly useful update that changes how a reader understands an issue.\n"
        "- 3: worth skimming, but impact or novelty is limited.\n"
        "- 2: mostly routine, repetitive, vague, or source-framed.\n"
        "- 1: low-value filler, liveblog noise, photo/video roundup, slogan, or pure ceremony.\n"
        "Penalize empty official wording, repeated meetings, leadership activity without concrete change, and live updates with no durable fact.\n"
        "Reward concrete actions, numbers, decisions, consequences, first reports, and facts that help future judgment.\n"
        "Return valid JSON only with this schema:\n"
        "{\n"
        '  "scores": [\n'
        "    {\n"
        '      "index": 1,\n'
        '      "value_score": 1.0,\n'
        '      "value_reason": "one short Chinese sentence explaining why it is or is not worth attention",\n'
        '      "spin_risk": "low|medium|high"\n'
        "    }\n"
        "  ]\n"
        "}\n\n"
        "Input articles:\n"
        + "\n\n".join(serialized_articles)
    )


def apply_value_scores(articles: list[Article], text: str) -> list[Article]:
    cleaned = strip_code_fences(text)
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", cleaned, re.S)
        if not match:
            raise ValueError("DeepSeek value scoring did not return JSON.")
        data = json.loads(match.group(0))

    by_index = {index: article for index, article in enumerate(articles, start=1)}
    for item in data.get("scores", []):
        try:
            index = int(item.get("index"))
        except (TypeError, ValueError):
            continue
        article = by_index.get(index)
        if not article:
            continue
        try:
            score = float(item.get("value_score", 0))
        except (TypeError, ValueError):
            score = 0
        article.value_score = max(1.0, min(5.0, score))
        article.value_reason = clean_text(str(item.get("value_reason", "")))
        article.spin_risk = clean_text(str(item.get("spin_risk", ""))).lower()

    for article in articles:
        if article.value_score <= 0:
            article.value_score = rule_value_score(article)
            article.value_reason = "\u89c4\u5219\u7c97\u8bc4\u4fdd\u7559\uff1a\u8fd9\u6761\u8fd8\u6709\u4e00\u5b9a\u4fe1\u606f\u91cf\uff0c\u4f46\u9700\u8981\u4eba\u5de5\u5224\u65ad\u540e\u7eed\u4ef7\u503c\u3002"
            article.spin_risk = "medium"

    return articles


def rank_articles_by_value(
    articles: list[Article],
    base_url: str,
    api_key: str,
    model: str,
    thinking_mode: str,
    max_candidates: int,
    max_items: int,
) -> list[Article]:
    candidates = filter_rule_noise(articles, max_candidates)
    prompt = build_value_score_prompt(candidates)
    raw_scores = summarize_with_deepseek(
        base_url=base_url,
        api_key=api_key,
        model=model,
        prompt=prompt,
        system_prompt="You are a strict news value judge. Always answer with valid JSON only.",
        temperature=0.15,
        thinking_mode=thinking_mode,
    )
    scored = apply_value_scores(candidates, raw_scores)
    return select_diverse_scored_articles(scored, max_items)


def build_digest_prompt(articles: list[Article], max_summary_items: int) -> str:
    serialized_articles = []
    for index, article in enumerate(articles, start=1):
        published = article.published_at.strftime("%Y-%m-%d %H:%M %z") if article.published_at else "unknown"
        domestic = "yes" if source_priority(article) else "no"
        serialized_articles.append(
            f"[{index}]\n"
            f"Title: {article.title}\n"
            f"Source: {article.source}\n"
            f"Published: {published}\n"
            f"Link: {article.link}\n"
            f"DomesticPriority: {domestic}\n"
            f"ValueScore: {article.value_score:.1f}\n"
            f"ValueReason: {article.value_reason or 'N/A'}\n"
            f"SpinRisk: {article.spin_risk or 'N/A'}\n"
            f"Summary: {article.summary or 'N/A'}"
        )

    return (
        "You are a sharp, plainspoken news explainer helping one individual reader understand the day.\n"
        "Create a daily digest in Simplified Chinese that feels like a smart friend explaining the news, not an official bulletin.\n"
        f"Return {max_summary_items} items when at least {max_summary_items} usable articles are available; otherwise return all usable articles.\n"
        "Selection rules:\n"
        "1. The input has already been ranked by news value. Preserve that order unless an item is unusable.\n"
        "2. Include a balanced mix of China domestic news and international news when both are available.\n"
        "3. Avoid duplicates covering the same event.\n"
        "4. Prefer concrete facts over slogans, claims, and vague institutional wording.\n"
        "5. Separate facts from claims. If something is only what a source says, write it as a claim, not as verified truth.\n"
        "6. Translate jargon and official phrasing into everyday language. Avoid words like \u63a8\u8fdb, \u8d4b\u80fd, \u91ca\u653e\u4fe1\u53f7, \u5f70\u663e, \u7a33\u4e2d\u5411\u597d unless you are explaining why they are vague.\n"
        "7. Light dry humor is welcome when deflating bureaucratic, corporate, or political theater, but do not joke about deaths, disasters, victims, or vulnerable people.\n"
        "8. Do not invent facts beyond the input articles.\n"
        "Writing style:\n"
        "- Short sentences. No grand conclusions. No lecture tone.\n"
        "- The title should be a rewritten human-friendly Chinese title, not a copied headline.\n"
        "- The summary should first say what happened, then translate why it matters in normal language.\n"
        "- The why field should be a useful caveat, hidden context, or what to watch next. It may include a mild quip if the topic is not tragic.\n"
        "Return valid JSON only with this schema:\n"
        "{\n"
        '  "overview": "one casual Chinese sentence about the day\'s main pattern",\n'
        '  "items": [\n'
        "    {\n"
        '      "title": "short human-friendly Chinese title",\n'
        '      "summary": "two plain Chinese sentences: what happened, then what it means in human terms",\n'
        '      "why": "one plain Chinese sentence giving caveat, context, or what to watch next",\n'
        '      "value_score": "4.5/5",\n'
        '      "source": "string",\n'
        '      "link": "https://..."\n'
        "    }\n"
        "  ]\n"
        "}\n\n"
        "Input articles:\n"
        + "\n\n".join(serialized_articles)
    )


def build_fallback_digest(articles: list[Article], max_items: int, reason: str | None = None) -> dict:
    items = []
    for article in articles:
        if len(items) >= max_items:
            break
        if not is_http_url(article.link):
            continue
        summary = article.summary or "\u6682\u65e0\u6458\u8981\u3002"
        items.append(
            {
                "title": article.title,
                "summary": summary[:140],
                "why": "\u8fd9\u6761\u5148\u5f53\u7ebf\u7d22\u770b\uff0c\u7b49\u66f4\u591a\u4fe1\u606f\u51fa\u6765\u518d\u5224\u65ad\u4e5f\u4e0d\u8fdf\u3002",
                "value_score": f"{article.value_score:.1f}/5" if article.value_score else "",
                "source": article.source,
                "link": article.link,
            }
        )

    overview = "\u81ea\u52a8\u89e3\u8bfb\u6ca1\u8dd1\u6210\uff0c\u5148\u628a\u6293\u5230\u7684\u91cd\u8981\u65b0\u95fb\u5217\u51fa\u6765\uff0c\u522b\u5148\u88ab\u6807\u9898\u5e26\u7740\u8d70\u3002"
    if reason:
        overview += f"\u964d\u7ea7\u539f\u56e0\uff1a{clean_text(reason)[:80]}"
    return {
        "overview": overview,
        "items": items,
    }


def parse_digest_response(text: str, fallback_articles: list[Article], max_items: int) -> dict:
    cleaned = strip_code_fences(text)
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", cleaned, re.S)
        if not match:
            return build_fallback_digest(fallback_articles, max_items)
        try:
            data = json.loads(match.group(0))
        except json.JSONDecodeError:
            return build_fallback_digest(fallback_articles, max_items)

    article_by_link: dict[str, Article] = {}
    for article in fallback_articles:
        if is_http_url(article.link):
            article_by_link.setdefault(article.link, article)

    items = []
    for item in data.get("items", [])[:max_items]:
        title = clean_text(str(item.get("title", "")))
        summary = clean_text(str(item.get("summary", "")))
        why = clean_text(str(item.get("why", "")))
        link = str(item.get("link", "")).strip()
        article = article_by_link.get(link)
        if title and summary and article:
            value_score = f"{article.value_score:.1f}/5" if article.value_score else clean_text(str(item.get("value_score", "")))
            items.append(
                {
                    "title": title,
                    "summary": summary,
                    "why": why or "\u8fd9\u4ef6\u4e8b\u8fd8\u8981\u770b\u540e\u7eed\u7ec6\u8282\uff0c\u5148\u522b\u6025\u7740\u4e0b\u7ed3\u8bba\u3002",
                    "value_score": value_score,
                    "source": article.source or "\u7efc\u5408\u6574\u7406",
                    "link": article.link,
                }
            )

    if not items:
        return build_fallback_digest(fallback_articles, max_items)

    overview = clean_text(str(data.get("overview", ""))) or "\u4eca\u5929\u7684\u65b0\u95fb\u4e3b\u8981\u770b\u4e24\u4ef6\u4e8b\uff1a\u54ea\u4e9b\u771f\u53d1\u751f\u4e86\uff0c\u54ea\u4e9b\u53ea\u662f\u5404\u65b9\u5728\u62a2\u8bdd\u7b52\u3002"
    return {
        "overview": overview,
        "items": items,
    }


def summarize_with_deepseek(
    base_url: str,
    api_key: str,
    model: str,
    prompt: str,
    system_prompt: str = "You are a sharp, plainspoken news explainer with light dry humor. Always answer with valid JSON only.",
    temperature: float = 0.45,
    max_tokens: int = DEEPSEEK_MAX_TOKENS,
    thinking_mode: str = "disabled",
) -> str:
    url = f"{base_url}{DEEPSEEK_CHAT_COMPLETIONS_PATH}"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": model,
        "messages": [
            {
                "role": "system",
                "content": system_prompt,
            },
            {
                "role": "user",
                "content": prompt,
            },
        ],
        "temperature": temperature,
        "thinking": {
            "type": thinking_mode,
        },
        "response_format": {
            "type": "json_object",
        },
        "max_tokens": max_tokens,
    }

    response = requests.post(
        url,
        headers=headers,
        json=payload,
        timeout=DEEPSEEK_TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    try:
        data = response.json()
    except ValueError as exc:
        raise ValueError("DeepSeek returned a non-JSON response.") from exc
    choices = data.get("choices") or []
    if not choices:
        raise ValueError(f"Unexpected DeepSeek response: {json.dumps(data, ensure_ascii=False)}")
    try:
        content = choices[0]["message"]["content"].strip()
    except (KeyError, TypeError, AttributeError) as exc:
        raise ValueError(f"Unexpected DeepSeek response: {json.dumps(data, ensure_ascii=False)}") from exc
    if not content:
        raise ValueError("DeepSeek returned empty content.")
    return content


def build_sign_fields(secret: str) -> dict:
    if not secret:
        return {}

    timestamp = str(int(datetime.now().timestamp()))
    string_to_sign = f"{timestamp}\n{secret}"
    digest = hmac.new(
        string_to_sign.encode("utf-8"),
        digestmod=hashlib.sha256,
    ).digest()
    sign = base64.b64encode(digest).decode("utf-8")
    return {
        "timestamp": timestamp,
        "sign": sign,
    }


def truncate_for_card(text: str, limit: int) -> str:
    text = clean_text(text)
    return text if len(text) <= limit else text[: limit - 3] + "..."


def build_card_payload(digest: dict, secret: str) -> dict:
    today = datetime.now(UTC8).strftime("%Y-%m-%d")
    elements: list[dict] = [
        {
            "tag": "div",
            "text": {
                "tag": "lark_md",
                "content": f"**{CARD_OVERVIEW}**\n{truncate_for_card(digest['overview'], 180)}",
            },
        },
        {"tag": "hr"},
    ]

    for index, item in enumerate(digest["items"], start=1):
        body = (
            f"**{index}. {truncate_for_card(item['title'], 90)}**\n"
            f"{truncate_for_card(item['summary'], 220)}\n\n"
            f"**{CARD_REASON}\uff1a** {truncate_for_card(item['why'], 140)}\n"
            f"**{CARD_VALUE}\uff1a** {truncate_for_card(str(item.get('value_score', '')), 20)}\n"
            f"**{CARD_SOURCE}\uff1a** {truncate_for_card(item['source'], 60)}"
        )
        elements.append(
            {
                "tag": "div",
                "text": {
                    "tag": "lark_md",
                    "content": body,
                },
            }
        )
        elements.append(
            {
                "tag": "action",
                "actions": [
                    {
                        "tag": "button",
                        "text": {
                            "tag": "plain_text",
                            "content": CARD_OPEN,
                        },
                        "type": "default",
                        "url": item["link"],
                    }
                ],
            }
        )
        if index != len(digest["items"]):
            elements.append({"tag": "hr"})

    elements.append(
        {
            "tag": "note",
            "elements": [
                {
                    "tag": "plain_text",
                    "content": CARD_FOOTER,
                }
            ],
        }
    )

    payload = {
        "msg_type": "interactive",
        "card": {
            "config": {
                "wide_screen_mode": True,
                "enable_forward": True,
            },
            "header": {
                "template": "blue",
                "title": {
                    "tag": "plain_text",
                    "content": f"{CARD_TITLE} | {today}",
                },
            },
            "elements": elements,
        },
    }
    payload.update(build_sign_fields(secret))
    return payload


def build_empty_card(secret: str, news_hours: int) -> dict:
    payload = {
        "msg_type": "interactive",
        "card": {
            "config": {
                "wide_screen_mode": True,
                "enable_forward": True,
            },
            "header": {
                "template": "grey",
                "title": {
                    "tag": "plain_text",
                    "content": f"{CARD_TITLE} | {datetime.now(UTC8):%Y-%m-%d}",
                },
            },
            "elements": [
                {
                    "tag": "div",
                    "text": {
                        "tag": "lark_md",
                        "content": f"{EMPTY_MESSAGE}\n\n\u68c0\u67e5\u8303\u56f4\uff1a\u6700\u8fd1 {news_hours} \u5c0f\u65f6",
                    },
                }
            ],
        },
    }
    payload.update(build_sign_fields(secret))
    return payload


def build_feishu_probe_card(secret: str) -> dict:
    payload = {
        "msg_type": "interactive",
        "card": {
            "config": {
                "wide_screen_mode": True,
                "enable_forward": False,
            },
            "header": {
                "template": "green",
                "title": {
                    "tag": "plain_text",
                    "content": f"DailyNewsFeishu webhook check | {datetime.now(UTC8):%Y-%m-%d}",
                },
            },
            "elements": [
                {
                    "tag": "div",
                    "text": {
                        "tag": "plain_text",
                        "content": "Feishu webhook check passed. No news digest was sent.",
                    },
                }
            ],
        },
    }
    payload.update(build_sign_fields(secret))
    return payload


def validate_feishu_response(data: dict) -> None:
    status_values = []
    for key in ("code", "StatusCode"):
        if key in data:
            status_values.append((key, data[key]))

    if not status_values:
        raise ValueError(f"Feishu webhook response missing status code: {json.dumps(data, ensure_ascii=False)}")

    failed = [(key, value) for key, value in status_values if value not in (0, "0")]
    if failed:
        raise ValueError(f"Feishu webhook failed: {json.dumps(data, ensure_ascii=False)}")


def send_to_feishu(webhook_url: str, payload: dict) -> None:
    try:
        response = requests.post(
            webhook_url,
            json=payload,
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
    except requests.RequestException as exc:
        raise ValueError(f"Feishu webhook request failed: {exc}") from exc
    try:
        data = response.json()
    except ValueError as exc:
        raise ValueError("Feishu webhook returned a non-JSON response.") from exc
    validate_feishu_response(data)


def print_feed_check(articles: list[Article]) -> None:
    print(f"Fetched {len(articles)} deduplicated articles.")
    domestic_count = sum(1 for article in articles if source_priority(article))
    global_count = len(articles) - domestic_count
    print(f"Domestic articles: {domestic_count}; international articles: {global_count}.")
    for article in articles[:8]:
        published = article.published_at.strftime("%Y-%m-%d %H:%M") if article.published_at else "unknown"
        domestic = "domestic" if source_priority(article) else "global"
        print(f"- {published} | {domestic} | {article.source} | {article.title}")
    global_samples = [article for article in articles if not source_priority(article)][:5]
    if global_samples:
        print("International samples:")
        for article in global_samples:
            published = article.published_at.strftime("%Y-%m-%d %H:%M") if article.published_at else "unknown"
            print(f"- {published} | {article.source} | {article.title}")


def minimum_feed_check_articles(max_articles: int) -> int:
    return max(1, min(10, max_articles))


def validate_feed_check_articles(articles: list[Article], min_articles: int) -> None:
    if len(articles) < min_articles:
        raise ValueError(f"RSS feed check found {len(articles)} articles; expected at least {min_articles}.")


def check_deepseek(config: dict) -> None:
    try:
        probe_text = summarize_with_deepseek(
            base_url=config["deepseek_base_url"],
            api_key=config["deepseek_api_key"],
            model=config["deepseek_model"],
            prompt='Return exactly this JSON object: {"ok": true}',
            system_prompt="You validate API connectivity. Always answer with valid JSON only.",
            temperature=0,
            max_tokens=64,
            thinking_mode=config["deepseek_thinking_mode"],
        )
    except requests.RequestException as exc:
        if is_http_status_error(exc, AUTH_ERROR_STATUS_CODES):
            raise ValueError("DeepSeek authentication failed. Check DEEPSEEK_API_KEY.") from exc
        raise ValueError(f"DeepSeek request failed. Check network or DEEPSEEK_BASE_URL: {exc}") from exc
    try:
        probe_data = json.loads(strip_code_fences(probe_text))
    except json.JSONDecodeError as exc:
        raise ValueError("DeepSeek probe did not return valid JSON.") from exc
    if probe_data.get("ok") is not True:
        raise ValueError("DeepSeek probe returned an unexpected JSON payload.")
    print(f"DeepSeek check passed for model {config['deepseek_model']}.")


def check_feishu(config: dict) -> None:
    send_to_feishu(
        config["feishu_webhook_url"],
        build_feishu_probe_card(config["feishu_bot_secret"]),
    )
    print("Feishu webhook check passed.")


def print_config_check(config: dict) -> None:
    print(
        "Config check passed "
        f"({len(config['rss_feeds'])} RSS sources, model {config['deepseek_model']}, "
        f"thinking {config['deepseek_thinking_mode']}, "
        f"{config['max_summary_items']} summary items)."
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check-config", action="store_true", help="Only validate required configuration.")
    parser.add_argument("--check-feeds", action="store_true", help="Only test feed fetching and print sample items.")
    parser.add_argument("--check-deepseek", action="store_true", help="Only validate DeepSeek API credentials and model.")
    parser.add_argument("--check-feishu", action="store_true", help="Send a small probe card to validate Feishu webhook.")
    parser.add_argument("--dry-run", action="store_true", help="Build the digest without sending it to Feishu.")
    args = parser.parse_args()

    require_news_settings = args.check_config or args.check_feeds or not (args.check_deepseek or args.check_feishu)
    config = load_config(
        require_deepseek=args.check_config or args.check_deepseek or not (args.check_feeds or args.check_feishu),
        require_feishu=args.check_config or args.check_feishu or not (args.check_feeds or args.check_deepseek or args.dry_run),
        require_rss=require_news_settings,
        require_news_settings=require_news_settings,
    )
    if args.check_config:
        print_config_check(config)
        return

    if args.check_deepseek:
        check_deepseek(config)
        return

    if args.check_feishu:
        check_feishu(config)
        return

    articles = fetch_articles(
        feed_sources=config["rss_feeds"],
        since_hours=config["news_hours"],
        max_articles=config["max_articles"],
    )

    if args.check_feeds:
        print_feed_check(articles)
        validate_feed_check_articles(articles, minimum_feed_check_articles(config["max_articles"]))
        return

    if not articles:
        payload = build_empty_card(config["feishu_bot_secret"], config["news_hours"])
        if args.dry_run:
            print("Dry run built empty-state card from 0 source articles. Feishu send skipped.")
            return
        send_to_feishu(
            config["feishu_webhook_url"],
            payload,
        )
        print("No articles found. Sent empty-state card.")
        return

    try:
        selected_articles = rank_articles_by_value(
            articles=articles,
            base_url=config["deepseek_base_url"],
            api_key=config["deepseek_api_key"],
            model=config["deepseek_model"],
            thinking_mode=config["deepseek_thinking_mode"],
            max_candidates=config["value_score_candidates"],
            max_items=config["max_summary_items"],
        )
    except requests.RequestException as exc:
        if is_http_status_error(exc, AUTH_ERROR_STATUS_CODES):
            raise ValueError("DeepSeek authentication failed. Check DEEPSEEK_API_KEY.") from exc
        print(f"Warning: DeepSeek value scoring failed, using rule-ranked articles: {exc}")
        selected_articles = select_diverse_scored_articles(
            filter_rule_noise(articles, config["value_score_candidates"]),
            config["max_summary_items"],
        )
    except ValueError as exc:
        print(f"Warning: DeepSeek value scoring invalid, using rule-ranked articles: {exc}")
        selected_articles = select_diverse_scored_articles(
            filter_rule_noise(articles, config["value_score_candidates"]),
            config["max_summary_items"],
        )

    prompt = build_digest_prompt(selected_articles, config["max_summary_items"])
    try:
        raw_digest = summarize_with_deepseek(
            base_url=config["deepseek_base_url"],
            api_key=config["deepseek_api_key"],
            model=config["deepseek_model"],
            prompt=prompt,
            thinking_mode=config["deepseek_thinking_mode"],
        )
        digest = parse_digest_response(
            raw_digest,
            fallback_articles=selected_articles,
            max_items=config["max_summary_items"],
        )
    except requests.RequestException as exc:
        if is_http_status_error(exc, AUTH_ERROR_STATUS_CODES):
            raise ValueError("DeepSeek authentication failed. Check DEEPSEEK_API_KEY.") from exc
        print(f"Warning: DeepSeek request failed, using fallback digest: {exc}")
        digest = build_fallback_digest(
            selected_articles,
            max_items=config["max_summary_items"],
            reason="DeepSeek request timeout or network error",
        )
    except ValueError as exc:
        print(f"Warning: DeepSeek response invalid, using fallback digest: {exc}")
        digest = build_fallback_digest(
            selected_articles,
            max_items=config["max_summary_items"],
            reason="DeepSeek returned invalid content",
        )

    payload = build_card_payload(digest, config["feishu_bot_secret"])
    if args.dry_run:
        print(
            f"Dry run built card with {len(digest['items'])} digest items "
            f"from {len(selected_articles)} selected articles and {len(articles)} source articles. Feishu send skipped."
        )
        return

    send_to_feishu(config["feishu_webhook_url"], payload)
    print(f"Sent card summary with {len(selected_articles)} selected articles from {len(articles)} source articles.")


if __name__ == "__main__":
    try:
        main()
    except ValueError as exc:
        print(f"Error: {exc}")
        raise SystemExit(1)
