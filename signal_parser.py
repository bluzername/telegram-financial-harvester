"""
Signal Parser - Uses Claude API to extract structured signals from raw Telegram messages.

Parses natural language politician trading disclosures into structured data
that can be sent to the checklister webhook.
"""

import json
import re
from dataclasses import dataclass
from typing import Optional

import anthropic


@dataclass
class ParsedSignal:
    """Structured representation of a politician trading signal."""

    ticker: str
    politician_name: Optional[str]
    transaction_type: str  # 'BUY' or 'SELL'
    amount_range: Optional[str]
    signal_date: str  # ISO format YYYY-MM-DD
    confidence: float  # 0-1, how confident the parser is
    raw_message: str


# Prompt for Claude to parse politician trading signals
PARSE_PROMPT = """You are parsing politician stock trading signals from a Telegram channel.

Extract the following from this message:
- ticker: Stock symbol (e.g., NVDA, AAPL, MSFT). Must be uppercase.
- politician_name: Full name of the politician (e.g., "Nancy Pelosi", "Dan Crenshaw")
- transaction_type: "BUY" for purchases, "SELL" for sales
- amount_range: Dollar range if mentioned (e.g., "$1K-$15K", "$50K-$100K", "$1M-$5M")
- signal_date: Date of the transaction in ISO format (YYYY-MM-DD)
- confidence: Your confidence in this extraction from 0.0 to 1.0

IMPORTANT RULES:
1. If this is NOT a politician trading signal (e.g., general news, commentary), return: {"is_signal": false}
2. If you cannot confidently extract the ticker, return: {"is_signal": false}
3. For transaction_type, "purchased", "bought", "acquired" = "BUY"; "sold", "sold off", "disposed" = "SELL"
4. If signal_date is not explicitly mentioned, use the message timestamp date
5. Return ONLY valid JSON, no explanation or markdown

Message:
{message}

Message timestamp: {timestamp}

Return JSON:"""


def parse_message(
    client: anthropic.Anthropic, message_text: str, timestamp: str
) -> Optional[ParsedSignal]:
    """
    Parse a Telegram message using Claude API to extract trading signal data.

    Args:
        client: Anthropic client instance
        message_text: Raw message text from Telegram
        timestamp: ISO timestamp of the message

    Returns:
        ParsedSignal if a valid signal was extracted, None otherwise
    """
    try:
        response = client.messages.create(
            model="claude-3-5-haiku-20241022",  # Fast and cheap for parsing
            max_tokens=300,
            messages=[
                {
                    "role": "user",
                    "content": PARSE_PROMPT.format(message=message_text, timestamp=timestamp),
                }
            ],
        )

        # Extract the text content from response
        response_text = response.content[0].text.strip()

        # Try to parse as JSON
        try:
            data = json.loads(response_text)
        except json.JSONDecodeError:
            # Try to extract JSON from markdown code blocks
            json_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", response_text, re.DOTALL)
            if json_match:
                data = json.loads(json_match.group(1))
            else:
                print(f"Could not parse response as JSON: {response_text[:200]}")
                return None

        # Check if it's not a signal
        if data.get("is_signal") is False:
            return None

        # Validate required fields
        ticker = data.get("ticker")
        if not ticker:
            return None

        transaction_type = data.get("transaction_type", "").upper()
        if transaction_type not in ("BUY", "SELL"):
            return None

        # Extract signal date, fallback to timestamp date
        signal_date = data.get("signal_date")
        if not signal_date:
            # Use the date part of the timestamp
            signal_date = timestamp[:10]

        return ParsedSignal(
            ticker=ticker.upper(),
            politician_name=data.get("politician_name"),
            transaction_type=transaction_type,
            amount_range=data.get("amount_range"),
            signal_date=signal_date,
            confidence=float(data.get("confidence", 0.5)),
            raw_message=message_text[:500],  # Truncate for storage
        )

    except anthropic.APIError as e:
        print(f"Anthropic API error: {e}")
        return None
    except Exception as e:
        print(f"Error parsing message: {e}")
        return None


def batch_parse_messages(
    client: anthropic.Anthropic,
    messages: list[tuple[str, str]],  # List of (message_text, timestamp)
    verbose: bool = False,
) -> list[ParsedSignal]:
    """
    Parse multiple messages and return valid signals.

    Args:
        client: Anthropic client instance
        messages: List of (message_text, timestamp) tuples
        verbose: Print progress if True

    Returns:
        List of parsed signals (only valid ones)
    """
    signals = []

    for i, (message_text, timestamp) in enumerate(messages):
        if verbose and (i + 1) % 10 == 0:
            print(f"  Parsed {i + 1}/{len(messages)} messages...")

        signal = parse_message(client, message_text, timestamp)
        if signal:
            signals.append(signal)

    return signals
