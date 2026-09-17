# Telegram Financial Harvester

Two small Python tools built on [Telethon](https://docs.telethon.dev/) that turn Telegram channels into machine-readable data:

| Script | What it does |
|--------|--------------|
| `telegram_export.py` | Exports the full history of one or more channels to Markdown files (one file per channel) for offline analysis or RAG. |
| `pipeline.py` | Pulls new messages from a channel, asks Claude to extract politician stock-trading signals, and POSTs them to a webhook. Remembers where it stopped between runs. |

Both log in with **your Telegram user account** (API ID and hash from my.telegram.org), not a bot token, so private channels you are a member of work too.

## Requirements

- Python 3.10+
- A Telegram account and API credentials from [my.telegram.org](https://my.telegram.org) (API Development Tools, create an app, copy `api_id` and `api_hash`)
- For `pipeline.py`: an Anthropic API key and a checklister webhook

## Install

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # then fill it in
```

## Configuration (`.env`)

| Variable | Used by | Meaning |
|----------|---------|---------|
| `API_ID`, `API_HASH` | both | Telegram API credentials |
| `PHONE_NUMBER` | export | Account phone number with country code |
| `TARGET_CHANNELS` | export | Comma separated usernames, `t.me` links or numeric IDs (`-100...`) |
| `TARGET_CHANNEL` | pipeline | Numeric channel ID to harvest (override with `--channel`) |
| `ANTHROPIC_API_KEY` | pipeline | Claude API key |
| `CLAUDE_MODEL` | pipeline | Optional; default `claude-haiku-4-5-20251001` |
| `CHECKLISTER_WEBHOOK_URL`, `CHECKLISTER_API_KEY` | pipeline | Webhook target and its key (not needed with `--dry-run`) |

Other exporter options (`FROM_DATE`, `TO_DATE`, `ONLY_TEXT`, `APPEND_MODE`, `OUTPUT_DIR`) are constants at the top of `telegram_export.py`.

## Exporting channels

```bash
python telegram_export.py
```

First run: enter the login code Telegram sends you (and your 2FA password if set). The session is saved as `telegram_scraper.session` so later runs do not prompt.

Messages are streamed oldest to newest into `output/<channel>.md`:

```markdown
### Message 12345 - 2024-01-02T15:04:05Z

From: Some User

Message text with line breaks preserved.

- https://example.com/some-link

---
```

## Running the signal pipeline

```bash
python pipeline.py --dry-run --verbose   # parse only, print what would be sent
python pipeline.py                       # incremental: new messages since last run
python pipeline.py --full --limit 50     # reprocess from the start, first 50 messages
python pipeline.py --channel -1001234567890
```

Flow: fetch messages after the last seen ID, send each to Claude with the prompt in `signal_parser.py`, keep the ones that validate (`ticker`, `BUY`/`SELL`, date), POST them to the webhook (`409` counts as a duplicate), then store the highest message ID in `pipeline_state.json`.

## Development

```bash
pip install -r requirements-dev.txt
ruff check .
pytest
```

Tests cover JSON extraction, signal validation, model selection, state persistence and channel-list parsing with a fake Anthropic client (no network). CI runs ruff and pytest on every push and pull request.

## Security

- `.env`, `*.session` and `pipeline_state.json` are git-ignored. Never commit them.
- If your `API_HASH` leaks, revoke the app at my.telegram.org and create a new one.
- Message text is sent to Anthropic for parsing; the first 500 characters are forwarded to the webhook as `raw_message`.
