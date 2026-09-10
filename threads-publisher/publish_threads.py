#!/usr/bin/env python3
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from urllib.error import HTTPError

API_BASE = "https://graph.threads.net/v1.0"
ROOT = Path(__file__).resolve().parent
POSTS_FILE = ROOT / "posts.json"
REPLIES_FILE = ROOT / "replies.json"
STATE_FILE = ROOT / "state.json"


def api_json(url: str, method: str = "GET", data: dict | None = None) -> dict:
    body = None
    headers = {"User-Agent": "KostttS-Threads-Publisher/1.2"}
    if data is not None:
        body = urlencode(data).encode("utf-8")
        headers["Content-Type"] = "application/x-www-form-urlencoded"
    req = Request(url, data=body, method=method, headers=headers)
    try:
        with urlopen(req, timeout=60) as response:
            raw = response.read().decode("utf-8")
            return json.loads(raw) if raw else {}
    except HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Threads API HTTP {exc.code}: {raw}") from exc


def get_token() -> str:
    token = os.getenv("THREADS_ACCESS_TOKEN", "").strip()
    if not token:
        raise RuntimeError("THREADS_ACCESS_TOKEN is not set")
    return token


def get_me(token: str) -> dict:
    query = urlencode({"fields": "id,username", "access_token": token})
    return api_json(f"{API_BASE}/me?{query}")


def publish_post(
    token: str,
    user_id: str,
    text: str,
    image_url: str | None = None,
    reply_to_id: str | None = None,
) -> str:
    text = text.strip()
    if not text:
        raise RuntimeError("Post text is empty")

    container = {
        "access_token": token,
        "text": text,
        "media_type": "IMAGE" if image_url else "TEXT",
    }
    if image_url:
        container["image_url"] = image_url
    if reply_to_id:
        container["reply_to_id"] = reply_to_id

    created = api_json(f"{API_BASE}/{user_id}/threads", method="POST", data=container)
    creation_id = created.get("id")
    if not creation_id:
        raise RuntimeError(f"Threads API did not return a creation id: {created}")

    publish_url = f"{API_BASE}/{user_id}/threads_publish"
    publish_data = {"creation_id": creation_id, "access_token": token}
    delays = (2, 4, 8, 12)
    last_error = None
    for attempt, delay in enumerate(delays, start=1):
        time.sleep(delay)
        try:
            published = api_json(publish_url, method="POST", data=publish_data)
            post_id = published.get("id")
            if not post_id:
                raise RuntimeError(f"Threads API did not return a published post id: {published}")
            return str(post_id)
        except RuntimeError as exc:
            last_error = exc
            message = str(exc)
            transient_media = "Media Not Found" in message or '"error_subcode":4279009' in message
            if not transient_media or attempt == len(delays):
                raise
            print(f"Threads media container not ready; retrying publish ({attempt}/{len(delays)})...", file=sys.stderr)

    raise last_error or RuntimeError("Threads publish failed")


def parse_time(value: str) -> datetime:
    value = value.strip()
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    dt = datetime.fromisoformat(value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def load_json(path: Path, default):
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def save_json(path: Path, value) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def is_due(value: str | None, now: datetime) -> bool:
    if not value:
        return True
    return parse_time(value) <= now


def main() -> int:
    token = get_token()
    me = get_me(token)
    user_id = str(me.get("id", "")).strip()
    username = me.get("username", "unknown")
    if not user_id:
        raise RuntimeError(f"Could not resolve Threads user id: {me}")

    print(f"Authenticated as Threads @{username} ({user_id})")

    mode = os.getenv("THREADS_MODE", "queue").strip().lower()
    manual_text = os.getenv("THREADS_MANUAL_TEXT", "").strip()
    manual_image = os.getenv("THREADS_MANUAL_IMAGE_URL", "").strip() or None

    if mode == "check":
        print("Threads API authentication check passed.")
        return 0

    if manual_text:
        post_id = publish_post(token, user_id, manual_text, manual_image)
        print(f"Published manual Threads post: {post_id}")
        return 0

    posts = load_json(POSTS_FILE, [])
    replies = load_json(REPLIES_FILE, [])
    state = load_json(STATE_FILE, {"published_ids": [], "published_reply_ids": []})
    published_ids = set(state.get("published_ids", []))
    published_reply_ids = set(state.get("published_reply_ids", []))
    now = datetime.now(timezone.utc)
    published_any = False

    due_posts = []
    for post in posts:
        post_key = str(post.get("id", "")).strip()
        publish_at = str(post.get("publish_at", "")).strip()
        text = str(post.get("text", "")).strip()
        if not post_key or not publish_at or not text or post_key in published_ids:
            continue
        if parse_time(publish_at) <= now:
            due_posts.append(post)

    due_posts.sort(key=lambda p: parse_time(str(p["publish_at"])))

    for post in due_posts:
        post_key = str(post["id"])
        text = str(post["text"])
        image_url = str(post.get("image_url", "")).strip() or None
        post_id = publish_post(token, user_id, text, image_url)
        print(f"Published queued post {post_key}: {post_id}")
        published_ids.add(post_key)
        published_any = True

    due_replies = []
    for reply in replies:
        reply_key = str(reply.get("id", "")).strip()
        target_id = str(reply.get("reply_to_id", "")).strip()
        text = str(reply.get("text", "")).strip()
        send_at = str(reply.get("send_at", "")).strip() or None
        if not reply_key or not target_id or not text or reply_key in published_reply_ids:
            continue
        if is_due(send_at, now):
            due_replies.append(reply)

    due_replies.sort(
        key=lambda r: parse_time(str(r["send_at"])) if r.get("send_at") else now
    )

    for reply in due_replies:
        reply_key = str(reply["id"])
        target_id = str(reply["reply_to_id"])
        text = str(reply["text"])
        post_id = publish_post(token, user_id, text, reply_to_id=target_id)
        print(f"Published queued reply {reply_key}: {post_id}")
        published_reply_ids.add(reply_key)
        published_any = True

    if published_any:
        state["published_ids"] = sorted(published_ids)
        state["published_reply_ids"] = sorted(published_reply_ids)
        state["last_run_at"] = datetime.now(timezone.utc).isoformat()
        save_json(STATE_FILE, state)
    else:
        print("No due unpublished posts or replies.")

    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
