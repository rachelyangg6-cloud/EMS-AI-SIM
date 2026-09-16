"""`.env` loading — the repo gitignored it from the start but nothing read it."""
import os

from ems.llm import _load_dotenv


def test_a_key_in_dotenv_reaches_the_environment(tmp_path, monkeypatch):
    monkeypatch.delenv("EMS_TEST_KEY", raising=False)
    env = tmp_path / ".env"
    env.write_text('EMS_TEST_KEY=sk-from-file\n# a comment\n\n')
    _load_dotenv(env)
    assert os.environ["EMS_TEST_KEY"] == "sk-from-file"


def test_a_real_environment_variable_wins(tmp_path, monkeypatch):
    """`KEY=... command` must still override the file."""
    monkeypatch.setenv("EMS_TEST_KEY2", "from-shell")
    env = tmp_path / ".env"
    env.write_text("EMS_TEST_KEY2=from-file\n")
    _load_dotenv(env)
    assert os.environ["EMS_TEST_KEY2"] == "from-shell"


def test_quotes_are_stripped(tmp_path, monkeypatch):
    monkeypatch.delenv("EMS_TEST_KEY3", raising=False)
    env = tmp_path / ".env"
    env.write_text('EMS_TEST_KEY3="sk-quoted"\n')
    _load_dotenv(env)
    assert os.environ["EMS_TEST_KEY3"] == "sk-quoted"


def test_a_missing_file_is_not_an_error(tmp_path):
    _load_dotenv(tmp_path / "nope.env")
