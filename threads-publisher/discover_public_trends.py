#!/usr/bin/env python3
"""Bounded, public-only Threads trend sampling. Never claims full-platform coverage.

The official keyword API is monitored separately in discover_threads.py.
This fallback reads only publicly served search pages. No login or tokens.
Unknown counters are null, never zero. Errors are explicitly recorded.
"""
import html
import json
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

SCHEMA_VERSION = 2
ROOT = Path(__file__).resolve().parent
OUT = ROOT / "external_trends.json"
STATE = ROOT / "trends_state.json"
SELF = "konstantin47209"
LOCAL_TZ = ZoneInfo("Asia/Jerusalem")
SCRIPT_RE = re.compile(r'<script[^>]*type=["\x27]application/json["\x27][^>]*>(.*?)</script>', re.I | re.S)

# Fixed buyer and creator terms, plus rotating broad RU/EN topics. This is a
# sample of searchable public posts, NOT a firehose of all Threads content.
CORE = [
    "FlutterFlow", "Flutter", "MVP app", "ищу разработчика",
    "mobile app", "agency", "стартап", "бизнес"
]
ROTATING = [
    "приложение", "предприниматель", "клиенты", "маркетинг",
    "ошибка", "история", "вопрос", "работа", "деньги",
    "startup", "founder", "customer", "marketing",
    "mistake", "story", "unpopular opinion", "business owner",
    "sales", "AI", "software", "freelancer", "product launch",
    "mobile developer", "technical partner"
]

def now_utc():
    return datetime.now(timezone.utc)

def load(path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default

def save(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

def number(value):
    if isinstance(value, bool):
        return None
    if isinstance(value, int) and value >= 0:
        return value
    if isinstance(value, str) and value.isdigit():
        return int(value)
    return None

def collect_nodes(node, posts, depth=0):
    if depth > 35:
        return
    if isinstance(node, list):
        for item in node:
            collect_nodes(item, posts, depth + 1)
    elif isinstance(node, dict):
        code = node.get("code")
        caption = node.get("caption")
        if (isinstance(code, str) and isinstance(caption, dict)
                and ("taken_at" in node or "like_count" in node)
                and isinstance(node.get("user"), dict)):
            if code not in posts or len(json.dumps(node)) > len(json.dumps(posts[code])):
                posts[code] = node
        for value in node.values():
            if isinstance(value, (list, dict)):
                collect_nodes(value, posts, depth + 1)

def read_blocks(page):
    posts = {}
    for block in SCRIPT_RE.findall(page):
        for candidate in (block, html.unescape(block)):
            try:
                collect_nodes(json.loads(candidate), posts)
                break
            except ValueError:
                continue
    return list(posts.values())

def relevant(text, q):
    content = " ".join(str(text or "").lower().split())
    needle = " ".join(q.lower().lstrip("#").split())
    if not needle or not content:
        return False
    if needle in content:
        return True
    words = [w for w in needle.split() if len(w) > 1]
    return len(words) > 1 and all(word in content for word in words)

def fetch(q, view):
    url = "https://www.threads.com/search?q=" + quote(q, safe="") + "&serp_type=" + view
    req = Request(url, headers={
        "User-Agent": "facebookexternalhit/1.1",
        "Accept": "text/html",
        "Accept-Language": "en-US,en;q=0.9"
    })
    try:
        with urlopen(req, timeout=8) as resp:
            if resp.status != 200:
                return [], {"http_status": resp.status}
            page = resp.read(5_000_000).decode("utf-8", errors="replace")
        rows = read_blocks(page)
        return rows, {"http_status": 200, "embedded_posts": len(rows),
                      "condition": "ok" if rows else "no_public_data_or_login_gate"}
    except HTTPError as exc:
        return [], {"http_status": exc.code, "condition": "http_error"}
    except (URLError, OSError, TimeoutError, ValueError) as exc:
        return [], {"condition": "fetch_error", "detail": str(exc)[:160]}

def normalize(post, query, source_view, when, prior):
    user = post.get("user") or {}
    info = post.get("text_post_app_info") or {}
    username = str(user.get("username") or "").strip()
    code = str(post.get("code") or "").strip()
    if not username or not code or username.lower() == SELF:
        return None
    body = str((post.get("caption") or {}).get("text") or "").strip()
    if not relevant(body, query):
        return None
    ts = number(post.get("taken_at"))
    if not ts or ts > int(when.timestamp()) + 120 or ts < int(when.timestamp()) - 7 * 86400:
        return None
    age_h = max(0.2, (when.timestamp() - ts) / 3600)
    likes = number(post.get("like_count"))
    replies = number(info.get("direct_reply_count"))
    reposts = number(info.get("repost_count"))
    quotes = number(info.get("quote_count"))
    previous = prior.get(code, {})
    prev_at = number(previous.get("last_seen_unix"))
    growth = None
    if prev_at and prev_at < int(when.timestamp()) and prev_at >= int(when.timestamp()) - 3 * 86400:
        changed = {}
        for key, current in (("likes", likes), ("replies", replies), ("reposts", reposts)):
            old = number(previous.get(key))
            changed[key] = max(0, current - old) if old is not None and current is not None else None
        growth = {"elapsed_hours": round((when.timestamp() - prev_at) / 3600, 2),
                  "likes_delta": changed["likes"], "replies_delta": changed["replies"],
                  "reposts_delta": changed["reposts"]}
    weighted = (likes or 0) + 4 * (replies or 0) + 3 * (reposts or 0)
    # A ranking heuristic, not an engagement rate or a verified viral label.
    score = round(weighted / (age_h ** 0.5), 2)
    if growth and growth.get("elapsed_hours"):
        velocity = (growth.get("likes_delta") or 0) + 4 * (growth.get("replies_delta") or 0) + 3 * (growth.get("reposts_delta") or 0)
        score += round(velocity / max(0.5, growth["elapsed_hours"]), 2)
    return {
        "code": code, "post_id": str(post.get("pk") or ""),
        "url": "https://www.threads.com/@" + username + "/post/" + code,
        "username": username, "timestamp": datetime.fromtimestamp(ts, timezone.utc).isoformat(),
        "age_hours": round(age_h, 1), "text_excerpt": body[:550],
        "matched_queries": [query], "views": None, "likes": likes, "replies": replies,
        "reposts": reposts, "quotes": quotes, "growth": growth,
        "score_heuristic": round(score, 2),
        "high_engagement_candidate": bool((likes or 0) >= 100 or (replies or 0) >= 20 or (reposts or 0) >= 30),
        "source": "public_threads_search_html", "source_view": source_view
    }

def buyer_signal(row):
    t = row["text_excerpt"].lower()
    # Avoid agencies advertising their own services or 'algorithm connect me' posts.
    if any(s in t for s in ("get a free quote", "message us", "we build apps",
                             "we are a software house", "connect me with founders",
                             "our development services", "dm for projects")):
        return False
    exact_need = re.search(
        r"(looking for|need|hiring|hire|seeking|ищу|нужен|нужна|ищем|требуется)"
        r".{0,80}(flutter\s*(developer|dev)|mobile\s*(app\s*)?developer|"
        r"app\s*developer|developer\s*for\s*(an?\s*)?app|"
        r"разработчик|разработчика|программист)",
        t, re.I | re.S
    )
    app_need = re.search(
        r"(need|looking for|хочу|нужно|нужен|ищу).{0,55}"
        r"(someone to build|build an?\s*(android|ios|mobile)\s*app|"
        r"разработать приложение|создать приложение|приложение под ключ)",
        t, re.I | re.S
    )
    return bool(exact_need or app_need)

def scan():
    when = now_utc()
    local = when.astimezone(LOCAL_TZ)
    slot = local.strftime("%Y-%m-%d %H")
    state = load(STATE, {"last_slot": "", "posts": {}})
    # Even local hours only; each slot once. The GitHub workflow runs 4x/hour.
    force_probe = os.getenv("GITHUB_EVENT_NAME") == "push"
    if (local.hour % 2 and not force_probe) or (state.get("last_slot") == slot and state.get("schema_version") == SCHEMA_VERSION):
        save(OUT, {"checked_at": when.isoformat(), "status": "skipped",
                   "reason": "outside_two_hour_window_or_already_scanned",
                   "last_scan_at": state.get("last_scan_at"), "coverage": "bounded_public_sample"})
        return
    prior = state.get("posts") or {}
    # Rotate 4 broad themes across 2-hour slots, keep 8 buyer/business anchors.
    start = ((local.toordinal() * 12) + local.hour // 2) * 4
    rotating = [ROTATING[(start + i) % len(ROTATING)] for i in range(4)]
    queries = CORE + rotating
    all_posts = {}
    diagnostics = []
    total_embedded = 0
    deadline = time.monotonic() + 115  # avoid holding publishing runs for long
    budget_exhausted = False
    for q in queries:
        for view in ("recent", "default"):
            if time.monotonic() >= deadline:
                budget_exhausted = True
                break
            found, diag = fetch(q, view)
            total_embedded += len(found)
            diagnostics.append({"query": q, "view": view, **diag})
            for p in found:
                row = normalize(p, q, view, when, prior)
                if not row:
                    continue
                key = row["code"]
                if key in all_posts:
                    all_posts[key]["matched_queries"] = sorted(set(all_posts[key]["matched_queries"] + [q]))
                    if all_posts[key]["score_heuristic"] < row["score_heuristic"]:
                        row["matched_queries"] = all_posts[key]["matched_queries"]
                        all_posts[key] = row
                else:
                    all_posts[key] = row
            time.sleep(0.30)
        if budget_exhausted:
            break
    ranked = sorted(all_posts.values(), key=lambda x: x["score_heuristic"], reverse=True)
    buyer = [x for x in ranked if buyer_signal(x)]
    good_responses = sum(d.get("embedded_posts", 0) > 0 for d in diagnostics)
    blocked = sum(d.get("http_status") in (403, 429) for d in diagnostics)
    status = "verified_public_sample" if ranked else "unavailable_or_no_verified_results"
    output = {
        "checked_at": when.isoformat(), "status": status,
        "coverage": "bounded_public_search_sample_not_all_threads",
        "notes": ["View counts on external posts may not be public. Null is not zero.",
                  "TOP/recent pages are samples and sometimes contain unrelated posts, which are filtered.",
                  "High-engagement candidate means an explicit threshold, not proof of virality."],
        "queries": queries, "page_requests": len(diagnostics),
        "pages_with_embedded_posts": good_responses, "embedded_posts_before_filter": total_embedded,
        "verified_unique_external_posts": len(ranked),
        "high_engagement_candidates": sum(x["high_engagement_candidate"] for x in ranked),
        "http_403_or_429": blocked, "time_budget_exhausted": budget_exhausted,
        "diagnostics": diagnostics,
        "top_posts": ranked[:25], "buyer_signals": buyer[:12]
    }
    save(OUT, output)
    updated = dict(prior)
    for row in ranked:
        old = updated.get(row["code"], {})
        updated[row["code"]] = {
            "first_seen_unix": old.get("first_seen_unix") or int(when.timestamp()),
            "last_seen_unix": int(when.timestamp()),
            "likes": row["likes"], "replies": row["replies"], "reposts": row["reposts"]
        }
    # Retain up to 1200 recent post snapshots for acceleration comparisons.
    updated = dict(sorted(updated.items(),
                          key=lambda item: number(item[1].get("last_seen_unix")) or 0,
                          reverse=True)[:1200])
    save(STATE, {"schema_version": SCHEMA_VERSION, "last_slot": slot, "last_scan_at": when.isoformat(),
                 "status": status, "posts": updated})
    print("Threads public trend sample:", status, len(ranked),
          "verified posts,", len(buyer), "possible buyer signals in", len(diagnostics), "pages")

if __name__ == "__main__":
    scan()
