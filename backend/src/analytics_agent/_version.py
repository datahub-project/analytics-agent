"""Single source of truth for the running package version.

Both the FastAPI app constructor (``main.create_app``) and the
``GET /api/version`` endpoint read the version through :func:`get_package_version`
so there is no hardcoded version string to drift out of sync with the package
metadata.
"""

from __future__ import annotations

import importlib.metadata
import os

PACKAGE_NAME = "datahub-analytics-agent"


def get_package_version() -> str:
    """Return the installed package version.

    Resolution order:

    1. ``ANALYTICS_AGENT_OVERRIDE_VERSION`` env var (used by dev/CI builds).
    2. ``importlib.metadata.version`` for the installed distribution.
    3. ``"unknown"`` if the package is not installed (e.g. running from a
       source checkout without an editable install).
    """
    try:
        return os.environ.get("ANALYTICS_AGENT_OVERRIDE_VERSION") or importlib.metadata.version(
            PACKAGE_NAME
        )
    except Exception:
        return "unknown"
