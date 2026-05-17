"""Unit tests for the sandbox env curation.

The sandbox backend itself spawns subprocesses; here we only validate
the pure `curate_env` helper, which is the security-relevant boundary.
"""

from __future__ import annotations

from analytics_agent.agent.sandbox import curate_env


def test_curate_env_keeps_allow_listed_keys_only():
    env = curate_env(
        os_env={
            "PATH": "/usr/bin",
            "LANG": "en_US.UTF-8",
            "AWS_ACCESS_KEY_ID": "leak",
            "OPENAI_API_KEY": "leak",
            "RANDOM_SECRET": "leak",
        },
        datahub_url="",
        datahub_token="",
    )
    # Allow-listed PATH + LANG survive; secrets are stripped.
    assert "LANG" in env
    assert "AWS_ACCESS_KEY_ID" not in env
    assert "OPENAI_API_KEY" not in env
    assert "RANDOM_SECRET" not in env


def test_curate_env_fills_in_default_path_when_absent():
    env = curate_env({}, datahub_url="", datahub_token="")
    assert "/usr/bin" in env["PATH"]


def test_curate_env_prepends_venv_bin_for_uv_run():
    """`uv run` doesn't put .venv/bin on PATH; sandbox needs it so
    `python` and `datahub` resolve to the project's tools, not system."""
    import sys

    env = curate_env({"PATH": "/usr/bin"}, datahub_url="", datahub_token="")
    venv_bin = f"{sys.prefix}/bin"
    assert env["PATH"].startswith(venv_bin)
    assert env.get("VIRTUAL_ENV") == sys.prefix


def test_curate_env_injects_datahub_creds_when_provided():
    env = curate_env(
        {"PATH": "/usr/bin"},
        datahub_url="http://gms.example.com",
        datahub_token="tok",
    )
    assert env["DATAHUB_GMS_URL"] == "http://gms.example.com"
    assert env["DATAHUB_GMS_TOKEN"] == "tok"


def test_curate_env_omits_datahub_creds_when_blank():
    env = curate_env({"PATH": "/usr/bin"}, datahub_url="", datahub_token="")
    assert "DATAHUB_GMS_URL" not in env
    assert "DATAHUB_GMS_TOKEN" not in env
