"""Yapılandırma: Windows'tan gelen .env değerleri ve anlaşılır hata mesajları."""

from __future__ import annotations

import pytest
from cryptography.fernet import Fernet
from pydantic import ValidationError

from app.__main__ import format_config_errors, run
from app.config import Settings, get_settings

KEY = Fernet.generate_key().decode()


def test_crlf_and_spaces_are_stripped(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_bytes(
        (
            "BOT_TOKEN=123:ABC\r\n"
            "API_ID= 42 \r\n"
            "API_HASH=abcdef\r\n"
            f"SESSION_ENCRYPTION_KEY={KEY}\r\n"
            "ADMIN_IDS=1, 2\r\n"
        ).encode()
    )
    settings = Settings(_env_file=env_file)
    assert settings.bot_token.get_secret_value() == "123:ABC"
    assert settings.api_id == 42
    assert settings.api_hash.get_secret_value() == "abcdef"
    assert settings.session_encryption_key.get_secret_value() == KEY
    assert settings.admin_ids == [1, 2]


@pytest.mark.parametrize("bad_key", ["", "gecersiz-anahtar"])
def test_bad_encryption_key_is_rejected(bad_key):
    with pytest.raises(ValidationError) as exc:
        Settings(
            _env_file=None, bot_token="1:x", api_id=1, api_hash="h", session_encryption_key=bad_key
        )
    message = format_config_errors(exc.value)
    assert "SESSION_ENCRYPTION_KEY" in message
    assert "app.tools.genkey" in message


def test_missing_values_are_listed(monkeypatch, tmp_path, capsys):
    monkeypatch.chdir(tmp_path)  # .env yok
    for name in ("BOT_TOKEN", "API_ID", "API_HASH", "SESSION_ENCRYPTION_KEY"):
        monkeypatch.delenv(name, raising=False)
    get_settings.cache_clear()
    try:
        with pytest.raises(SystemExit) as exc:
            run()
    finally:
        get_settings.cache_clear()
    assert exc.value.code == 1
    err = capsys.readouterr().err
    assert "BOT_TOKEN: eksik" in err
    assert "API_HASH: eksik" in err
    assert ".env.txt" in err
