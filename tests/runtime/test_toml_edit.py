"""set_toml_string: einzelne Werte setzen, Rest der config.toml unveraendert lassen."""

import tomllib

import pytest

from conclave.runtime.toml_edit import set_toml_string


def test_creates_file_and_section(tmp_path):
    path = tmp_path / "sub" / "config.toml"
    set_toml_string(path, "server", "rate_limit", "120 per minute")
    assert tomllib.loads(path.read_text(encoding="utf-8")) == {"server": {"rate_limit": "120 per minute"}}


def test_replaces_existing_value_and_keeps_comments_and_other_sections(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text(
        "# Kopf\n[database]\nprovider = \"sqlite\"\n\n[server]\n# Limit\nrate_limit = \"1/minute\"\nother = 1\n\n[participants]\n",
        encoding="utf-8",
    )
    set_toml_string(path, "server", "rate_limit", "5/minute")
    text = path.read_text(encoding="utf-8")
    data = tomllib.loads(text)
    assert data["server"] == {"rate_limit": "5/minute", "other": 1}
    assert data["database"] == {"provider": "sqlite"}
    assert "# Kopf" in text and "# Limit" in text
    assert text.count("rate_limit") == 1


def test_adds_key_to_existing_section_before_next_section(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text("[server]\nother = 1\n\n[participants]\nx = 2\n", encoding="utf-8")
    set_toml_string(path, "server", "rate_limit", "off")
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    assert data["server"] == {"other": 1, "rate_limit": "off"}
    assert data["participants"] == {"x": 2}


def test_escapes_special_characters(tmp_path):
    path = tmp_path / "config.toml"
    set_toml_string(path, "server", "rate_limit", 'a "b" \\ c')
    assert tomllib.loads(path.read_text(encoding="utf-8"))["server"]["rate_limit"] == 'a "b" \\ c'


def test_does_not_touch_similar_keys_or_sections(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text("[server.extra]\nrate_limit = \"x\"\n[serverx]\nrate_limit_old = \"y\"\n", encoding="utf-8")
    set_toml_string(path, "server", "rate_limit", "9/minute")
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    assert data["server"]["rate_limit"] == "9/minute"
    assert data["server"]["extra"]["rate_limit"] == "x"
    assert data["serverx"] == {"rate_limit_old": "y"}


def test_invalid_existing_file_is_not_overwritten(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text("[server\nkaputt", encoding="utf-8")
    with pytest.raises(Exception):
        set_toml_string(path, "server", "rate_limit", "1/minute")
    assert path.read_text(encoding="utf-8") == "[server\nkaputt"
