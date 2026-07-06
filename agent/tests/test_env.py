import os

from duet_agent import env


def test_load_repo_env_sets_missing_keys(tmp_path, monkeypatch):
    dotenv = tmp_path / ".env"
    dotenv.write_text("GEMINI_API_KEY=from-file\n# comment\nEMPTY=\n")
    monkeypatch.setattr(env, "_env_file_candidates", lambda: [dotenv])
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)

    env.load_repo_env()

    assert os.environ["GEMINI_API_KEY"] == "from-file"


def test_load_repo_env_does_not_override_existing(tmp_path, monkeypatch):
    dotenv = tmp_path / ".env"
    dotenv.write_text("GEMINI_API_KEY=from-file\n")
    monkeypatch.setattr(env, "_env_file_candidates", lambda: [dotenv])
    monkeypatch.setenv("GEMINI_API_KEY", "from-shell")

    env.load_repo_env()

    assert os.environ["GEMINI_API_KEY"] == "from-shell"


def test_load_repo_env_fills_empty_shell_value(tmp_path, monkeypatch):
    dotenv = tmp_path / ".env"
    dotenv.write_text("GEMINI_API_KEY=from-file\n")
    monkeypatch.setattr(env, "_env_file_candidates", lambda: [dotenv])
    monkeypatch.setenv("GEMINI_API_KEY", "")

    env.load_repo_env()

    assert os.environ["GEMINI_API_KEY"] == "from-file"


def test_load_repo_env_finds_cwd_env(tmp_path, monkeypatch):
    dotenv = tmp_path / ".env"
    dotenv.write_text("GEMINI_API_KEY=from-cwd\n")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(env, "repo_root", lambda: tmp_path / "missing")
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)

    env.load_repo_env()

    assert os.environ["GEMINI_API_KEY"] == "from-cwd"
