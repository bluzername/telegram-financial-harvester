import json
from types import SimpleNamespace

import pytest

import signal_parser
from signal_parser import (
    DEFAULT_MODEL,
    ParsedSignal,
    extract_json,
    get_model,
    parse_message,
    signal_from_data,
)


class FakeMessages:
    def __init__(self, text):
        self.text = text
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(content=[SimpleNamespace(type="text", text=self.text)])


class FakeClient:
    def __init__(self, text):
        self.messages = FakeMessages(text)


def test_build_prompt_keeps_literal_json_braces():
    prompt = signal_parser.build_prompt("Pelosi bought NVDA", "2024-05-02T10:00:00")
    assert '{"is_signal": false}' in prompt
    assert "Pelosi bought NVDA" in prompt
    assert "2024-05-02T10:00:00" in prompt


def test_extract_json_plain_and_fenced():
    assert extract_json('{"a": 1}') == {"a": 1}
    assert extract_json('Sure:\n```json\n{"a": 2}\n```') == {"a": 2}
    assert extract_json("no json here") is None


def test_signal_from_data_valid():
    data = {
        "ticker": "nvda",
        "politician_name": "Nancy Pelosi",
        "transaction_type": "buy",
        "amount_range": "$1M-$5M",
        "signal_date": "2024-05-01",
        "confidence": "0.9",
    }
    signal = signal_from_data(data, "raw " * 200, "2024-05-02T10:00:00")
    assert signal.ticker == "NVDA"
    assert signal.transaction_type == "BUY"
    assert signal.confidence == 0.9
    assert len(signal.raw_message) == 500


def test_signal_from_data_defaults_date_to_timestamp():
    signal = signal_from_data({"ticker": "AAPL", "transaction_type": "SELL"}, "m", "2024-05-02T10:00:00")
    assert signal.signal_date == "2024-05-02"
    assert signal.confidence == 0.5


@pytest.mark.parametrize(
    "data",
    [
        {"is_signal": False},
        {"transaction_type": "BUY"},
        {"ticker": "AAPL", "transaction_type": "HOLD"},
        {"ticker": 42, "transaction_type": "BUY"},
    ],
)
def test_signal_from_data_rejects(data):
    assert signal_from_data(data, "m", "2024-05-02T10:00:00") is None


def test_parse_message_uses_configured_model(monkeypatch):
    monkeypatch.setenv("CLAUDE_MODEL", "claude-sonnet-5")
    client = FakeClient(json.dumps({"ticker": "MSFT", "transaction_type": "BUY"}))
    signal = parse_message(client, "Pelosi bought MSFT", "2024-05-02T10:00:00")
    assert isinstance(signal, ParsedSignal)
    assert client.messages.calls[0]["model"] == "claude-sonnet-5"
    assert "Pelosi bought MSFT" in client.messages.calls[0]["messages"][0]["content"]


def test_get_model_default(monkeypatch):
    monkeypatch.delenv("CLAUDE_MODEL", raising=False)
    assert get_model() == DEFAULT_MODEL
    assert DEFAULT_MODEL == "claude-haiku-4-5-20251001"


def test_parse_message_handles_api_error(monkeypatch):
    class Boom:
        class messages:
            @staticmethod
            def create(**kwargs):
                raise signal_parser.anthropic.APIConnectionError(request=None)

    assert parse_message(Boom(), "text", "2024-05-02T10:00:00") is None
