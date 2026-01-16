#!/usr/bin/env python3
"""
Telegram Signal Pipeline

Main orchestration script that:
1. Pulls new messages from Telegram channel
2. Parses them using Claude API to extract trading signals
3. Sends parsed signals to the checklister webhook

Usage:
  python pipeline.py                    # Process new messages since last run
  python pipeline.py --full             # Reprocess all messages (ignores state)
  python pipeline.py --dry-run          # Parse but don't send to webhook
  python pipeline.py --verbose          # Print detailed progress
  python pipeline.py --limit 50         # Limit to N messages
"""

import argparse
import asyncio
import os
import sys
from datetime import datetime

import anthropic
from dotenv import load_dotenv
from telethon import TelegramClient
from telethon.errors import ChannelPrivateError

from signal_parser import parse_message, ParsedSignal
from state import get_last_message_id, set_last_message_id, increment_processed_count
from webhook_client import WebhookClient

# =============================================================================
# CONFIGURATION
# =============================================================================

# Target Telegram channel (from telegram_export.py)
TARGET_CHANNEL = -1002481698957  # Your channel ID

# Session file for Telegram login
SESSION_NAME = "telegram_scraper"

# =============================================================================
# MAIN PIPELINE
# =============================================================================


async def run_pipeline(
    telegram_client: TelegramClient,
    anthropic_client: anthropic.Anthropic,
    webhook_client: WebhookClient | None,
    channel_id: int,
    full_scan: bool = False,
    dry_run: bool = False,
    verbose: bool = False,
    limit: int | None = None,
) -> dict:
    """
    Run the signal extraction and submission pipeline.

    Args:
        telegram_client: Connected Telethon client
        anthropic_client: Anthropic API client
        webhook_client: Webhook client (None if dry_run)
        channel_id: Telegram channel ID to process
        full_scan: If True, process all messages ignoring state
        dry_run: If True, parse but don't send to webhook
        verbose: Print detailed progress
        limit: Maximum number of messages to process

    Returns:
        Summary dict with counts
    """
    # Get starting point
    if full_scan:
        min_id = 0
        if verbose:
            print("Full scan mode: processing all messages")
    else:
        min_id = get_last_message_id(channel_id)
        if verbose:
            print(f"Incremental mode: starting from message ID {min_id}")

    # Get channel entity
    try:
        entity = await telegram_client.get_entity(channel_id)
        if verbose:
            channel_name = getattr(entity, "title", str(channel_id))
            print(f"Processing channel: {channel_name}")
    except ChannelPrivateError:
        print(f"Error: No access to channel {channel_id}")
        return {"error": "No access to channel"}

    # Collect messages
    messages_to_parse = []
    max_message_id = min_id

    if verbose:
        print("Fetching messages...")

    count = 0
    async for message in telegram_client.iter_messages(entity, min_id=min_id):
        if not message.text:
            continue

        count += 1
        if limit and count > limit:
            break

        messages_to_parse.append(
            (message.id, message.text, message.date.isoformat())
        )
        max_message_id = max(max_message_id, message.id)

        if verbose and count % 50 == 0:
            print(f"  Fetched {count} messages...")

    if verbose:
        print(f"Found {len(messages_to_parse)} messages to process")

    if not messages_to_parse:
        return {
            "total_messages": 0,
            "signals_found": 0,
            "signals_sent": 0,
            "duplicates": 0,
            "errors": 0,
        }

    # Parse messages with Claude
    if verbose:
        print("\nParsing messages with Claude API...")

    signals: list[ParsedSignal] = []
    for i, (msg_id, text, timestamp) in enumerate(messages_to_parse):
        if verbose and (i + 1) % 10 == 0:
            print(f"  Parsed {i + 1}/{len(messages_to_parse)}...")

        signal = parse_message(anthropic_client, text, timestamp)
        if signal:
            signals.append(signal)
            if verbose:
                print(f"    Found signal: {signal.ticker} ({signal.transaction_type})")

    if verbose:
        print(f"Found {len(signals)} valid signals from {len(messages_to_parse)} messages")

    # Send signals to webhook
    results = {
        "total_messages": len(messages_to_parse),
        "signals_found": len(signals),
        "signals_sent": 0,
        "duplicates": 0,
        "errors": 0,
    }

    if signals and not dry_run and webhook_client:
        if verbose:
            print("\nSending signals to webhook...")

        webhook_results = webhook_client.send_signals_batch(signals, verbose=verbose)
        results["signals_sent"] = webhook_results["success"]
        results["duplicates"] = webhook_results["duplicates"]
        results["errors"] = webhook_results["failed"]

        # Update processed count
        increment_processed_count(webhook_results["success"])
    elif dry_run:
        if verbose:
            print("\nDry run mode: skipping webhook submission")
            for signal in signals:
                print(f"  Would send: {signal.ticker} - {signal.politician_name} - "
                      f"{signal.transaction_type} {signal.amount_range or 'N/A'} "
                      f"on {signal.signal_date}")

    # Update state with the highest message ID processed
    if not full_scan and max_message_id > min_id:
        set_last_message_id(channel_id, max_message_id)
        if verbose:
            print(f"\nUpdated state: last_message_id = {max_message_id}")

    return results


async def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Process Telegram messages and send signals to checklister"
    )
    parser.add_argument(
        "--full",
        action="store_true",
        help="Process all messages (ignore state)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Parse messages but don't send to webhook",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Print detailed progress",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Limit number of messages to process",
    )
    parser.add_argument(
        "--channel",
        type=int,
        default=TARGET_CHANNEL,
        help=f"Telegram channel ID (default: {TARGET_CHANNEL})",
    )
    args = parser.parse_args()

    # Load environment variables
    load_dotenv()

    # Validate configuration
    api_id = os.getenv("API_ID")
    api_hash = os.getenv("API_HASH")
    anthropic_api_key = os.getenv("ANTHROPIC_API_KEY")
    webhook_url = os.getenv("CHECKLISTER_WEBHOOK_URL")
    webhook_api_key = os.getenv("CHECKLISTER_API_KEY")

    if not api_id or not api_hash:
        print("Error: API_ID and API_HASH must be set in .env")
        sys.exit(1)

    if not anthropic_api_key:
        print("Error: ANTHROPIC_API_KEY must be set in .env")
        sys.exit(1)

    if not args.dry_run and (not webhook_url or not webhook_api_key):
        print("Error: CHECKLISTER_WEBHOOK_URL and CHECKLISTER_API_KEY must be set in .env")
        print("Use --dry-run to test parsing without sending to webhook")
        sys.exit(1)

    print("=" * 60)
    print("Telegram Signal Pipeline")
    print("=" * 60)
    print(f"Started at: {datetime.now().isoformat()}")
    print(f"Mode: {'DRY RUN' if args.dry_run else 'LIVE'}")
    print(f"Scan: {'FULL' if args.full else 'INCREMENTAL'}")
    if args.limit:
        print(f"Limit: {args.limit} messages")
    print()

    # Initialize clients
    telegram_client = TelegramClient(SESSION_NAME, int(api_id), api_hash)
    anthropic_client = anthropic.Anthropic(api_key=anthropic_api_key)
    webhook_client = (
        WebhookClient(webhook_url, webhook_api_key)
        if not args.dry_run and webhook_url and webhook_api_key
        else None
    )

    try:
        # Connect to Telegram
        await telegram_client.start()
        me = await telegram_client.get_me()
        print(f"Connected as: {me.first_name} (@{me.username or me.id})")
        print()

        # Run pipeline
        results = await run_pipeline(
            telegram_client=telegram_client,
            anthropic_client=anthropic_client,
            webhook_client=webhook_client,
            channel_id=args.channel,
            full_scan=args.full,
            dry_run=args.dry_run,
            verbose=args.verbose,
            limit=args.limit,
        )

        # Print summary
        print()
        print("=" * 60)
        print("Summary")
        print("=" * 60)
        print(f"Total messages processed: {results.get('total_messages', 0)}")
        print(f"Signals found: {results.get('signals_found', 0)}")
        if not args.dry_run:
            print(f"Signals sent successfully: {results.get('signals_sent', 0)}")
            print(f"Duplicates skipped: {results.get('duplicates', 0)}")
            print(f"Errors: {results.get('errors', 0)}")
        print(f"Completed at: {datetime.now().isoformat()}")

    finally:
        await telegram_client.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
