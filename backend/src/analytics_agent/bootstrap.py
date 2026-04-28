"""DB-mutating bootstrap functions.

Pure async helpers, no FastAPI coupling. Each is independently callable, idempotent,
and intended to be invoked from the analytics-agent CLI (typically via a Helm
pre-install/pre-upgrade hook). All write logic that used to live inside the
FastAPI lifespan now lives here.
"""

from __future__ import annotations
