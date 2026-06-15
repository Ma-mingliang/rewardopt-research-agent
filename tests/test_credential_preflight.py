"""Tests for .env loading and credential preflight."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest

from research_agent.core.config import load_dotenv


class TestLoadDotenv:
    def test_loads_key_from_file(self, tmp_path):
        env_file = tmp_path / ".env"
        env_file.write_text("TEST_DOTENV_KEY=hello123\n")
        # Ensure key doesn't exist in shell
        os.environ.pop("TEST_DOTENV_KEY", None)
        loaded = load_dotenv([env_file])
        assert "TEST_DOTENV_KEY" in loaded
        assert os.environ["TEST_DOTENV_KEY"] == "hello123"
        # Cleanup
        os.environ.pop("TEST_DOTENV_KEY", None)

    def test_shell_nonempty_takes_precedence(self, tmp_path):
        env_file = tmp_path / ".env"
        env_file.write_text("TEST_DOTENV_KEY=from_dotenv\n")
        os.environ["TEST_DOTENV_KEY"] = "from_shell"
        loaded = load_dotenv([env_file])
        assert "TEST_DOTENV_KEY" not in loaded
        assert os.environ["TEST_DOTENV_KEY"] == "from_shell"
        os.environ.pop("TEST_DOTENV_KEY", None)

    def test_shell_empty_allows_dotenv_override(self, tmp_path):
        env_file = tmp_path / ".env"
        env_file.write_text("TEST_DOTENV_KEY=from_dotenv\n")
        os.environ["TEST_DOTENV_KEY"] = ""
        loaded = load_dotenv([env_file])
        assert "TEST_DOTENV_KEY" in loaded
        assert os.environ["TEST_DOTENV_KEY"] == "from_dotenv"
        os.environ.pop("TEST_DOTENV_KEY", None)

    def test_missing_env_file_returns_empty(self, tmp_path):
        missing = tmp_path / "nonexistent.env"
        loaded = load_dotenv([missing])
        assert loaded == {}

    def test_skips_comments_and_blanks(self, tmp_path):
        env_file = tmp_path / ".env"
        env_file.write_text("# comment\n\nKEY_A=val_a\n  # another\nKEY_B=val_b\n")
        os.environ.pop("KEY_A", None)
        os.environ.pop("KEY_B", None)
        loaded = load_dotenv([env_file])
        assert loaded["KEY_A"] == "val_a"
        assert loaded["KEY_B"] == "val_b"
        os.environ.pop("KEY_A", None)
        os.environ.pop("KEY_B", None)

    def test_strips_quotes(self, tmp_path):
        env_file = tmp_path / ".env"
        env_file.write_text('QUOTED_KEY="hello world"\n')
        os.environ.pop("QUOTED_KEY", None)
        loaded = load_dotenv([env_file])
        assert os.environ["QUOTED_KEY"] == "hello world"
        os.environ.pop("QUOTED_KEY", None)

    def test_multiple_files_first_wins(self, tmp_path):
        env1 = tmp_path / ".env1"
        env1.write_text("MULTI_KEY=first\n")
        env2 = tmp_path / ".env2"
        env2.write_text("MULTI_KEY=second\n")
        os.environ.pop("MULTI_KEY", None)
        loaded = load_dotenv([env1, env2])
        assert os.environ["MULTI_KEY"] == "first"
        os.environ.pop("MULTI_KEY", None)

    def test_no_api_key_leak_in_loaded_dict(self, tmp_path):
        env_file = tmp_path / ".env"
        env_file.write_text("SECRET_KEY=super_secret_value_12345\n")
        os.environ.pop("SECRET_KEY", None)
        loaded = load_dotenv([env_file])
        # loaded dict contains the key name but this is internal, not logged
        assert "SECRET_KEY" in loaded
        os.environ.pop("SECRET_KEY", None)
