#!/usr/bin/env python3
"""Publish the next queued Telegram post safely.

Uses only the Python standard library. The bot token is read from .env or the
process environment and is never stored in the queue or state files.
"""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import mimetypes
import os
import secrets
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parent
QUEUE_PATH = ROOT / "posts.json"
STATE_PATH = ROOT / "state.json"
LOCK_PATH = ROOT / ".publisher.lock"
ENV_PATH = ROOT / ".env"
TIMEZONE = ZoneInfo("Asia/Jerusalem")
PUBLISH_WEEKDAYS = {0, 1, 2, 3, 4, 6}  # Sunday through Friday; Saturday off
PUBLISH_HOUR = 15  # Asia/Jerusalem; workflow runs at both possible UTC offsets
MAX_CAPTION_LENGTH = 1024


class PublisherError(RuntimeError):
    pass


def load_env_file(path: Path) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def save_json_atomic(path: Path, value: Any) -> None:
    temp_path = path.with_suffix(path.suffix + ".tmp")
    temp_path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    os.replace(temp_path, path)


def validate_queue(posts: list[dict[str, Any]]) -> None:
    seen_ids: set[str] = set()
    if not posts:
        raise PublisherError("The post queue is empty.")

    for index, post in enumerate(posts, start=1):
        post_id = str(post.get("id", "")).strip()
        caption = str(post.get("caption", "")).strip()
        image_name = str(post.get("image", "")).strip()

        if not post_id or post_id in seen_ids:
            raise PublisherError(f"Invalid or duplicate id at queue item {index}.")
        if not caption:
            raise PublisherError(f"Missing caption for {post_id}.")
        if len(caption) > MAX_CAPTION_LENGTH:
            raise PublisherError(
                f"Caption {post_id} is {len(caption)} characters; "
                f"Telegram allows {MAX_CAPTION_LENGTH}."
            )
        image_path = ROOT / image_name
        if not image_path.is_file():
            raise PublisherError(f"Image not found for {post_id}: {image_path}")
        seen_ids.add(post_id)


def next_post(
    posts: list[dict[str, Any]], state: dict[str, Any]
) -> dict[str, Any] | None:
    published_ids = set(state.get("published_ids", []))
    for post in posts:
        if post["id"] not in published_ids:
            return post
    return None


def encode_multipart(fields: dict[str, str], file_field: str, file_path: Path) -> tuple[bytes, str]:
    boundary = "----TelegramPublisher" + secrets.token_hex(16)
    chunks: list[bytes] = []

    for name, value in fields.items():
        chunks.extend(
            [
                f"--{boundary}\r\n".encode(),
                f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode(),
                value.encode("utf-8"),
                b"\r\n",
            ]
        )

    mime_type = mimetypes.guess_type(file_path.name)[0] or "application/octet-stream"
    chunks.extend(
        [
            f"--{boundary}\r\n".encode(),
            (
                f'Content-Disposition: form-data; name="{file_field}"; '
                f'filename="{file_path.name}"\r\n'
            ).encode(),
            f"Content-Type: {mime_type}\r\n\r\n".encode(),
            file_path.read_bytes(),
            b"\r\n",
            f"--{boundary}--\r\n".encode(),
        ]
    )
    return b"".join(chunks), f"multipart/form-data; boundary={boundary}"


def telegram_send_photo(
    token: str, chat_id: str, photo_path: Path, caption: str
) -> dict[str, Any]:
    body, content_type = encode_multipart(
        {"chat_id": chat_id, "caption": caption}, "photo", photo_path
    )
    request = urllib.request.Request(
        f"https://api.telegram.org/bot{token}/sendPhoto",
        data=body,
        headers={"Content-Type": content_type, "User-Agent": "TelegramGroupPublisher/1.0"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise PublisherError(f"Telegram HTTP {exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise PublisherError(f"Telegram connection failed: {exc.reason}") from exc

    if not payload.get("ok"):
        raise PublisherError(f"Telegram rejected the post: {payload}")
    return payload["result"]


def telegram_call(
    token: str, method: str, fields: dict[str, Any]
) -> dict[str, Any] | bool:
    encoded_fields: dict[str, str] = {}
    for key, value in fields.items():
        if isinstance(value, bool):
            encoded_fields[key] = "true" if value else "false"
        elif isinstance(value, (dict, list)):
            encoded_fields[key] = json.dumps(value, ensure_ascii=False)
        else:
            encoded_fields[key] = str(value)

    request = urllib.request.Request(
        f"https://api.telegram.org/bot{token}/{method}",
        data=urllib.parse.urlencode(encoded_fields).encode("utf-8"),
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "User-Agent": "TelegramGroupPublisher/1.0",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise PublisherError(f"Telegram HTTP {exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise PublisherError(f"Telegram connection failed: {exc.reason}") from exc

    if not payload.get("ok"):
        raise PublisherError(f"Telegram rejected {method}: {payload}")
    return payload.get("result", True)


def should_publish_scheduled(state: dict[str, Any], now: datetime) -> tuple[bool, str]:
    today = now.date().isoformat()
    if now.weekday() not in PUBLISH_WEEKDAYS:
        return False, "Today is not a publishing day."
    if now.hour != PUBLISH_HOUR:
        return False, f"The local publishing hour is {PUBLISH_HOUR:02d}:00."
    if state.get("last_publish_date") == today:
        return False, "A post has already been published today."
    return True, "Scheduled publishing window is open."


def publish(dry_run: bool, scheduled: bool) -> int:
    load_env_file(ENV_PATH)
    posts = load_json(QUEUE_PATH, [])
    state = load_json(STATE_PATH, {"published_ids": [], "history": []})
    validate_queue(posts)

    now = datetime.now(TIMEZONE)
    if scheduled:
        allowed, reason = should_publish_scheduled(state, now)
        if not allowed:
            print(reason)
            return 0

    post = next_post(posts, state)
    if post is None:
        print("No unpublished posts remain in the queue.")
        return 0

    image_path = ROOT / post["image"]
    print(
        f"Next post: {post['id']} | caption={len(post['caption'])} chars | "
        f"image={image_path.name}"
    )
    if dry_run:
        print("Dry run completed; nothing was sent.")
        return 0

    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "@mobileapplication2026").strip()
    if not token:
        raise PublisherError(
            "TELEGRAM_BOT_TOKEN is missing. Put the regenerated token in .env."
        )

    message = telegram_send_photo(token, chat_id, image_path, post["caption"])
    message_id = message.get("message_id")
    actual_chat = message.get("chat", {})
    actual_username = actual_chat.get("username")
    if chat_id.startswith("@") and actual_username:
        if actual_username.casefold() != chat_id[1:].casefold():
            raise PublisherError(
                f"Telegram returned an unexpected chat @{actual_username}; state not advanced."
            )

    pinned = False
    pin_error: str | None = None
    unpinned_message_id: int | None = None
    unpin_error: str | None = None
    if post.get("pin") and message_id is not None:
        try:
            telegram_call(
                token,
                "pinChatMessage",
                {
                    "chat_id": chat_id,
                    "message_id": message_id,
                    "disable_notification": True,
                },
            )
            pinned = True
        except PublisherError as exc:
            pin_error = str(exc)
            print(f"WARNING: post sent, but pinning failed: {exc}", file=sys.stderr)

        previous_pin = post.get("replace_pin_message_id")
        if pinned and previous_pin is not None:
            try:
                previous_pin_id = int(previous_pin)
                telegram_call(
                    token,
                    "unpinChatMessage",
                    {"chat_id": chat_id, "message_id": previous_pin_id},
                )
                unpinned_message_id = previous_pin_id
            except (PublisherError, TypeError, ValueError) as exc:
                unpin_error = str(exc)
                print(
                    f"WARNING: new post pinned, but previous pin was not removed: {exc}",
                    file=sys.stderr,
                )

    published_ids = list(state.get("published_ids", []))
    published_ids.append(post["id"])
    history = list(state.get("history", []))
    history.append(
        {
            "post_id": post["id"],
            "message_id": message_id,
            "chat_id": actual_chat.get("id"),
            "chat_username": actual_username,
            "published_at": now.isoformat(),
            "caption_sha256": hashlib.sha256(post["caption"].encode("utf-8")).hexdigest(),
            "pinned": pinned,
            "pin_error": pin_error,
            "unpinned_message_id": unpinned_message_id,
            "unpin_error": unpin_error,
        }
    )
    state.update(
        {
            "published_ids": published_ids,
            "history": history,
            "last_publish_date": now.date().isoformat(),
        }
    )
    save_json_atomic(STATE_PATH, state)
    print(f"Published {post['id']} successfully as Telegram message {message_id}.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true", help="Validate without posting.")
    mode.add_argument("--publish-now", action="store_true", help="Publish the next queued post.")
    mode.add_argument(
        "--scheduled",
        action="store_true",
        help="Publish at 15:00 Asia/Jerusalem on Sun-Fri, once per day.",
    )
    args = parser.parse_args()

    LOCK_PATH.touch(exist_ok=True)
    with LOCK_PATH.open("r+") as lock_file:
        try:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print("Another publisher process is already running.")
            return 0
        return publish(dry_run=args.dry_run, scheduled=args.scheduled)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except PublisherError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
