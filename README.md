# Telegram Channel to Markdown Exporter

This tool exports the full history of one or more Telegram channels to local **Markdown** files using the official Telegram API and a user account session (via Telethon). It is designed for building offline corpora that can later be analyzed by LLMs or other tools, without hitting context or memory limits.

## Features

- Export **one or more channels** (public or private, if your account has access).  
- Streams messages directly to `.md` files (no large in-memory buffers).  
- Chronological export (oldest → newest) with:
  - Message ID and timestamp  
  - Optional sender info  
  - Text content and URLs (when available)  
- Optional filters:
  - Date range (`FROM_DATE` / `TO_DATE`)  
  - Text-only vs include all message types  
- Safe to rerun:
  - Can append to existing files (or configurable behavior in the script).

***

## Prerequisites

- Python 3.9+  
- A Telegram account (phone number)  
- Telegram **API ID** and **API hash** from `my.telegram.org`[1]

### Getting Telegram API ID and hash

1. Open https://my.telegram.org in your browser and log in with your Telegram phone number.[2][3]
2. Enter the login code you receive in the Telegram app.[3]
3. Click **“API Development Tools”**.[4]
4. If it is your first time, create an app:
   - Fill in *App title*, *Short name*, choose a platform (e.g. “other”), add any description.  
   - For *App URL*, you can use your project website, GitHub repo, or even a placeholder like `https://example.com`; Telegram does not enforce anything specific here.[5][1]
5. After creating the app, you will see your **App api_id** and **App api_hash**.[1]

Keep these values secret; they are what the script uses to authenticate as your user.

***

## Installation

Clone the repository and install dependencies:

```bash
git clone <your-repo-url>.git
cd <your-repo-folder>

python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate

pip install -r requirements.txt
# or, if not using a requirements file:
pip install telethon python-dotenv
```

***

## Configuration

### 1. Environment variables (`.env`)

Create a `.env` file in the project root:

```env
API_ID=1234567
API_HASH=your_api_hash_here
PHONE_NUMBER=+1234567890
```

- `API_ID` / `API_HASH`: from `my.telegram.org` as described above.[1]
- `PHONE_NUMBER`: the phone number of the Telegram account you are using (with country code).

The script will read these values automatically if `python-dotenv` is installed.

### 2. Target channels and options

In `telegram_export.py` (or whatever your script is called), edit the configuration section near the top:

```python
TARGET_CHANNELS = [
    "some_public_channel",
    "another_channel",
    "https://t.me/joinchat/xxxxxxx"  # invite links are also supported if your account has access
]

FROM_DATE = None  # e.g. datetime(2023, 1, 1) or None
TO_DATE = None    # e.g. datetime(2024, 1, 1) or None
ONLY_TEXT = True  # True = skip non-text messages; False = include all
APPEND_MODE = True  # True = append to existing .md files, False = overwrite
```

***

## Usage

Run the exporter:

```bash
python telegram_export.py
```

On the first run:

- Telethon will open a session named something like `telegram_scraper.session`.  
- If not already authorized, you will be prompted to:
  - Confirm or enter your phone number (if not in `.env`).  
  - Enter the Telegram login code sent to your Telegram app.  
  - Enter your 2FA password if your account has one.[6]

After successful login, the script will:

1. Resolve each channel in `TARGET_CHANNELS`.  
2. Iterate through messages from oldest to newest using Telethon’s `iter_messages` with `reverse=True`.[6]
3. For each channel, create or append to a Markdown file named:

   ```text
   <channel_username>.md
   ```
   or, if there is no username, a safe slug derived from the channel title.

***

## Output format

Each message is written roughly as:

```markdown
### Message 12345 – 2024-01-02T15:04:05

From: Some User

This is the message text, with basic line breaks preserved.

- https://example.com/some-link
- https://t.me/c/123456/789  # optional permalink or media URL

---
```

- Messages are separated by `---`.  
- Encoding is always UTF-8 so files are safe to use with downstream tools.

***

## Typical workflow for LLM analysis

1. Run the exporter to produce `channel_a.md`, `channel_b.md`, etc.  
2. Use your preferred pipeline to:
   - Chunk the Markdown into manageable pieces, and  
   - Feed those chunks into RAG, summarization, or other analysis flows, without ever sending the entire channel history in a single prompt.

This separation keeps scraping/export fully independent from any LLM context limits.

***

## Security notes

- The script uses **your user account** via API, not a bot token.  
- Do **not** commit your `.env` file or any credentials to version control.  
- If you suspect your `API_HASH` has leaked, revoke the app in `my.telegram.org` and create a new one.[1]
