# Telegram group publisher

Publishes prepared image posts to `@mobileapplication2026` through the official
Telegram Bot API. It runs entirely in a private GitHub repository; no hosting or
always-on server is required.

## One-time setup

1. In `@BotFather`, run `/token`, select `@mobileapplication2026bot`, and
   regenerate the token that was visible in the screenshot.
2. In this GitHub repository, open **Settings → Secrets and variables → Actions**.
3. Create a repository secret named `TELEGRAM_BOT_TOKEN` and paste the new token
   there. Never put the token in a file, issue, commit, or chat.
4. Open **Actions → Telegram group publisher → Run workflow** to publish the
   first queued post immediately.

After that, GitHub Actions runs automatically on Monday, Wednesday, Friday and
Sunday at 15:00 in `Asia/Jerusalem`. Two UTC triggers cover both Israeli winter
and summer time; `publisher.py` accepts only the correct local-hour run and
prevents a second post on the same local date.

The workflow commits only `state.json` after a successful Telegram response.
The stored history contains the Telegram message ID, timestamp and content hash,
so a failed or repeated workflow cannot silently advance the queue.

## Useful commands

```bash
# Validate queue and image files
python3 publisher.py --dry-run

# Publish the next queued post immediately
python3 publisher.py --publish-now

# Run the normal local-time schedule check
python3 publisher.py --scheduled
```

Published message IDs, timestamps and content hashes are stored in `state.json`
to prevent accidental duplicates.
