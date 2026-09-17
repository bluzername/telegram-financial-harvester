import state
from telegram_export import parse_channel_list, sanitize_filename


def test_state_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setattr(state, "STATE_FILE", str(tmp_path / "state.json"))
    assert state.get_last_message_id(-100123) == 0
    state.set_last_message_id(-100123, 42)
    assert state.get_last_message_id(-100123) == 42
    state.increment_processed_count(3)
    state.increment_processed_count()
    assert state.get_processed_count() == 4


def test_parse_channel_list_mixed():
    assert parse_channel_list(" -1001234567890, some_channel ,https://t.me/x,, ") == [
        -1001234567890,
        "some_channel",
        "https://t.me/x",
    ]
    assert parse_channel_list(None) == []


def test_sanitize_filename():
    assert sanitize_filename("My Channel: News/Updates!") == "My_Channel_NewsUpdates!"
    assert sanitize_filename("שלום") == "unnamed_channel"
