#!/usr/bin/env python3
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from urllib.error import HTTPError

API_BASE = "https://graph.threads.net"
ROOT = Path(__file__).resolve().parent
ANALYTICS_FILE = ROOT / "analytics.json"
INBOX_FILE = ROOT / "inbox.json"

THREAD_FIELDS = "id,media_type,permalink,username,text,timestamp,is_quote_post,has_replies"
REPLY_FIELDS = "id,media_type,permalink,username,text,timestamp,has_replies"
MINIMAL_MENTION_FIELDS = "id,permalink,username,text,timestamp"
POST_METRICS = "views,likes,replies,reposts,quotes,shares"
ACCOUNT_METRICS = "views,likes,replies,reposts,quotes,clicks,followers_count"


def api_json(path: str, params: dict | None = None) -> dict:
    params = dict(params or {})
    token = os.getenv("THREADS_ACCESS_TOKEN", "").strip()
    if not token:
        raise RuntimeError("THREADS_ACCESS_TOKEN is not set")
    params["access_token"] = token
    url = f"{API_BASE}{path}?{urlencode(params)}"
    req = Request(url, headers={"User-Agent": "KostttS-Threads-Monitor/1.1"})
    try:
        with urlopen(req, timeout=60) as response:
            raw = response.read().decode("utf-8")
            return json.loads(raw) if raw else {}
    except HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Threads API HTTP {exc.code}: {raw}") from exc


def save_json(path: Path, value) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def compact_error(exc: Exception) -> str:
    text = str(exc)
    return text if len(text) <= 1000 else text[:1000] + "..."


def try_call(errors: list[dict], name: str, fn, default):
    try:
        return fn()
    except Exception as exc:
        errors.append({"feature": name, "error": compact_error(exc)})
        return default


def normalize_insights(payload: dict) -> dict:
    result = {}
    for item in payload.get("data", []):
        name = item.get("name")
        if not name:
            continue
        if "total_value" in item:
            result[name] = item.get("total_value")
        elif "values" in item:
            result[name] = item.get("values", [])
        else:
            result[name] = item
    return result


def get_post_insights(thread_id: str, errors: list[dict]) -> dict:
    payload = try_call(
        errors,
        f"post_insights:{thread_id}",
        lambda: api_json(f"/{thread_id}/insights", {"metric": POST_METRICS}),
        {},
    )
    return normalize_insights(payload) if payload else {}


def get_mentions(errors: list[dict]) -> dict:
    try:
        return api_json("/me/mentions", {"fields": THREAD_FIELDS, "limit": 50})
    except Exception as first:
        try:
            return api_json("/me/mentions", {"fields": MINIMAL_MENTION_FIELDS, "limit": 25})
        except Exception as second:
            errors.append(
                {
                    "feature": "mentions",
                    "error": compact_error(second),
                    "first_attempt_error": compact_error(first),
                }
            )
            return {"data": []}


def main() -> int:
    now = datetime.now(timezone.utc).isoformat()
    analytics_errors: list[dict] = []
    inbox_errors: list[dict] = []

    profile = try_call(
        analytics_errors,
        "profile",
        lambda: api_json(
            "/me",
            {"fields": "id,username,name,threads_profile_picture_url,threads_biography"},
        ),
        {},
    )

    account_raw = try_call(
        analytics_errors,
        "account_insights",
        lambda: api_json("/me/threads_insights", {"metric": ACCOUNT_METRICS}),
        {},
    )
    account_insights = normalize_insights(account_raw) if account_raw else {}

    quota = try_call(
        analytics_errors,
        "publishing_quota",
        lambda: api_json(
            "/me/threads_publishing_limit",
            {"fields": "quota_usage,config,reply_quota_usage,reply_config"},
        ),
        {},
    )

    threads_payload = try_call(
        analytics_errors,
        "recent_threads",
        lambda: api_json("/me/threads", {"fields": THREAD_FIELDS, "limit": 20}),
        {"data": []},
    )
    recent_threads = threads_payload.get("data", [])[:10]
    posts = []
    replies = []
    seen_reply_ids = set()

    for thread in recent_threads:
        thread_id = str(thread.get("id", ""))
        enriched = dict(thread)
        if thread_id:
            enriched["insights"] = get_post_insights(thread_id, analytics_errors)
        posts.append(enriched)

        if thread_id and thread.get("has_replies"):
            reply_payload = try_call(
                inbox_errors,
                f"replies:{thread_id}",
                lambda tid=thread_id: api_json(
                    f"/{tid}/replies",
                    {"fields": REPLY_FIELDS, "reverse": "true", "limit": 50},
                ),
                {"data": []},
            )
            for reply in reply_payload.get("data", []):
                reply_id = str(reply.get("id", ""))
                if not reply_id or reply_id in seen_reply_ids:
                    continue
                seen_reply_ids.add(reply_id)
                item = dict(reply)
                item["root_thread_id"] = thread_id
                item["root_thread_permalink"] = thread.get("permalink")
                replies.append(item)

    own_replies_payload = try_call(
        inbox_errors,
        "own_replies_permission_probe",
        lambda: api_json("/me/replies", {"fields": REPLY_FIELDS, "limit": 10}),
        {"data": []},
    )
    own_replies = own_replies_payload.get("data", [])

    mentions_payload = get_mentions(inbox_errors)
    mentions = mentions_payload.get("data", [])

    analytics = {
        "generated_at": now,
        "profile": profile,
        "account_insights": account_insights,
        "publishing_quota": quota.get("data", quota),
        "recent_posts": posts,
        "errors": analytics_errors,
    }
    inbox = {
        "generated_at": now,
        "mentions": mentions,
        "replies_to_recent_posts": replies,
        "own_recent_replies": own_replies,
        "errors": inbox_errors,
    }

    save_json(ANALYTICS_FILE, analytics)
    save_json(INBOX_FILE, inbox)

    print(
        f"Threads monitor complete: {len(posts)} recent posts, "
        f"{len(replies)} incoming replies, {len(own_replies)} own replies, "
        f"{len(mentions)} mentions, "
        f"{len(analytics_errors) + len(inbox_errors)} feature errors."
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
