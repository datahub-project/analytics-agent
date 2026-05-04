"""
analytics_agent/telemetry.py

Anonymous product analytics — annotate once, emit twice.

Application code creates OTEL spans with business attributes at key event points.
MixpanelSpanProcessor intercepts those spans, strips everything not in the
attribute allowlist (anonymization), then fires Mixpanel events in a background
thread so on_end() never blocks the caller.

Opt-out (checked in priority order):
  1. Any CI environment variable is set
  2. DATAHUB_TELEMETRY_ENABLED=false
  3. ~/.datahub/telemetry-config.json has "enabled": false

Client ID (priority order):
  1. ~/.datahub/telemetry-config.json client_id  (reuse DataHub CLI identity)
  2. "telemetry_client_id" key in DB settings table
  3. Fresh UUID — persisted to DB for next startup
"""
from __future__ import annotations

import importlib.metadata
import json
import logging
import os
import platform
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import TYPE_CHECKING

from opentelemetry.sdk.trace import ReadableSpan, SpanProcessor

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)

# ── Constants ─────────────────────────────────────────────────────────────────

# Shared DataHub CLI Mixpanel project — events are distinguishable by name.
_MIXPANEL_TOKEN = "5ee83d940754d63cacbf7d34daa6f44a"
_MIXPANEL_ENDPOINT = "track.datahubproject.io/mp"
_MIXPANEL_TIMEOUT = 2  # seconds — non-negotiable; must not stall on_end()

_CLI_CONFIG_FILE = Path.home() / ".datahub" / "telemetry-config.json"
_DB_CLIENT_ID_KEY = "telemetry_client_id"

# Full CI environment variable set copied from DataHub CLI telemetry.py.
# If any of these are set, we're almost certainly in a CI pipeline.
_CI_ENV_VARS: frozenset[str] = frozenset({
    "APPCENTER", "APPCIRCLE", "APPVEYOR", "AZURE_PIPELINES", "BAMBOO",
    "BITBUCKET", "BITRISE", "BUDDY", "BUILDKITE", "BUILD_ID", "CI",
    "CIRCLE", "CIRCLECI", "CIRRUS", "CIRRUS_CI", "CI_NAME", "CODEBUILD",
    "CODEBUILD_BUILD_ID", "CODEFRESH", "CODESHIP", "CYPRESS_HOST", "DRONE",
    "DSARI", "EAS_BUILD", "GITHUB_ACTIONS", "GITLAB", "GITLAB_CI", "GOCD",
    "HEROKU_TEST_RUN_ID", "HUDSON", "JENKINS", "JENKINS_URL", "LAYERCI",
    "MAGNUM", "NETLIFY", "NEVERCODE", "RENDER", "SAIL", "SCREWDRIVER",
    "SEMAPHORE", "SHIPPABLE", "SOLANO", "STRIDER", "TASKCLUSTER", "TEAMCITY",
    "TEAMCITY_VERSION", "TF_BUILD", "TRAVIS", "VERCEL", "WERCKER_ROOT",
})

# Span names we care about — everything else is ignored by MixpanelSpanProcessor.
KNOWN_SPAN_NAMES: frozenset[str] = frozenset({
    "agent.started",
    "query.completed",
    "connection.tested",
    "chart.generated",
})

# Attribute allowlist per span name — the only keys forwarded to Mixpanel.
# Any attribute not listed here is silently dropped (anonymization guarantee).
_ATTRIBUTE_ALLOWLIST: dict[str, frozenset[str]] = {
    "agent.started": frozenset({
        "llm.provider", "engines.count", "engine_types", "prompt_cache.enabled",
    }),
    "query.completed": frozenset({"engine.type", "row.count"}),
    "connection.tested": frozenset({"engine.type", "connection.success"}),
    "chart.generated": frozenset({"chart.type"}),
}


# ── TelemetryClient ───────────────────────────────────────────────────────────

class TelemetryClient:
    """Singleton that owns Mixpanel initialization and synchronous event emission.

    Call ``await initialize(session_factory)`` once from the FastAPI lifespan.
    Until that completes, ``enabled`` is False and all track calls are no-ops.
    """

    def __init__(self) -> None:
        self.enabled: bool = False
        self.client_id: str = str(uuid.uuid4())
        self._mp = None
        self._global_props: dict = {}

    # ── Opt-out checks ────────────────────────────────────────────────────────

    def _is_ci(self) -> bool:
        return any(v in os.environ for v in _CI_ENV_VARS)

    def _read_cli_config(self) -> tuple[str | None, bool | None]:
        """Return (client_id, enabled) from ~/.datahub/telemetry-config.json.

        Returns (None, None) on any read/parse failure — caller treats as absent.
        """
        try:
            with open(_CLI_CONFIG_FILE) as fh:
                data = json.load(fh)
            return data["client_id"], bool(data["enabled"])
        except Exception:
            return None, None

    # ── Async initialization ──────────────────────────────────────────────────

    async def initialize(self, session_factory) -> None:
        """Resolve client_id, check opt-out, instantiate Mixpanel.

        Must be called from an async context (FastAPI lifespan) because the
        DB client_id fallback requires async SQLAlchemy.
        """
        from analytics_agent.config import settings

        if self._is_ci():
            logger.debug("Telemetry disabled: running in CI environment")
            return

        if not settings.datahub_telemetry_enabled:
            logger.debug("Telemetry disabled: DATAHUB_TELEMETRY_ENABLED=false")
            return

        cli_client_id, cli_enabled = self._read_cli_config()
        if cli_enabled is False:
            logger.debug("Telemetry disabled: ~/.datahub/telemetry-config.json enabled=false")
            return

        # Resolve client_id
        if cli_client_id:
            self.client_id = cli_client_id
        else:
            self.client_id = await self._resolve_db_client_id(session_factory)

        # Build global properties attached to every Mixpanel event.
        # "source" is the primary segmentation key in the shared DataHub Mixpanel
        # project — it lets dashboards filter analytics-agent events with a single
        # predicate without relying on event name patterns.
        try:
            version = importlib.metadata.version("datahub-analytics-agent")
        except Exception:
            version = "unknown"
        self._global_props = {
            "source": "analytics-agent",
            "deployment_id": self.client_id,
            "analytics_agent_version": version,
            "python_version": platform.python_version(),
            "os": platform.system(),
            "arch": platform.machine(),
        }

        # Instantiate Mixpanel client
        try:
            from mixpanel import Consumer, Mixpanel

            self._mp = Mixpanel(
                _MIXPANEL_TOKEN,
                consumer=Consumer(
                    request_timeout=_MIXPANEL_TIMEOUT,
                    api_host=_MIXPANEL_ENDPOINT,
                ),
            )
            self.enabled = True
            logger.info(
                "Telemetry enabled (client_id=%s...)", self.client_id[:8]
            )
        except Exception as exc:
            logger.debug("Telemetry init failed: %s", exc)

    async def _resolve_db_client_id(self, session_factory) -> str:
        """Look up or generate a persistent client_id in the DB settings table."""
        from analytics_agent.db.repository import SettingsRepo

        try:
            async with session_factory() as session:
                repo = SettingsRepo(session)
                stored = await repo.get(_DB_CLIENT_ID_KEY)
                if stored:
                    return stored
                new_id = str(uuid.uuid4())
                await repo.set(_DB_CLIENT_ID_KEY, new_id)
                return new_id
        except Exception as exc:
            logger.debug("Could not persist telemetry client_id: %s", exc)
            return str(uuid.uuid4())

    # ── Synchronous event emission (called from thread pool) ──────────────────

    def track_sync(self, event_name: str, properties: dict) -> None:
        """Emit a Mixpanel event synchronously. Intended for thread-pool use only."""
        if not self.enabled or self._mp is None:
            return
        try:
            merged = {**self._global_props, **properties}
            self._mp.track(self.client_id, event_name, merged)
        except Exception as exc:
            logger.debug("Mixpanel send failed for %s: %s", event_name, exc)


# ── MixpanelSpanProcessor ─────────────────────────────────────────────────────

class MixpanelSpanProcessor(SpanProcessor):
    """OTEL SpanProcessor that routes known business spans to Mixpanel.

    Registered alongside the OTLP BatchSpanProcessor in tracing.py so every
    span is offered to both sinks. Only spans whose name is in KNOWN_SPAN_NAMES
    are forwarded, and only attributes in _ATTRIBUTE_ALLOWLIST survive.

    on_end() is synchronous (OTEL contract). Mixpanel HTTP I/O is offloaded to
    a single-worker ThreadPoolExecutor to avoid blocking span processing.
    """

    def __init__(self, client: TelemetryClient) -> None:
        self._client = client
        self._executor = ThreadPoolExecutor(
            max_workers=1, thread_name_prefix="mixpanel-telemetry"
        )

    def on_start(self, span, parent_context=None) -> None:  # noqa: ARG002
        pass

    def on_end(self, span: ReadableSpan) -> None:
        if span.name not in KNOWN_SPAN_NAMES:
            return
        if not self._client.enabled:
            return

        allowed = _ATTRIBUTE_ALLOWLIST.get(span.name, frozenset())
        props = {k: v for k, v in (span.attributes or {}).items() if k in allowed}

        client = self._client
        self._executor.submit(client.track_sync, span.name, props)

    def shutdown(self) -> None:
        self._executor.shutdown(wait=True, cancel_futures=False)

    def force_flush(self, timeout_millis: int = 30_000) -> bool:  # noqa: ARG002
        return True


# ── Module-level singletons ───────────────────────────────────────────────────

telemetry_client = TelemetryClient()
mixpanel_processor = MixpanelSpanProcessor(telemetry_client)


async def init_telemetry(session_factory) -> None:
    """Initialize telemetry from the FastAPI lifespan. Idempotent."""
    await telemetry_client.initialize(session_factory)
