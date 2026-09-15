# Contributing

Thank you for your interest in contributing to Analytics Agent!

## Prerequisites

Before starting development, make sure you have:

- Python 3.11+
- [`uv`](https://docs.astral.sh/uv/getting-started/installation/)
- [`mise`](https://mise.jdx.dev/getting-started.html) — manages Node and `pnpm` (reads `.mise.toml`)

## Development setup

1. Fork the repository and clone your fork.
2. Create a feature branch from `main`.
3. Install dependencies:
   ```bash
   mise install     # installs Node + pnpm from .mise.toml
   make install     # uv sync + pnpm install
   ```
4. Start the development environment:
   ```bash
   make dev         # hot-reload backend (use `make dev-full` for frontend HMR too)
   ```

See the **Manual setup (for contributors / development)** section of `README.md` for full detail (first-time setup, `.env`, connecting DataHub), and `make help` for all available targets.

## Running tests and checks

Before opening a pull request:

```bash
make test        # unit tests
make lint        # ruff + format + mypy — mirrors CI; must pass
```

- `make fix` auto-fixes lint and formatting issues.
- `make test-integration` runs the integration suite (needs credentials in `.env`).

If you add or change behavior, include tests when practical.

## Commit messages

This project uses [Conventional Commits](https://www.conventionalcommits.org/). Keep messages concise and use an appropriate type, for example:

```text
feat: add analytics filter
fix: handle missing connector data
docs: clarify local development setup
chore: update dependencies
```

## Pull request process

1. Keep the change focused and related to one problem.
2. Run `make test` and `make lint` locally — CI runs the same checks.
3. Use a clear PR title (Conventional Commits style) and describe what changed and why.
4. Link the relevant issue when applicable (e.g. `Closes #123`).
5. Be responsive to review feedback and update the branch as needed.
6. Wait for CI checks and maintainer review before merging.

## Good first contributions

Documentation improvements, tests, bug fixes, and small usability improvements are all welcome. If you are unsure where to start, look for issues labeled `good first issue` or `documentation`.

## Questions

For questions about contributing or the development environment, please open an issue or start a discussion.
