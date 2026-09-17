"""
Signal Parser - Uses the Claude API to extract structured signals from raw Telegram messages.

Parses natural language politician trading disclosures into structured data
that can be sent to the checklister webhook.

The model is read from the CLAUDE_MODEL environment variable and defaults to
DEFAULT_MODEL. The JSON extraction and validation steps are pure functions so
they can be unit tested without network access.
"""

import json
import os
import re
from dataclasses import dataclass
from typing import Any, Optional

import anthropic

DEFAULT_MODEL = "claude-haiku-4-5-20251001"
MAX_TOKENS = 300
RAW_MESSAGE_LIMIT = 500


@dataclass(frozen=True)
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


def build_prompt(message_text: str, timestamp: str) -> str:
    """
    Fill the prompt template. Uses replace() rather than str.format() because
    the template contains literal JSON braces such as {"is_signal": false}.
    """
    return PARSE_PROMPT.replace("{message}", message_text).replace("{timestamp}", timestamp)


def get_model() -> str:
    """Model ID to use, from CLAUDE_MODEL or the default."""
    return os.getenv("CLAUDE_MODEL", "").strip() or DEFAULT_MODEL


def extract_json(response_text: str) -> Optional[dict]:
    """
    Parse the model output as JSON, tolerating a markdown code fence.
    Returns None when no JSON object can be found.
    """
    text = response_text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if not match:
        return None
    try:
        return json.loads(match.group(1))
    except json.JSONDecodeError:
        return None


def signal_from_data(data: dict, message_text: str, timestamp: str) -> Optional[ParsedSignal]:
    """
    Validate the extracted fields and build a ParsedSignal.
    Returns None when the data is not a usable signal.
    """
    if data.get("is_signal") is False:
        return None

    ticker = data.get("ticker")
    if not ticker or not isinstance(ticker, str):
        return None

    transaction_type = str(data.get("transaction_type", "")).upper()
    if transaction_type not in ("BUY", "SELL"):
        return None

    signal_date = data.get("signal_date") or timestamp[:10]

    try:
        confidence = float(data.get("confidence", 0.5))
    except (TypeError, ValueError):
        confidence = 0.5

    return ParsedSignal(
        ticker=ticker.upper(),
        politician_name=data.get("politician_name"),
        transaction_type=transaction_type,
        amount_range=data.get("amount_range"),
        signal_date=signal_date,
        confidence=confidence,
        raw_message=message_text[:RAW_MESSAGE_LIMIT],
    )


def _response_text(response: Any) -> str:
    """First text block of a Messages API response."""
    for block in getattr(response, "content", []) or []:
        if getattr(block, "type", None) == "text":
            return block.text
    return ""


def parse_message(
    client: anthropic.Anthropic,
    message_text: str,
    timestamp: str,
    model: Optional[str] = None,
) -> Optional[ParsedSignal]:
    """
    Parse a Telegram message using the Claude API to extract trading signal data.

    Args:
        client: Anthropic client instance
        message_text: Raw message text from Telegram
        timestamp: ISO timestamp of the message
        model: Model ID override (defaults to CLAUDE_MODEL / DEFAULT_MODEL)

    Returns:
        ParsedSignal if a valid signal was extracted, None otherwise
    """
    try:
        response = client.messages.create(
            model=model or get_model(),
            max_tokens=MAX_TOKENS,
            messages=[
                {
                    "role": "user",
                    "content": build_prompt(message_text, timestamp),
                }
            ],
        )
    except anthropic.APIError as e:
        print(f"Anthropic API error: {e}")
        return None

    response_text = _response_text(response)
    data = extract_json(response_text)
    if data is None:
        print(f"Could not parse response as JSON: {response_text[:200]}")
        return None

    return signal_from_data(data, message_text, timestamp)


def batch_parse_messages(
    client: anthropic.Anthropic,
    messages: list,  # List of (message_text, timestamp) tuples
    verbose: bool = False,
) -> list:
    """
    Parse multiple messages and return only the valid signals.
    """
    signals = []
    for i, (message_text, timestamp) in enumerate(messages):
        if verbose and (i + 1) % 10 == 0:
            print(f"  Parsed {i + 1}/{len(messages)} messages...")
        signal = parse_message(client, message_text, timestamp)
        if signal:
            signals.append(signal)
    return signals
