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
    "ищу мобильного разработчика",
    "нужен мобильный разработчик",
    "ищу разработчика приложения",
    "нужен Flutter разработчик",
    "looking for mobile app developer",
    "need a mobile app developer",
    "looking for Flutter developer",
    "mobile app development partner",
    "build a mobile app",
]

FIELDS = "id,username,text,timestamp,permalink,shortcode,has_replies,is_reply"


def api_json(url: str) -> dict:
    req = Request(url, headers={"User-Agent": "KostttS-Threads-Discovery/1.1"})
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

    for query in QUERIES:
        params = {
            "q": query,
            "search_type": "RECENT",
            "fields": FIELDS,
            "access_token": token,
        }
        url = f"{API_BASE}/keyword_search?{urlencode(params)}"
        try:
            payload = api_json(url)
            for item in payload.get("data", []) or []:
                post_id = str(item.get("id", "")).strip()
                if not post_id:
                    continue
                row = dict(item)
                row["matched_query"] = query
                all_rows[post_id] = row
        except Exception as exc:
            errors.append({"query": query, "error": str(exc)})

    rows = list(all_rows.values())
    rows.sort(key=lambda x: str(x.get("timestamp", "")), reverse=True)

    output = {
        "searched_at": now.isoformat(),
        "queries": QUERIES,
        "count": len(rows),
        "results": rows[:120],
        "errors": errors,
    }
    OUT_FILE.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Saved {len(rows)} unique Threads discovery results; errors={len(errors)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
