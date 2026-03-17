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

## Claude CLI Behavior — Validate Before Assuming

Any assumption about how `claude` CLI behaves (what files it creates, what hooks it fires, what processes it spawns) **MUST be validated empirically before implementing a fix**. Never assume — run it and observe.

Validated facts (do not re-investigate unless behavior seems to have changed):
- `claude --print "..."` does NOT create a PID file in `~/.claude/sessions/`
- `claude --print "..."` DOES fire hook events: `session_start`, `stop`, `session_end` (with a new session ID and the cwd of the process that spawned it)
- These events can be mistakenly resolved to a real session via CWD-based mapping if not guarded

To validate new assumptions about `claude` CLI behavior:
```bash
# Watch session files
ls -la ~/.claude/sessions/

# Watch hook events in real time
tail -f ~/.cctop/data/events.jsonl | python3 -c "import sys,json; [print(json.loads(l)) for l in sys.stdin]"

# Run the thing you want to test, then inspect what changed
```

## Issue Tracking

All issues are tracked in GitHub Issues (not Linear).

## Workflow for Every Feature

Every feature MUST follow this full workflow:

1. **Brainstorm** — run `/brainstorming` to explore intent, requirements, and design
2. **Plan & implement** — pass the brainstorming output to `/dev-loop:workflow` to generate and execute the implementation plan
3. Features MUST be developed in a git worktree (use the `superpowers:using-git-worktrees` skill to set one up)

After completing any code change, always follow these steps in order:

1. **Simplify** — run `/simplify` to review and clean up the changed code
2. **Create a PR** — run `/commit-push-pr` to commit, push, and open a pull request
3. **Review** — run `/code-review:code-review` and `/security-review` on the PR
