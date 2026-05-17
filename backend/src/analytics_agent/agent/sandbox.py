"""Per-conversation Python + datahub CLI sandbox.

When `settings.enable_python_sandbox` is true, the agent receives a
`LocalShellBackend` rooted at `data/sandboxes/<conversation_id>/`. Inside
the sandbox the agent can write Python files, execute them, and shell out
to the `datahub` CLI for metadata operations that don't have direct
LangChain tools.

Trade-offs:
  - The `execute` tool is unsandboxed at the OS level — it runs with the
    server process's user permissions. We narrow the surface by passing a
    curated env (no inheritance) and a per-conversation cwd, but a
    determined agent can still read any file the server user can read.
  - For multi-tenant or internet-exposed deployments, leave the flag off
    and either (a) extend BaseSandbox with a Docker/VM backend or (b) rely
    on the existing typed tools.
"""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

from deepagents.backends.local_shell import LocalShellBackend

logger = logging.getLogger(__name__)


# Env vars passed through to the sandbox. Anything not in this set is
# stripped — no LLM API keys, no AWS creds, no random secrets. DataHub
# creds get a separate path because they may live in config.yaml rather
# than env vars (see curate_env below).
_ALLOWED_ENV_PASSTHROUGH: frozenset[str] = frozenset(
    {
        "PATH",
        "LANG",
        "LC_ALL",
        "PYTHONPATH",
    }
)


def curate_env(os_env: dict[str, str], datahub_url: str, datahub_token: str) -> dict[str, str]:
    """Build the sandbox's env dict.

    Pure function so the curation rule is independently testable. Includes
    only allow-listed keys from `os_env`, falls back to a sane PATH if absent,
    and injects DataHub creds from `settings.get_datahub_config()` so deployments
    that store creds in config.yaml (not env vars) still work in the sandbox.
    """
    env: dict[str, str] = {}
    for key in _ALLOWED_ENV_PASSTHROUGH:
        if key in os_env:
            env[key] = os_env[key]
    if "PATH" not in env:
        env["PATH"] = "/usr/local/bin:/usr/bin:/bin"
    # The agent runs under `uv run`, which doesn't put the venv on PATH —
    # without prepending it, sandbox `python` would be the system python
    # (no datahub-agent-context / pandas) and `datahub` wouldn't resolve.
    venv_bin = str(Path(sys.prefix) / "bin")
    if venv_bin not in env["PATH"].split(":"):
        env["PATH"] = f"{venv_bin}:{env['PATH']}"
        env["VIRTUAL_ENV"] = sys.prefix
    if datahub_url:
        env["DATAHUB_GMS_URL"] = datahub_url
    if datahub_token:
        env["DATAHUB_GMS_TOKEN"] = datahub_token
    return env


def build_sandbox_backend(conversation_id: str) -> LocalShellBackend:
    """Create (and ensure) a per-conversation LocalShellBackend.

    The sandbox dir is `{settings.sandbox_root_dir}/{conversation_id}/`.
    Caller must have already gated on `settings.enable_python_sandbox`.
    """
    from analytics_agent.config import settings

    sandbox_root = Path(settings.sandbox_root_dir).expanduser().resolve()
    sandbox_dir = sandbox_root / conversation_id
    sandbox_dir.mkdir(parents=True, exist_ok=True)

    datahub_url, datahub_token = settings.get_datahub_config()
    env = curate_env(dict(os.environ), datahub_url, datahub_token)

    logger.warning(
        "Python sandbox ENABLED for conversation %s at %s — agent has shell "
        "execution with curated env (DataHub creds passthrough only).",
        conversation_id,
        sandbox_dir,
    )

    return LocalShellBackend(
        root_dir=sandbox_dir,
        # virtual_mode=False so write_file and execute share the same path
        # semantics: cwd = root_dir, relative paths resolve there, absolute
        # paths hit the real OS root. With virtual_mode=True, write_file
        # silently rewrites "/foo" to "<root_dir>/foo" but execute does not
        # — so `execute("python /foo")` can't find the script that
        # `write_file("/foo", ...)` just created.
        # The path-traversal guardrail virtual_mode provides is moot: execute
        # can read any path the server user can read regardless.
        virtual_mode=False,
        timeout=settings.sandbox_command_timeout,
        max_output_bytes=settings.sandbox_max_output_bytes,
        inherit_env=False,
        env=env,
    )
