#!/usr/bin/env python3
"""
Telegram Channel to Markdown Exporter

Exports messages from Telegram channels to local Markdown files using the
Telethon library. Designed for building offline corpora for LLM analysis.

Installation:
    pip install telethon python-dotenv

    Or using the requirements file:
    pip install -r requirements.txt

Setup:
    1. Copy .env.example to .env
    2. Fill in your API_ID, API_HASH, and PHONE_NUMBER
    3. Edit TARGET_CHANNELS below with your desired channels
    4. Run: python telegram_export.py

On first run, you'll be prompted for the login code sent to your Telegram app.
If your account has 2FA enabled, you'll also be prompted for your password.
"""

import asyncio
import os
import re
from datetime import datetime, timezone
from typing import Optional

from dotenv import load_dotenv
from telethon import TelegramClient
from telethon.errors import (
    ChannelPrivateError,
    ChatAdminRequiredError,
    FloodWaitError,
    UsernameInvalidError,
    UsernameNotOccupiedError,
)
from telethon.tl.types import Channel, Chat, User

# =============================================================================
# CONFIGURATION - Edit these values as needed
# =============================================================================

# List of channels to export. Can be:
# - Channel usernames: "channelname" or "@channelname"
# - Channel links: "https://t.me/channelname"
# - Invite links: "https://t.me/joinchat/xxxxx" or "https://t.me/+xxxxx"
# - Channel IDs: -1001234567890
TARGET_CHANNELS = [
    -1002481698957,  # Channel from web.telegram.org (with -100 prefix for channels)
]

# Date range filter (set to None to include all messages)
# Example: datetime(2024, 1, 1, tzinfo=timezone.utc)
FROM_DATE: Optional[datetime] = None
TO_DATE: Optional[datetime] = None

# If True, skip messages without text content (e.g., media-only messages)
ONLY_TEXT = False

# If True, append to existing files; if False, overwrite
APPEND_MODE = True

# Print progress every N messages
PROGRESS_INTERVAL = 100

# Output directory for Markdown files
OUTPUT_DIR = "output"

# Session file name (stores login state)
SESSION_NAME = "telegram_scraper"


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================


def sanitize_filename(name: str) -> str:
    """
    Convert a string to a safe filename by removing/replacing invalid characters.
    """
    # Replace spaces and common separators with underscores
    name = re.sub(r"[\s\-]+", "_", name)
    # Remove characters that are invalid in filenames
    name = re.sub(r'[<>:"/\\|?*]', "", name)
    # Remove any non-ASCII characters for maximum compatibility
    name = re.sub(r"[^\x00-\x7F]+", "", name)
    # Collapse multiple underscores
    name = re.sub(r"_+", "_", name)
    # Strip leading/trailing underscores and dots
    name = name.strip("_.")
    # Ensure we have something left
    return name if name else "unnamed_channel"


def get_sender_name(sender) -> str:
    """
    Extract a display name from a sender object.
    """
    if sender is None:
        return "Unknown"
    if isinstance(sender, User):
        parts = []
        if sender.first_name:
            parts.append(sender.first_name)
        if sender.last_name:
            parts.append(sender.last_name)
        if parts:
            name = " ".join(parts)
            if sender.username:
                name += f" (@{sender.username})"
            return name
        if sender.username:
            return f"@{sender.username}"
        return f"User {sender.id}"
    if isinstance(sender, (Channel, Chat)):
        return sender.title or f"Channel {sender.id}"
    return str(sender.id) if hasattr(sender, "id") else "Unknown"


def extract_urls(message) -> list[str]:
    """
    Extract URLs from message text and entities.
    """
    urls = []

    # Extract URLs from message entities (links, text URLs, etc.)
    if message.entities:
        from telethon.tl.types import (
            MessageEntityTextUrl,
            MessageEntityUrl,
        )

        for entity in message.entities:
            if isinstance(entity, MessageEntityUrl) and message.text:
                url = message.text[entity.offset : entity.offset + entity.length]
                if url not in urls:
                    urls.append(url)
            elif isinstance(entity, MessageEntityTextUrl):
                if entity.url and entity.url not in urls:
                    urls.append(entity.url)

    # Also check for URLs in the raw text using regex
    if message.text:
        url_pattern = r"https?://[^\s<>\"')\]]+"
        for match in re.finditer(url_pattern, message.text):
            url = match.group(0)
            if url not in urls:
                urls.append(url)

    return urls


def format_message_to_markdown(message, sender_name: str) -> str:
    """
    Format a Telegram message as a Markdown block.
    """
    # Format the date in ISO format
    date_str = message.date.strftime("%Y-%m-%dT%H:%M:%S")
    if message.date.tzinfo:
        date_str += "Z" if message.date.utcoffset().total_seconds() == 0 else ""

    lines = []
    lines.append(f"### Message {message.id} \u2013 {date_str}")
    lines.append("")

    # Sender info
    lines.append(f"From: {sender_name}")
    lines.append("")

    # Message text (preserve line breaks)
    if message.text:
        lines.append(message.text)
    else:
        lines.append("*(No text content)*")
    lines.append("")

    # URLs
    urls = extract_urls(message)
    if urls:
        for url in urls:
            lines.append(f"- {url}")
        lines.append("")

    # Separator
    lines.append("---")
    lines.append("")

    return "\n".join(lines)


async def get_entity_info(client: TelegramClient, channel) -> tuple[str, str]:
    """
    Get the display name and filename for a channel entity.
    Returns (display_name, filename).
    """
    entity = await client.get_entity(channel)

    if hasattr(entity, "username") and entity.username:
        display_name = f"@{entity.username}"
        filename = entity.username
    elif hasattr(entity, "title") and entity.title:
        display_name = entity.title
        filename = sanitize_filename(entity.title)
    else:
        display_name = f"Channel {entity.id}"
        filename = f"channel_{entity.id}"

    return display_name, filename, entity


async def export_channel(
    client: TelegramClient,
    channel,
    output_dir: str,
    from_date: Optional[datetime],
    to_date: Optional[datetime],
    only_text: bool,
    append_mode: bool,
    progress_interval: int,
) -> None:
    """
    Export all messages from a single channel to a Markdown file.
    """
    # Resolve the channel entity
    display_name, filename, entity = await get_entity_info(client, channel)
    output_path = os.path.join(output_dir, f"{filename}.md")

    print(f"\nExporting channel: {display_name}")
    print(f"  Output file: {output_path}")

    # Open file in appropriate mode
    mode = "a" if append_mode else "w"
    message_count = 0
    skipped_count = 0

    with open(output_path, mode, encoding="utf-8") as f:
        # If not appending, write a header
        if not append_mode:
            f.write(f"# Messages from {display_name}\n\n")
            f.write(f"Exported on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")
            f.write("---\n\n")

        # Iterate through messages (reverse=True for chronological order)
        async for message in client.iter_messages(entity, reverse=True):
            # Date range filter
            if from_date and message.date < from_date:
                continue
            if to_date and message.date > to_date:
                continue

            # Text-only filter
            if only_text and not message.text:
                skipped_count += 1
                continue

            # Get sender information
            sender = await message.get_sender()
            sender_name = get_sender_name(sender)

            # Format and write the message
            markdown_block = format_message_to_markdown(message, sender_name)
            f.write(markdown_block)
            f.flush()  # Ensure it's written immediately

            message_count += 1

            # Progress update
            if message_count % progress_interval == 0:
                print(f"  Processed {message_count} messages...")

    print(f"  Completed: {message_count} messages exported")
    if skipped_count > 0:
        print(f"  Skipped: {skipped_count} non-text messages")


async def main() -> None:
    """
    Main entry point for the Telegram exporter.
    """
    # Load environment variables from .env file
    load_dotenv()

    # Get credentials
    api_id = os.getenv("API_ID")
    api_hash = os.getenv("API_HASH")
    phone_number = os.getenv("PHONE_NUMBER")

    # Validate credentials
    if not api_id or not api_hash:
        print("Error: API_ID and API_HASH must be set in .env file")
        print("Copy .env.example to .env and fill in your credentials from my.telegram.org")
        return

    try:
        api_id = int(api_id)
    except ValueError:
        print("Error: API_ID must be a number")
        return

    # Check for target channels
    if not TARGET_CHANNELS:
        print("Error: No channels specified in TARGET_CHANNELS")
        print("Edit the TARGET_CHANNELS list at the top of this script")
        return

    # Create output directory if it doesn't exist
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    # Create the Telegram client
    client = TelegramClient(SESSION_NAME, api_id, api_hash)

    print("Telegram Channel Exporter")
    print("=" * 40)

    try:
        # Start the client (handles login automatically)
        await client.start(phone=phone_number)
        print("Successfully connected to Telegram")

        # Get current user info
        me = await client.get_me()
        print(f"Logged in as: {me.first_name} (@{me.username or me.id})")

        # Process each channel
        successful = 0
        failed = 0

        for channel in TARGET_CHANNELS:
            try:
                await export_channel(
                    client=client,
                    channel=channel,
                    output_dir=OUTPUT_DIR,
                    from_date=FROM_DATE,
                    to_date=TO_DATE,
                    only_text=ONLY_TEXT,
                    append_mode=APPEND_MODE,
                    progress_interval=PROGRESS_INTERVAL,
                )
                successful += 1

            except (ChannelPrivateError, ChatAdminRequiredError):
                print(f"\nError: No access to channel '{channel}'")
                print("  Make sure your account is a member of this channel")
                failed += 1

            except (UsernameNotOccupiedError, UsernameInvalidError):
                print(f"\nError: Channel not found: '{channel}'")
                print("  Check the channel username or link")
                failed += 1

            except FloodWaitError as e:
                print(f"\nError: Rate limited by Telegram. Wait {e.seconds} seconds")
                print("  The script will need to be rerun after the wait period")
                failed += 1

            except Exception as e:
                print(f"\nError exporting '{channel}': {type(e).__name__}: {e}")
                failed += 1

        # Summary
        print("\n" + "=" * 40)
        print("Export Complete")
        print(f"  Successful: {successful} channel(s)")
        if failed > 0:
            print(f"  Failed: {failed} channel(s)")
        print(f"  Output directory: {os.path.abspath(OUTPUT_DIR)}")

    finally:
        await client.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
