#!/usr/bin/env python3
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from urllib.error import HTTPError

API_BASE = "https://graph.threads.net/v1.0"
# App Review refresh marker: 2026-09-18
ROOT = Path(__file__).resolve().parent
OUT_FILE = ROOT / "discovery.json"
STATE_FILE = ROOT / "state.json"

QUERIES = [
    # Review/test-friendly broad query; also useful for catching Russian app discussions.
    "приложение",
    # Direct mobile-development demand — first priority.
    "ищу мобильного разработчика",
    "нужен мобильный разработчик",
    "ищу разработчика приложения",
    "нужен Flutter разработчик",
    "looking for mobile app developer",
    "need a mobile app developer",
    "looking for Flutter developer",
    "mobile app development partner",
    "build a mobile app",
    "нужен разработчик iOS Android",
    "ищу подрядчика мобильное приложение",
    "доделать мобильное приложение",
    "разработчик MVP приложения",
    "white label mobile developer",
    "mobile development subcontractor",
    "agency needs mobile developer",
    # Broader discovery terms. Specific demand phrases are still preferred,
    # but these keep the search from collapsing to only our own posts.
    "FlutterFlow",
    "mobile app",
    "мобильное приложение",
    "ищу разработчика",

    # People/partners who say they can bring clients or have client flow.
    "есть клиенты нужен разработчик",
    "ищу разработчика под клиентов",
    "ищу партнера разработчика",
    "партнер разработчик за процент",
    "могу приводить клиентов",
    "приведу клиентов разработчику",
    "есть поток клиентов",
    "ищу технического партнера",
    "лидогенерация для разработчиков",
    "ищу подрядчика под клиентов",
    "have clients need developer",
    "I can bring clients to developers",
    "looking for development partner",
    "looking for technical delivery partner",
    "need development partner for clients",
    "lead generation developers partnership",
    "looking for dev partner for clients",
    "agency looking for development partner",
]

FIELDS = "id,username,text,timestamp,permalink"


def api_json(url: str) -> dict:
    req = Request(url, headers={"User-Agent": "KostttS-Threads-Discovery/1.2"})
    try:
        with urlopen(req, timeout=60) as response:
            raw = response.read().decode("utf-8")
            return json.loads(raw) if raw else {}
    except HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Threads API HTTP {exc.code}: {raw}") from exc


def load_json(path: Path, default):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def save_json(path: Path, value) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def parse_iso(value: str):
    try:
        if value.endswith("Z"):
            value = value[:-1] + "+00:00"
        return datetime.fromisoformat(value).astimezone(timezone.utc)
    except Exception:
        return None


def main() -> int:
    token = os.getenv("THREADS_ACCESS_TOKEN", "").strip()
    if not token:
        raise RuntimeError("THREADS_ACCESS_TOKEN is not set")

    now = datetime.now(timezone.utc)
    state = load_json(STATE_FILE, {})
    last = parse_iso(str(state.get("last_discovery_at", "")))
    last_had_errors = bool(state.get("last_discovery_had_errors", False))
    if last and now - last < timedelta(minutes=55) and not last_had_errors:
        print("Discovery was refreshed less than 55 minutes ago; skipping.")
        return 0

    all_rows = {}
    errors = []
    self_username = "konstantin47209"
    since_ts = int((now - timedelta(days=7)).timestamp())
    until_ts = int(now.timestamp())

    token_debug = {}
    try:
        debug_params = {"input_token": token, "access_token": token}
        debug_url = f"{API_BASE}/debug_token?{urlencode(debug_params)}"
        debug_data = api_json(debug_url).get("data", {})
        token_debug = {
            "is_valid": debug_data.get("is_valid"),
            "type": debug_data.get("type"),
            "application": debug_data.get("application"),
            "expires_at": debug_data.get("expires_at"),
            "data_access_expires_at": debug_data.get("data_access_expires_at"),
            "scopes": debug_data.get("scopes", []),
            "user_id": debug_data.get("user_id"),
        }
    except Exception as exc:
        token_debug = {"error": str(exc)}

    print("Threads token scopes:", token_debug.get("scopes", []), "valid=", token_debug.get("is_valid"))

    for query in QUERIES:
        # Search both RECENT and TOP. RECENT alone can heavily favor our own
        # posts for broad terms, which makes discovery look healthy while
        # finding zero external opportunities.
        for search_type in ("RECENT", "TOP"):
            attempts = [
                {
                    "q": query,
                    "search_type": search_type,
                    "search_mode": "KEYWORD",
                    "fields": FIELDS,
                    "limit": 25,
                    "since": since_ts,
                    "until": until_ts,
                    "access_token": token,
                },
                {
                    "q": query,
                    "search_type": search_type,
                    "fields": FIELDS,
                    "limit": 25,
                    "since": since_ts,
                    "until": until_ts,
                    "access_token": token,
                },
                {
                    "q": query,
                    "search_type": search_type,
                    "fields": "id,text",
                    "limit": 25,
                    "since": since_ts,
                    "until": until_ts,
                    "access_token": token,
                },
            ]
            payload = None
            attempt_errors = []
            for params in attempts:
                url = f"{API_BASE}/keyword_search?{urlencode(params)}"
                try:
                    payload = api_json(url)
                    break
                except Exception as exc:
                    attempt_errors.append(str(exc))
            if payload is None:
                errors.append(
                    {
                        "query": query,
                        "search_type": search_type,
                        "error": " | ".join(attempt_errors),
                    }
                )
                continue

            for item in payload.get("data", []) or []:
                post_id = str(item.get("id", "")).strip()
                username = str(item.get("username", "")).strip().lower()
                if not post_id or username == self_username:
                    continue
                row = dict(item)
                row["matched_query"] = query
                row["matched_search_type"] = search_type
                all_rows[post_id] = row

    rows = list(all_rows.values())
    rows.sort(key=lambda x: str(x.get("timestamp", "")), reverse=True)

    output = {
        "searched_at": now.isoformat(),
        "queries": QUERIES,
        "token_debug": token_debug,
        "count": len(rows),
        "results": rows[:160],
        "errors": errors,
    }
    save_json(OUT_FILE, output)
    state["last_discovery_at"] = now.isoformat()
    state["last_discovery_had_errors"] = bool(errors)
    save_json(STATE_FILE, state)
    print(f"Saved {len(rows)} unique Threads discovery results; errors={len(errors)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
