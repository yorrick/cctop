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

**NEVER use recency-based (most recently modified file) fallbacks** for transcript/session ID resolution. When multiple sessions share a project directory, the most recently modified transcript belongs to a *different* session, causing cross-contamination (e.g. session "features" getting the name "backlog"). Only use exact session ID matches.

**NEVER use CWD-based heuristics** to map hook events to sessions. CWD mapping is unreliable — multiple sessions can share the same CWD, and stale events from dead sessions get mis-attributed to new ones. Use `transcript_path` (available on every hook event) for deterministic matching.

### Session ID → Transcript Mapping

Claude Code uses two different session IDs that may diverge:
- **PID-file session ID**: stored in `~/.claude/sessions/{pid}.json`, changes on every resume
- **Transcript session ID**: the original ID embedded in the transcript `.jsonl` filename, stable across resumes

Hook events report the **transcript** session ID and include `transcript_path`, while cctop discovers sessions via **PID-file** session IDs. The `SessionManager._resolve_session()` bridges this gap via:
1. Direct match (PID-file ID == transcript ID, for new sessions)
2. Cached mapping (learned from a previous transcript-path match)
3. Transcript-path matching: extract the encoded project dir from `event.transcript_path`, find a session whose `encode_cwd(cwd)` matches. Stale events (timestamp before the session's `started_at`) are rejected.

Note: the transcript file may not exist yet when `session_start` fires. The `transcript_path` is stored and retried on subsequent `refresh()` cycles.

### Project Directory Encoding (`encode_cwd`)

Claude Code encodes CWD paths into project directory names by replacing `/`, `_`, and `.` with `-`. Our `encode_cwd()` must match this exactly. Example: `/Users/foo/.worktrees/bar` → `-Users-foo--worktrees-bar` (the `.` becomes `-`, creating a double dash).

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
