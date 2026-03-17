# cctop — Claude Code Instructions

## Code Quality

This project uses the standard Python stack:

- **uv** for package and environment management
- **ruff format** for formatting — run `uv run ruff format src/ tests/`
- **ruff check** for linting — run `uv run ruff check --fix src/ tests/`
- **pyright** for type checking — run `uv run pyright`
- All 3 checks are enforced by a pre-commit hook (runs automatically on commit)
- **pydantic** for data models and validation
- **loguru** for logging — never use stdlib `logging`
- **pytest** for testing — unit tests MUST be written for every code change

## Testing

Run the full test suite:
```
uv run pytest
```

Contract tests (require `claude` CLI and cost tokens) are excluded by default. To run them explicitly:
```
uv run pytest -m contract
```

## Validation

Before claiming a change is done:
1. Run `uv run ruff format src/ tests/ && uv run ruff check src/ tests/ && uv run pyright && uv run pytest`
2. All checks must pass — fix any errors before finishing

## Workflow After Every Change

After completing any code change, always follow these steps in order:

1. **Simplify** — run `/simplify` to review and clean up the changed code
2. **Create a PR** — run `/commit-push-pr` to commit, push, and open a pull request
3. **Review** — run `/code-review:code-review` and `/security-review` on the PR
