"""Hatchling build hook — bundles the pre-built React frontend into the wheel.

Before building the wheel, copies frontend/dist/ → backend/src/analytics_agent/static/
so that `pip install datahub-analytics-agent` ships a fully self-contained package.

Prerequisite: run `cd frontend && pnpm install && pnpm build` before `uv build`.
CI does this automatically in publish.yml.
"""

from __future__ import annotations

import shutil
from pathlib import Path

from hatchling.builders.hooks.plugin.interface import BuildHookInterface


class CustomBuildHook(BuildHookInterface):
    PLUGIN_NAME = "custom"

    def initialize(self, version: str, build_data: dict) -> None:
        dist = Path("frontend/dist")
        target = Path("backend/src/analytics_agent/static")

        if not dist.exists():
            self.app.display_warning(
                "frontend/dist/ not found — building wheel without UI. "
                "Run `cd frontend && pnpm install && pnpm build` first."
            )
            return

        if target.exists():
            shutil.rmtree(target)
        shutil.copytree(dist, target)

        # static/ is gitignored, so hatchling's file scanner won't pick it up.
        # Explicitly register every file via force_include so they land in the wheel.
        for f in target.rglob("*"):
            if f.is_file():
                # key: path relative to project root
                # value: destination path inside the wheel (relative to package root)
                dest = str(f.relative_to("backend/src"))
                build_data["force_include"][str(f)] = dest

        self.app.display_info(f"Bundled frontend ({_count(target)} files) into {target}")

    def finalize(self, version: str, build_data: dict, artifact_path: str) -> None:
        # Clean up the generated static dir so it doesn't linger in the source tree
        target = Path("backend/src/analytics_agent/static")
        if target.exists():
            shutil.rmtree(target)


def _count(path: Path) -> int:
    return sum(1 for _ in path.rglob("*") if _.is_file())
