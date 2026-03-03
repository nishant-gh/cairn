# Cairn

A minimal AI agent memory system.

Cairn gives AI coding agents (Claude Code, Cursor, Aider, etc.) persistent,
structured memory across sessions.

## Install

```
uv sync
```

## Quick Start

```
cairn init
cairn add "Set up authentication" --priority 1
cairn add "Write login tests" --priority 2
cairn link c-a1b2 --blocks c-d4e5
cairn next --json
cairn set c-a1b2 --status active
cairn log c-a1b2 "JWT flow implemented"
cairn done c-a1b2 --reason "All tests passing"
cairn land --summary "Auth system done" --json
```

## Commands

```
init    - Create .cairn/ directory and AGENTS.md
add     - Create a new task
list    - List tasks with filters
show    - Display task details
set     - Update task fields
done    - Mark task complete
link    - Add a dependency
unlink  - Remove a dependency
next    - Show ready (unblocked) work
log     - Add a progress note
land    - Generate session handoff
```

Every command supports --json for structured agent output.

## Agent Integration

CLI (zero config): cairn init generates AGENTS.md that Claude Code and Cursor read.

## Design Principles

- Zero dependencies (stdlib only)
- One JSON file per task (clean git diffs, no merge conflicts)
- No daemon (every command reads/writes/exits)
- Hash-based IDs (no collisions across branches)
- Partial ID matching (c-a1 resolves to c-a1b2c3)
- Cycle detection (prevents circular dependencies)

## License: MIT
