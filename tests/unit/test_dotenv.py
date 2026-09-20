"""Phase 12 — .env fills gaps and never shadows a real environment variable."""
from __future__ import annotations

import os

import pytest

from shipdoc.infra.dotenv import load, parse


def test_a_real_environment_variable_always_wins(tmp_path, monkeypatch):
    """THE rule. Azure App Settings arrive as real env vars; a .env copied into an
    image must not silently repoint the deployed service."""
    monkeypatch.setenv("SHIPDOC_TEST_KEY", "from-the-real-environment")
    (tmp_path / ".env").write_text("SHIPDOC_TEST_KEY=from-the-file\n", encoding="utf-8")
    applied = load(tmp_path / ".env")
    assert os.environ["SHIPDOC_TEST_KEY"] == "from-the-real-environment"
    assert "SHIPDOC_TEST_KEY" not in applied


def test_a_gap_is_filled(tmp_path, monkeypatch):
    monkeypatch.delenv("SHIPDOC_TEST_GAP", raising=False)
    (tmp_path / ".env").write_text("SHIPDOC_TEST_GAP=filled\n", encoding="utf-8")
    assert load(tmp_path / ".env") == ["SHIPDOC_TEST_GAP"]
    assert os.environ["SHIPDOC_TEST_GAP"] == "filled"
    monkeypatch.delenv("SHIPDOC_TEST_GAP", raising=False)


def test_an_empty_real_value_is_treated_as_a_gap(tmp_path, monkeypatch):
    """A variable declared in a compose file with no value is how this breaks."""
    monkeypatch.setenv("SHIPDOC_TEST_BLANK", "")
    (tmp_path / ".env").write_text("SHIPDOC_TEST_BLANK=real\n", encoding="utf-8")
    load(tmp_path / ".env")
    assert os.environ["SHIPDOC_TEST_BLANK"] == "real"


def test_missing_file_is_not_an_error(tmp_path):
    assert load(tmp_path / "nope.env") == []


def test_load_returns_names_never_values(tmp_path, monkeypatch):
    """The return value gets printed. Printing values is how keys reach CI logs."""
    monkeypatch.delenv("SHIPDOC_SECRET", raising=False)
    (tmp_path / ".env").write_text("SHIPDOC_SECRET=hunter2\n", encoding="utf-8")
    applied = load(tmp_path / ".env")
    assert applied == ["SHIPDOC_SECRET"]
    assert "hunter2" not in str(applied)
    monkeypatch.delenv("SHIPDOC_SECRET", raising=False)


@pytest.mark.parametrize("line,expected", [
    ("A=1", {"A": "1"}),
    ("export A=1", {"A": "1"}),
    ('A="quoted"', {"A": "quoted"}),
    ("A='quoted'", {"A": "quoted"}),
    ("# comment", {}),
    ("", {}),
    ("   ", {}),
    ("no_equals_sign", {}),
    ("A=", {"A": ""}),
    # A '#' inside a value is not a comment — passwords contain them.
    ("A=pa#ss", {"A": "pa#ss"}),
    ("DATABASE_URL=postgresql+psycopg://u:p@h:5432/d?sslmode=require",
     {"DATABASE_URL": "postgresql+psycopg://u:p@h:5432/d?sslmode=require"}),
])
def test_parse_shapes(line, expected):
    assert parse(line) == expected
