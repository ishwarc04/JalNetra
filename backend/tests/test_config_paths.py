"""Regression checks for configuration loading from different launch folders."""

import importlib.util
from pathlib import Path

import pytest

from app.core import paths


@pytest.mark.parametrize("launch_folder", ["repo", "repo/backend", "outside/work"])
def test_env_files_are_loaded_from_repo_not_launch_folder(tmp_path, monkeypatch, launch_folder):
    config_file = Path(__file__).resolve().parents[1] / "app/core/config.py"
    repo = tmp_path / "repo"
    (repo / "backend").mkdir(parents=True)
    (repo / "backend/.env").write_text(
        "APP_NAME=Backend local\nAPP_VERSION=9.8.7\n", encoding="utf-8"
    )
    (repo / ".env").write_text("APP_NAME=Repository settings\n", encoding="utf-8")

    outside = tmp_path / "outside/work"
    outside.mkdir(parents=True)
    (outside / ".env").write_text("APP_NAME=Unrelated settings\n", encoding="utf-8")
    (tmp_path / "outside/.env").write_text("APP_NAME=Unrelated parent\n", encoding="utf-8")
    monkeypatch.delenv("APP_NAME", raising=False)
    monkeypatch.delenv("APP_VERSION", raising=False)
    monkeypatch.setattr(paths, "get_repo_root", lambda: repo)
    monkeypatch.chdir(tmp_path / launch_folder)

    # Execute the settings module against the isolated repository so no real
    # credentials or configuration files need to be created or modified.
    spec = importlib.util.spec_from_file_location("isolated_jalnetra_config", config_file)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    assert module.settings.APP_NAME == "Repository settings"
    assert module.settings.APP_VERSION == "9.8.7"
    monkeypatch.setenv("APP_NAME", "Environment override")
    assert module.Settings().APP_NAME == "Environment override"
