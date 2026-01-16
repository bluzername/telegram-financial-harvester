"""
State management for the Telegram signal pipeline.

Tracks the last processed message ID to avoid reprocessing signals.
State is persisted to a JSON file between runs.
"""

import json
import os
from typing import Dict, Any

STATE_FILE = "pipeline_state.json"


def load_state() -> Dict[str, Any]:
    """
    Load pipeline state from file.
    Returns empty dict if file doesn't exist.
    """
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError) as e:
            print(f"Warning: Could not load state file: {e}")
            return {}
    return {}


def save_state(state: Dict[str, Any]) -> None:
    """
    Save pipeline state to file.
    """
    try:
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2)
    except IOError as e:
        print(f"Error: Could not save state file: {e}")


def get_last_message_id(channel_id: int) -> int:
    """
    Get the last processed message ID for a specific channel.
    Returns 0 if no state exists.
    """
    state = load_state()
    channel_key = str(channel_id)
    return state.get("channels", {}).get(channel_key, {}).get("last_message_id", 0)


def set_last_message_id(channel_id: int, message_id: int) -> None:
    """
    Update the last processed message ID for a specific channel.
    """
    state = load_state()

    if "channels" not in state:
        state["channels"] = {}

    channel_key = str(channel_id)
    if channel_key not in state["channels"]:
        state["channels"][channel_key] = {}

    state["channels"][channel_key]["last_message_id"] = message_id
    save_state(state)


def get_processed_count() -> int:
    """
    Get the total count of processed signals across all runs.
    """
    state = load_state()
    return state.get("total_processed", 0)


def increment_processed_count(count: int = 1) -> None:
    """
    Increment the total processed signal count.
    """
    state = load_state()
    state["total_processed"] = state.get("total_processed", 0) + count
    save_state(state)
