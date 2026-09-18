#!/usr/bin/env python3
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from urllib.error import HTTPError

API_BASE = "https://graph.threads.net/v1.0"
ROOT = Path(__file__).resolve().parent
OUT_FILE = ROOT / "discovery.json"

QUERIES = [
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


def load_existing():
    if not OUT_FILE.exists():
        return {}
    try:
        return json.loads(OUT_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


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
    existing = load_existing()
    last = parse_iso(str(existing.get("searched_at", "")))
    existing_errors = existing.get("errors", []) or []
    if last and now - last < timedelta(minutes=55) and not existing_errors:
        print("Discovery was refreshed less than 55 minutes ago; skipping.")
        return 0

    all_rows = {}
    errors = []

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
        # Keep keyword_search requests deliberately minimal. Optional media
        # fields have caused Meta to return opaque HTTP 500/code=1 responses.
        # If RECENT itself is temporarily rejected, retry without search_type.
        attempts = [
            {"q": query, "search_type": "RECENT", "fields": FIELDS, "limit": 25, "access_token": token},
            {"q": query, "fields": FIELDS, "limit": 25, "access_token": token},
            {"q": query, "fields": "id,text", "limit": 25, "access_token": token},
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
            errors.append({"query": query, "error": " | ".join(attempt_errors)})
            continue
        for item in payload.get("data", []) or []:
            post_id = str(item.get("id", "")).strip()
            if not post_id:
                continue
            row = dict(item)
            row["matched_query"] = query
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
    OUT_FILE.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Saved {len(rows)} unique Threads discovery results; errors={len(errors)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
