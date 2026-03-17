# cctop — Design Specification

A Textual-based TUI for monitoring all active Claude Code sessions in real-time, similar to `htop` for processes.

## Problem

When running many Claude Code sessions simultaneously across different terminal windows, it's easy to lose track of what each session is doing, which are idle, and what they've accomplished. There's no unified view.

## Solution

`cctop` is a live terminal dashboard that discovers all running Claude Code sessions, shows their real-time status (working/idle/offline), and lets you expand any session to see its summary, git branch, PR link, and other metadata.

## Data Architecture

Three data sources are merged into a unified session model:

### Source 1: Session Discovery — `~/.claude/sessions/{pid}.json`

One file per running Claude Code process. First line contains:

```json
{"pid": 36783, "sessionId": "b119b9f1-...", "cwd": "/Users/.../website", "startedAt": 1773690112394}
```

Used for:
- Discovering which sessions exist
- PID liveness checks (`os.kill(pid, 0)`) to detect hard-killed sessions
- Working directory and start time

### Source 2: Session Metadata — `~/.claude/projects/{encoded-cwd}/sessions-index.json`

Rich metadata indexed by project directory:

```json
{
  "sessionId": "...",
  "summary": "Created n8n-utils repo with GitHub setup",
  "firstPrompt": "create a repo named n8n-utils",
  "gitBranch": "main",
  "messageCount": 14,
  "created": "2026-01-22T17:30:31.745Z",
  "modified": "2026-01-22T17:51:36.041Z",
  "projectPath": "/Users/.../work"
}
```

Used for:
- Session summary (Claude-generated, updated as conversation progresses)
- First prompt
- Git branch
- Message count
- Created/modified timestamps

### Source 3: Real-time Hook Events — `~/.cctop/data/events.jsonl`

Events produced by our hook script, appended as JSONL:

```json
{"ts": 1773764710403, "sid": "a7259198-...", "type": "tool_start", "tool": "Bash", "cwd": "/Users/.../work"}
{"ts": 1773764710496, "sid": "a7259198-...", "type": "tool_end", "tool": "Bash", "ok": true}
{"ts": 1773764712000, "sid": "a7259198-...", "type": "stop"}
{"ts": 1773764800000, "sid": "a7259198-...", "type": "session_start", "cwd": "/Users/.../work"}
{"ts": 1773764900000, "sid": "a7259198-...", "type": "session_end"}
```

Used for:
- Current tool being used (working status)
- Precise idle time (time since last `stop` or `tool_end` event)
- Session lifecycle events

### Source 4: GitHub PR Lookup (background, cached)

`gh pr list --head <branch> --json url,title` run in background for sessions with a git branch.

Used for:
- PR URL and title displayed in expanded view

## Session Model

```python
class Session(BaseModel):
    session_id: str
    pid: int
    cwd: Path
    project_name: str           # derived: repo name or dir basename
    worktree_name: str | None   # parsed from cwd if .worktrees/ pattern
    git_branch: str | None      # from sessions-index
    pr_url: str | None          # from gh lookup, cached
    pr_title: str | None        # from gh lookup, cached
    status: Literal["working", "idle", "offline"]
    current_tool: str | None    # from hooks, when working
    started_at: datetime
    last_activity: datetime     # from hooks
    ended_at: datetime | None   # when offline: from hook or PID death detection
    idle_duration: timedelta    # computed
    session_duration: timedelta # computed
    message_count: int          # from sessions-index
    summary: str | None         # from sessions-index
    first_prompt: str | None    # from sessions-index
```

## CLI Interface

Built with Typer. Three commands:

### `cctop` (default command)

Launches the Textual TUI.

```
cctop [--recent DURATION]
```

- `--recent`: Include sessions that ended within this duration. Accepts values like `30m`, `1h`, `2h`. Default: `0` (live sessions only).

### `cctop install`

Registers hook script in Claude Code's settings.

1. Creates `~/.cctop/hooks/` and `~/.cctop/data/` directories
2. Writes `~/.cctop/hooks/cctop-hook.sh` (the bash hook script)
3. Reads `~/.claude/settings.json`
4. Appends hook entries for: `PreToolUse`, `PostToolUse`, `Stop`, `SessionStart`, `SessionEnd` (never replaces existing hooks)
5. Writes back `settings.json`
6. Prints success message: "Hooks installed. Restart your Claude Code sessions for hooks to take effect."

### `cctop uninstall`

Removes hooks and cleans up.

1. Reads `~/.claude/settings.json`
2. Removes only hook entries whose command path contains `cctop`
3. Writes back `settings.json`
4. Removes `~/.cctop/` directory
5. Prints confirmation

## Hook Script

A bash script (`~/.cctop/hooks/cctop-hook.sh`) registered for 5 Claude Code hook events:

- `PreToolUse` → emits `tool_start` event
- `PostToolUse` → emits `tool_end` event
- `Stop` → emits `stop` event
- `SessionStart` → emits `session_start` event
- `SessionEnd` → emits `session_end` event

The script:
1. Reads JSON from stdin (provided by Claude Code)
2. Extracts key fields with `jq`
3. Appends one JSONL line to `~/.cctop/data/events.jsonl`

Requires `jq` as a dependency (checked during `cctop install`).

## TUI Layout

```
┌─────────────────────────────────────────────────────────────────────┐
│  cctop — 9 sessions (7 active, 2 idle)     Sort: [idle time ▼]    │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  ● gen-ai-on-aws          main        Working: Bash    12m   0s    │
│  ● gen-ai-on-aws          issue-349   Working: Edit     8m  30s    │
│  ◉ website                feat/redesign  Idle           45m   2m   │
│  │  PR: #42 "Redesign landing page"                                │
│  │  Summary: Implementing responsive grid layout for the hero      │
│  │  section. Added Tailwind breakpoints for mobile/tablet/desktop. │
│  │  Currently waiting for feedback on the color scheme choice.     │
│  │                                                                  │
│  ○ claude-code-plugins    main        Idle            1h20m  15m   │
│  ● autonomous-agent       main        Working: Read    2d 4h   0s  │
│  ○ linkedin-posts         main        Idle            3d 2h  45m   │
│  ○ work                   —           Idle              5m   3m    │
│  ◌ yorrick-jansen-eoy     main        Offline          20m   —     │
│  ◌ website (2)            feat/seo    Offline          45m   —     │
│                                                                     │
├─────────────────────────────────────────────────────────────────────┤
│  ↑↓ navigate  Enter expand/collapse  F6 sort  ? help  q quit      │
└─────────────────────────────────────────────────────────────────────┘
```

### Status Indicators

- `●` green — working (tool currently in use)
- `○` yellow — idle (alive, waiting for user input)
- `◌` gray — offline (dead PID or recently ended session)

### Collapsed Row

| Column | Source |
|--------|--------|
| Status icon (colored) | PID liveness + hook events |
| Project name | Derived from `cwd` |
| Branch / worktree | `sessions-index.json` / parsed from `cwd` |
| Status text + current tool | Hook events |
| Session duration | `startedAt` from session file |
| Idle time | Time since last hook activity |

### Expanded View (on Enter)

Shown below the collapsed row:
- Summary (from `sessions-index.json`)
- First prompt
- Full working directory path
- PR link + title (if found via `gh`)
- Message count
- Git branch

### Keyboard Shortcuts

| Key | Action |
|-----|--------|
| `↑`/`↓` or `k`/`j` | Navigate sessions |
| `Enter` | Expand / collapse session |
| `F6` or `>`/`<` | Cycle sort mode |
| `/` | Filter / search |
| `?` or `h` | Help |
| `F10` or `q` | Quit |

### Sort Modes

Cycle through:
1. Idle time (longest first)
2. Duration (longest first)
3. Name (alphabetical)
4. Status (working → idle → offline)

## Polling & Update Loop

The TUI runs background async tasks:

### Every 2 seconds
- Scan `~/.claude/sessions/*.json` for session discovery
- Check PID liveness for each session (`os.kill(pid, 0)`)
- Tail `~/.cctop/data/events.jsonl` for new hook events (track file byte offset)
- Update session status and current tool from events

### Every 10 seconds
- Re-read relevant `sessions-index.json` files for updated summaries, message counts, branches
- Run `gh pr list --head <branch>` for sessions with a git branch but no cached PR (background, non-blocking)

### On PID death detection
- Mark session as offline
- Record `ended_at = now`
- If `--recent` flag is set, keep showing with gray indicator until `now - ended_at > recent_duration`
- If `--recent` is 0, remove from the list

## Project Structure

```
cctop/
  __init__.py
  cli.py              # Typer CLI (main, install, uninstall)
  app.py              # Textual App + polling loop
  models.py           # Pydantic Session model
  sources/
    __init__.py
    sessions.py       # ~/.claude/sessions/ reader + PID liveness
    index.py          # sessions-index.json reader
    events.py         # events.jsonl tailer
    github.py         # gh PR lookup (background, cached)
  hooks/
    __init__.py
    install.py        # Hook install/uninstall logic
    cctop-hook.sh     # Bash hook script template
  widgets/
    __init__.py
    session_list.py   # Main scrollable list widget
    session_row.py    # Collapsed row widget
    session_detail.py # Expanded detail view
    header.py         # Top bar with session counts + sort indicator
    footer.py         # Keyboard shortcut help bar
```

## Tech Stack

- **Python >=3.12**
- **uv** for package management
- **Textual** for TUI framework
- **Typer** for CLI
- **Pydantic** for data models
- **loguru** for logging
- **ruff** for formatting + linting
- **pyright** for type checking
- **pytest** for testing
- **pre-commit** hooks for ruff format, ruff check, pyright

## Dependencies

Runtime:
- `textual`
- `typer`
- `pydantic`
- `loguru`

System (checked during `cctop install`):
- `jq` (for hook script)
- `gh` (optional, for PR lookups)
