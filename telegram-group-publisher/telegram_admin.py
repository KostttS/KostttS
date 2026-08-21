#!/usr/bin/env python3
"""Audit and improve the configured Telegram group through the Bot API."""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any, Callable
from zoneinfo import ZoneInfo

from publisher import ENV_PATH, ROOT, encode_multipart, load_env_file, load_json


AUDIT_PATH = ROOT / "chat_audit.json"
STATE_PATH = ROOT / "state.json"
AVATAR_PATH = ROOT / "assets" / "group-avatar.jpg"
TIMEZONE = ZoneInfo("Asia/Jerusalem")
NEW_TITLE = "Мобильные приложения для бизнеса | FlutterFlow"
NEW_DESCRIPTION = (
    "Мобильные приложения для бизнеса: FlutterFlow, Firebase/Supabase, API, "
    "платежи, карты, push, App Store/Google Play. Кейсы и практические разборы. "
    "Проект: oxta.ha@gmail.com | Портфолио: behance.net/24512dab | github.com/KostttS"
)


class TelegramAdminError(RuntimeError):
    pass


def api_call(token: str, method: str, fields: dict[str, Any]) -> Any:
    encoded: dict[str, str] = {}
    for key, value in fields.items():
        if isinstance(value, bool):
            encoded[key] = "true" if value else "false"
        elif isinstance(value, (dict, list)):
            encoded[key] = json.dumps(value, ensure_ascii=False)
        else:
            encoded[key] = str(value)
    request = urllib.request.Request(
        f"https://api.telegram.org/bot{token}/{method}",
        data=urllib.parse.urlencode(encoded).encode("utf-8"),
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise TelegramAdminError(f"HTTP {exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise TelegramAdminError(f"connection failed: {exc.reason}") from exc
    if not payload.get("ok"):
        raise TelegramAdminError(str(payload))
    return payload.get("result", True)


def set_chat_photo(token: str, chat_id: str) -> Any:
    if not AVATAR_PATH.is_file():
        raise TelegramAdminError(f"avatar file is missing: {AVATAR_PATH}")
    body, content_type = encode_multipart(
        {"chat_id": chat_id}, "photo", AVATAR_PATH
    )
    request = urllib.request.Request(
        f"https://api.telegram.org/bot{token}/setChatPhoto",
        data=body,
        headers={"Content-Type": content_type},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise TelegramAdminError(f"HTTP {exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise TelegramAdminError(f"connection failed: {exc.reason}") from exc
    if not payload.get("ok"):
        raise TelegramAdminError(str(payload))
    return payload.get("result", True)


def collect_audit(token: str, chat_id: str) -> dict[str, Any]:
    me = api_call(token, "getMe", {})
    chat = api_call(token, "getChat", {"chat_id": chat_id})
    member_count = api_call(token, "getChatMemberCount", {"chat_id": chat_id})
    bot_member = api_call(
        token,
        "getChatMember",
        {"chat_id": chat_id, "user_id": me["id"]},
    )
    capability_names = [
        "can_manage_chat",
        "can_change_info",
        "can_delete_messages",
        "can_restrict_members",
        "can_invite_users",
        "can_pin_messages",
        "can_manage_topics",
    ]
    state = load_json(STATE_PATH, {"history": [], "published_ids": []})
    history = state.get("history", [])
    latest_message_id = history[-1].get("message_id") if history else None
    return {
        "audited_at": datetime.now(TIMEZONE).isoformat(),
        "chat": {
            "username": chat.get("username"),
            "title": chat.get("title"),
            "description": chat.get("description"),
            "member_count": member_count,
            "permissions": chat.get("permissions"),
        },
        "bot": {
            "username": me.get("username"),
            "status": bot_member.get("status"),
            "capabilities": {
                name: bot_member.get(name)
                for name in capability_names
                if name in bot_member
            },
        },
        "publishing": {
            "published_count": len(state.get("published_ids", [])),
            "latest_message_id": latest_message_id,
        },
    }


def apply_improvements(token: str, chat_id: str) -> list[dict[str, Any]]:
    actions: list[dict[str, Any]] = []

    def attempt(name: str, action: Callable[[], Any]) -> None:
        try:
            action()
            actions.append({"action": name, "ok": True})
        except TelegramAdminError as exc:
            actions.append({"action": name, "ok": False, "error": str(exc)})

    attempt(
        "set_title",
        lambda: api_call(
            token, "setChatTitle", {"chat_id": chat_id, "title": NEW_TITLE}
        ),
    )
    attempt(
        "set_description",
        lambda: api_call(
            token,
            "setChatDescription",
            {"chat_id": chat_id, "description": NEW_DESCRIPTION},
        ),
    )
    permissions = {
        "can_send_messages": False,
        "can_send_audios": False,
        "can_send_documents": False,
        "can_send_photos": False,
        "can_send_videos": False,
        "can_send_video_notes": False,
        "can_send_voice_notes": False,
        "can_send_polls": False,
        "can_send_other_messages": False,
        "can_add_web_page_previews": False,
        "can_change_info": False,
        "can_invite_users": True,
        "can_pin_messages": False,
        "can_manage_topics": False,
    }
    attempt(
        "restrict_member_posting",
        lambda: api_call(
            token,
            "setChatPermissions",
            {
                "chat_id": chat_id,
                "permissions": permissions,
                "use_independent_chat_permissions": True,
            },
        ),
    )
    attempt("set_avatar", lambda: set_chat_photo(token, chat_id))
    return actions


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="Apply safe improvements.")
    args = parser.parse_args()
    load_env_file(ENV_PATH)
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "@mobileapplication2026").strip()
    if not token:
        raise TelegramAdminError("TELEGRAM_BOT_TOKEN is missing")

    before = collect_audit(token, chat_id)
    actions = apply_improvements(token, chat_id) if args.apply else []
    after = collect_audit(token, chat_id)
    payload = {"before": before, "actions": actions, "after": after}
    AUDIT_PATH.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except TelegramAdminError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
