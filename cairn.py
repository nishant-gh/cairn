#!/usr/bin/env python3
"""Cairn - A minimal AI agent memory system.

A lightweight, Git-backed task tracker and session memory for AI coding agents.
~800 lines, zero dependencies beyond Python's stdlib.

Usage:
    cairn init [--name NAME]
    cairn add TITLE [--priority N] [--type TYPE] [--parent ID]
    cairn list [--status S] [--priority N] [--type T] [--json]
    cairn show ID [--json]
    cairn set ID [--title T] [--status S] [--priority N] [--note MSG]
    cairn done ID [--reason MSG]
    cairn link ID --blocks OTHER_ID
    cairn unlink ID --blocks OTHER_ID
    cairn next [--json]
    cairn log ID MESSAGE
    cairn land [--summary TEXT] [--json]
"""

import argparse
import json
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

__version__ = "0.1.0"

# --- Constants ----------------------------------------------------------------

CAIRN_DIR = ".cairn"
TASKS_DIR = "tasks"
HANDOFFS_DIR = "handoffs"
CONFIG_FILE = "config.json"
VALID_STATUSES = ("open", "active", "done")
VALID_TYPES = ("task", "epic", "bug")
EXIT_OK = 0
EXIT_ERROR = 1
EXIT_USAGE = 2
EXIT_NOT_FOUND = 3
EXIT_CONFLICT = 5


# --- ID Generation and Resolution --------------------------------------------

def generate_id():
    return "c-" + uuid.uuid4().hex[:6]


def resolve_id(cairn_root, partial):
    tasks_dir = cairn_root / TASKS_DIR
    if not tasks_dir.exists():
        raise FileNotFoundError("No tasks directory found")
    if not partial.startswith("c-"):
        partial = "c-" + partial
    matches = [f.stem for f in tasks_dir.glob("c-*.json") if f.stem.startswith(partial)]
    if len(matches) == 0:
        raise FileNotFoundError("No task matching '{}'".format(partial))
    if len(matches) > 1:
        raise ValueError("Ambiguous ID '{}': matches {}".format(partial, ", ".join(sorted(matches))))
    return matches[0]


# --- Storage Layer ------------------------------------------------------------

def find_cairn_root():
    current = Path.cwd()
    while True:
        if (current / CAIRN_DIR).is_dir():
            return current / CAIRN_DIR
        parent = current.parent
        if parent == current:
            break
        current = parent
    print("Error: not a cairn project (no .cairn/ found). Run 'cairn init'.", file=sys.stderr)
    sys.exit(EXIT_ERROR)


def read_task(cairn_root, task_id):
    path = cairn_root / TASKS_DIR / (task_id + ".json")
    if not path.exists():
        raise FileNotFoundError("Task {} not found".format(task_id))
    with open(path, "r") as f:
        return json.load(f)


def write_task(cairn_root, task):
    path = cairn_root / TASKS_DIR / (task["id"] + ".json")
    with open(path, "w") as f:
        json.dump(task, f, indent=2)
        f.write("\n")


def list_tasks(cairn_root):
    tasks_dir = cairn_root / TASKS_DIR
    tasks = []
    if tasks_dir.exists():
        for path in sorted(tasks_dir.glob("c-*.json")):
            with open(path, "r") as f:
                tasks.append(json.load(f))
    return tasks


def write_handoff(cairn_root, handoff):
    handoffs_dir = cairn_root / HANDOFFS_DIR
    handoffs_dir.mkdir(exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%S")
    path = handoffs_dir / (ts + ".json")
    with open(path, "w") as f:
        json.dump(handoff, f, indent=2)
        f.write("\n")
    return path


def latest_handoff(cairn_root):
    handoffs_dir = cairn_root / HANDOFFS_DIR
    if not handoffs_dir.exists():
        return None
    files = sorted(handoffs_dir.glob("*.json"))
    if not files:
        return None
    with open(files[-1], "r") as f:
        return json.load(f)


# --- Dependency Graph ---------------------------------------------------------

def compute_blocked_set(tasks):
    blocked = set()
    done_ids = set(t["id"] for t in tasks if t["status"] == "done")
    for t in tasks:
        if t["status"] != "done":
            for target_id in t.get("blocks", []):
                if target_id not in done_ids:
                    blocked.add(target_id)
    return blocked


def would_create_cycle(cairn_root, source_id, target_id):
    tasks = list_tasks(cairn_root)
    task_map = {t["id"]: t for t in tasks}
    visited = set()
    stack = [target_id]
    while stack:
        current = stack.pop()
        if current == source_id:
            return True
        if current in visited:
            continue
        visited.add(current)
        t = task_map.get(current)
        if t:
            stack.extend(t.get("blocks", []))
    return False


# --- Output Formatting --------------------------------------------------------

def now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def print_json(data):
    print(json.dumps(data, indent=2))


def format_task_row(t):
    icons = {"open": " ", "active": ">", "done": "x"}
    icon = icons.get(t["status"], "?")
    p = "P" + str(t["priority"])
    bl = " blocks:" + ",".join(t["blocks"]) if t.get("blocks") else ""
    pa = " ^" + t["parent"] if t.get("parent") else ""
    return "  {} {}  {}  [{:6s}]  {}{}{}".format(icon, t["id"], p, t["status"], t["title"], bl, pa)


# --- Commands -----------------------------------------------------------------

def cmd_init(args):
    cairn_path = Path.cwd() / CAIRN_DIR
    if cairn_path.exists():
        print("Cairn already initialized in {}".format(cairn_path))
        return EXIT_OK
    cairn_path.mkdir()
    (cairn_path / TASKS_DIR).mkdir()
    (cairn_path / HANDOFFS_DIR).mkdir()
    config = {"name": args.name or Path.cwd().name, "version": __version__, "created": now_iso()}
    with open(cairn_path / CONFIG_FILE, "w") as f:
        json.dump(config, f, indent=2)
        f.write("\n")
    agents_md = Path.cwd() / "AGENTS.md"
    if not agents_md.exists():
        agents_md.write_text(AGENTS_MD_TEMPLATE.format(name=config["name"]))
        print("Created AGENTS.md")
    print("Initialized cairn project in {}".format(cairn_path))
    return EXIT_OK


def cmd_add(args):
    cairn_root = find_cairn_root()
    task_id = generate_id()
    parent = None
    if args.parent:
        try:
            parent = resolve_id(cairn_root, args.parent)
        except (FileNotFoundError, ValueError) as e:
            print("Error resolving parent: {}".format(e), file=sys.stderr)
            return EXIT_NOT_FOUND
    task = {
        "id": task_id, "title": args.title, "status": "open",
        "priority": args.priority, "type": args.type, "blocks": [],
        "parent": parent, "created": now_iso(), "updated": now_iso(),
        "notes": "", "log": [{"ts": now_iso(), "msg": "Created: " + args.title}],
    }
    write_task(cairn_root, task)
    if args.json:
        print_json(task)
    else:
        print("Created {}: {}".format(task_id, args.title))
    return EXIT_OK


def cmd_list(args):
    cairn_root = find_cairn_root()
    tasks = list_tasks(cairn_root)
    if args.status:
        tasks = [t for t in tasks if t["status"] == args.status]
    if args.priority is not None:
        tasks = [t for t in tasks if t["priority"] == args.priority]
    if args.type:
        tasks = [t for t in tasks if t["type"] == args.type]
    if args.json:
        print_json(tasks)
    else:
        if not tasks:
            print("No tasks found.")
        else:
            for t in tasks:
                print(format_task_row(t))
    return EXIT_OK


def cmd_show(args):
    cairn_root = find_cairn_root()
    try:
        task_id = resolve_id(cairn_root, args.id)
    except FileNotFoundError:
        print("Error: no task matching '{}'".format(args.id), file=sys.stderr)
        return EXIT_NOT_FOUND
    except ValueError as e:
        print("Error: {}".format(e), file=sys.stderr)
        return EXIT_CONFLICT
    task = read_task(cairn_root, task_id)
    if args.json:
        print_json(task)
    else:
        print("  ID:       {}".format(task["id"]))
        print("  Title:    {}".format(task["title"]))
        print("  Status:   {}".format(task["status"]))
        print("  Priority: P{}".format(task["priority"]))
        print("  Type:     {}".format(task["type"]))
        if task.get("parent"):
            print("  Parent:   {}".format(task["parent"]))
        if task.get("blocks"):
            print("  Blocks:   {}".format(", ".join(task["blocks"])))
        if task.get("notes"):
            print("  Notes:    {}".format(task["notes"]))
        print("  Created:  {}".format(task["created"]))
        print("  Updated:  {}".format(task["updated"]))
        if task.get("log"):
            print("  Log:")
            for entry in task["log"]:
                print("    [{}] {}".format(entry["ts"], entry["msg"]))
    return EXIT_OK


def cmd_set(args):
    cairn_root = find_cairn_root()
    try:
        task_id = resolve_id(cairn_root, args.id)
    except FileNotFoundError:
        print("Error: no task matching '{}'".format(args.id), file=sys.stderr)
        return EXIT_NOT_FOUND
    except ValueError as e:
        print("Error: {}".format(e), file=sys.stderr)
        return EXIT_CONFLICT
    task = read_task(cairn_root, task_id)
    changes = []
    if args.title:
        task["title"] = args.title
        changes.append("title -> " + args.title)
    if args.status:
        task["status"] = args.status
        changes.append("status -> " + args.status)
    if args.priority is not None:
        task["priority"] = args.priority
        changes.append("priority -> P" + str(args.priority))
    if args.note:
        task["notes"] = args.note
        changes.append("notes updated")
    if changes:
        task["updated"] = now_iso()
        task["log"].append({"ts": now_iso(), "msg": "Updated: " + ", ".join(changes)})
        write_task(cairn_root, task)
    if args.json:
        print_json(task)
    else:
        print("Updated {}: {}".format(task_id, ", ".join(changes) if changes else "no changes"))
    return EXIT_OK


def cmd_done(args):
    cairn_root = find_cairn_root()
    try:
        task_id = resolve_id(cairn_root, args.id)
    except FileNotFoundError:
        print("Error: no task matching '{}'".format(args.id), file=sys.stderr)
        return EXIT_NOT_FOUND
    except ValueError as e:
        print("Error: {}".format(e), file=sys.stderr)
        return EXIT_CONFLICT
    task = read_task(cairn_root, task_id)
    task["status"] = "done"
    task["updated"] = now_iso()
    reason = args.reason or "Completed"
    task["log"].append({"ts": now_iso(), "msg": "Done: " + reason})
    write_task(cairn_root, task)
    if args.json:
        print_json(task)
    else:
        print("Completed {}: {}".format(task_id, task["title"]))
    return EXIT_OK


def cmd_link(args):
    cairn_root = find_cairn_root()
    try:
        source_id = resolve_id(cairn_root, args.id)
        target_id = resolve_id(cairn_root, args.blocks)
    except FileNotFoundError as e:
        print("Error: {}".format(e), file=sys.stderr)
        return EXIT_NOT_FOUND
    except ValueError as e:
        print("Error: {}".format(e), file=sys.stderr)
        return EXIT_CONFLICT
    if source_id == target_id:
        print("Error: a task cannot block itself", file=sys.stderr)
        return EXIT_USAGE
    if would_create_cycle(cairn_root, source_id, target_id):
        print("Error: would create a cycle", file=sys.stderr)
        return EXIT_USAGE
    source = read_task(cairn_root, source_id)
    if target_id not in source["blocks"]:
        source["blocks"].append(target_id)
        source["updated"] = now_iso()
        source["log"].append({"ts": now_iso(), "msg": "Now blocks " + target_id})
        write_task(cairn_root, source)
    if args.json:
        print_json(source)
    else:
        print("Linked: {} --blocks--> {}".format(source_id, target_id))
    return EXIT_OK


def cmd_unlink(args):
    cairn_root = find_cairn_root()
    try:
        source_id = resolve_id(cairn_root, args.id)
        target_id = resolve_id(cairn_root, args.blocks)
    except FileNotFoundError as e:
        print("Error: {}".format(e), file=sys.stderr)
        return EXIT_NOT_FOUND
    except ValueError as e:
        print("Error: {}".format(e), file=sys.stderr)
        return EXIT_CONFLICT
    source = read_task(cairn_root, source_id)
    if target_id in source["blocks"]:
        source["blocks"].remove(target_id)
        source["updated"] = now_iso()
        source["log"].append({"ts": now_iso(), "msg": "No longer blocks " + target_id})
        write_task(cairn_root, source)
    if args.json:
        print_json(source)
    else:
        print("Unlinked: {} -/-> {}".format(source_id, target_id))
    return EXIT_OK


def cmd_next(args):
    cairn_root = find_cairn_root()
    tasks = list_tasks(cairn_root)
    blocked = compute_blocked_set(tasks)
    ready = [t for t in tasks if t["status"] in ("open", "active") and t["id"] not in blocked]
    ready.sort(key=lambda t: (t["priority"], t["created"]))
    handoff = latest_handoff(cairn_root)
    handoff_context = None
    if handoff and ready:
        top = ready[0]
        if top["id"] in handoff.get("still_active", []):
            handoff_context = handoff.get("next_prompt")
    if args.json:
        print_json({"ready": ready, "blocked_ids": sorted(blocked), "handoff_context": handoff_context})
    else:
        if not ready:
            print("No ready tasks. All tasks are done or blocked.")
        else:
            print("Ready tasks (highest priority first):")
            for t in ready:
                print(format_task_row(t))
            if handoff_context:
                print("\n  Last session context: " + handoff_context)
    return EXIT_OK


def cmd_log(args):
    cairn_root = find_cairn_root()
    try:
        task_id = resolve_id(cairn_root, args.id)
    except FileNotFoundError:
        print("Error: no task matching '{}'".format(args.id), file=sys.stderr)
        return EXIT_NOT_FOUND
    except ValueError as e:
        print("Error: {}".format(e), file=sys.stderr)
        return EXIT_CONFLICT
    task = read_task(cairn_root, task_id)
    task["log"].append({"ts": now_iso(), "msg": args.message})
    task["updated"] = now_iso()
    write_task(cairn_root, task)
    if args.json:
        print_json(task)
    else:
        print("Logged to {}".format(task_id))
    return EXIT_OK


def cmd_land(args):
    cairn_root = find_cairn_root()
    tasks = list_tasks(cairn_root)
    active = [t for t in tasks if t["status"] == "active"]
    done_ids = []
    for t in tasks:
        if t["status"] == "done" and t.get("log"):
            if t["log"][-1]["msg"].startswith("Done:"):
                done_ids.append(t["id"])
    summary = args.summary or "Session ended - see active tasks for status."
    blocked = compute_blocked_set(tasks)
    ready = [t for t in tasks if t["status"] in ("open", "active") and t["id"] not in blocked]
    ready.sort(key=lambda t: (t["priority"], t["created"]))
    next_prompt = None
    if ready:
        top = ready[0]
        last_msg = top["log"][-1]["msg"] if top.get("log") else ""
        next_prompt = "Continue work on {}: {} (P{}, {}). Last progress: {}".format(
            top["id"], top["title"], top["priority"], top["status"], last_msg)
    handoff = {
        "timestamp": now_iso(), "summary": summary, "completed": done_ids,
        "still_active": [t["id"] for t in active],
        "open_remaining": [t["id"] for t in ready if t["status"] == "open"],
        "blocked": sorted(blocked), "next_prompt": next_prompt,
    }
    path = write_handoff(cairn_root, handoff)
    if args.json:
        print_json(handoff)
    else:
        print("Session handoff saved to {}".format(path.name))
        print("\n  Summary: {}".format(summary))
        if active:
            print("  Active:  {}".format(", ".join(t["id"] for t in active)))
        if done_ids:
            print("  Done:    {}".format(", ".join(done_ids)))
        if next_prompt:
            print("\n  Next session prompt:\n  {}".format(next_prompt))
    return EXIT_OK


# --- AGENTS.md Template -------------------------------------------------------

AGENTS_MD_TEMPLATE = """# {name} - Agent Instructions

## Task Tracking with Cairn
This project uses `cairn` for task tracking and session memory.
Always use `--json` flag when running cairn commands for structured output.

### Session Start
Run `cairn next --json` to find the highest-priority unblocked task.
If handoff_context is present, read it for context from the previous session.

### During Work
- Create new tasks: `cairn add "title" --priority N --type task --json`
- Track dependencies: `cairn link <id> --blocks <other-id> --json`
- Log progress: `cairn log <id> "what you did" --json`
- Mark active: `cairn set <id> --status active --json`
- View a task: `cairn show <id> --json`
- List all tasks: `cairn list --json` or `cairn list --status open --json`

### Session End ("Land the Plane")
Before ending your session, always:
1. Mark completed tasks: `cairn done <id> --reason "why" --json`
2. Log progress on active tasks: `cairn log <id> "current status" --json`
3. Generate handoff: `cairn land --summary "brief summary" --json`
4. Commit: `git add .cairn && git commit -m "cairn: session update"`

### Task Priorities
- P0: Critical / blocking everything
- P1: High priority
- P2: Normal
- P3: Low / backlog

### Task Types
- task: Feature or general work item
- bug: Defect to fix
- epic: Parent container for related tasks (use --parent to link children)

### Dependencies
- `cairn link A --blocks B` means A must be done before B can start
- `cairn next` automatically filters out blocked tasks
- Use `cairn unlink A --blocks B` to remove a dependency

### Partial IDs
You can use partial IDs: `cairn show c-a1` resolves to `c-a1b2c3` if unambiguous.
"""


# --- CLI Parser ---------------------------------------------------------------

def build_parser():
    parser = argparse.ArgumentParser(prog="cairn", description="Cairn - A minimal AI agent memory system")
    parser.add_argument("--version", action="version", version="cairn " + __version__)
    sub = parser.add_subparsers(dest="command", help="Available commands")

    p = sub.add_parser("init", help="Initialize a new cairn project")
    p.add_argument("--name", help="Project name (defaults to directory name)")

    p = sub.add_parser("add", help="Create a new task")
    p.add_argument("title", help="Task title")
    p.add_argument("--priority", "-p", type=int, default=2, choices=range(4), help="Priority 0-3")
    p.add_argument("--type", "-t", default="task", choices=VALID_TYPES, help="Task type")
    p.add_argument("--parent", help="Parent task/epic ID")
    p.add_argument("--json", action="store_true", help="Output as JSON")

    p = sub.add_parser("list", help="List tasks with optional filters")
    p.add_argument("--status", "-s", choices=VALID_STATUSES, help="Filter by status")
    p.add_argument("--priority", "-p", type=int, choices=range(4), help="Filter by priority")
    p.add_argument("--type", "-t", choices=VALID_TYPES, help="Filter by type")
    p.add_argument("--json", action="store_true", help="Output as JSON")

    p = sub.add_parser("show", help="Show task details")
    p.add_argument("id", help="Task ID (partial match supported)")
    p.add_argument("--json", action="store_true", help="Output as JSON")

    p = sub.add_parser("set", help="Update task fields")
    p.add_argument("id", help="Task ID")
    p.add_argument("--title", help="New title")
    p.add_argument("--status", "-s", choices=VALID_STATUSES, help="New status")
    p.add_argument("--priority", "-p", type=int, choices=range(4), help="New priority")
    p.add_argument("--note", help="Replace notes field")
    p.add_argument("--json", action="store_true", help="Output as JSON")

    p = sub.add_parser("done", help="Mark a task as done")
    p.add_argument("id", help="Task ID")
    p.add_argument("--reason", "-r", default="", help="Completion reason")
    p.add_argument("--json", action="store_true", help="Output as JSON")

    p = sub.add_parser("link", help="Add dependency: ID blocks OTHER")
    p.add_argument("id", help="Source task ID")
    p.add_argument("--blocks", required=True, help="Target task that is blocked")
    p.add_argument("--json", action="store_true", help="Output as JSON")

    p = sub.add_parser("unlink", help="Remove dependency")
    p.add_argument("id", help="Source task ID")
    p.add_argument("--blocks", required=True, help="Target task to unblock")
    p.add_argument("--json", action="store_true", help="Output as JSON")

    p = sub.add_parser("next", help="Show highest-priority unblocked task")
    p.add_argument("--json", action="store_true", help="Output as JSON")

    p = sub.add_parser("log", help="Add a log entry to a task")
    p.add_argument("id", help="Task ID")
    p.add_argument("message", help="Log message")
    p.add_argument("--json", action="store_true", help="Output as JSON")

    p = sub.add_parser("land", help="Generate session handoff")
    p.add_argument("--summary", "-s", help="Session summary")
    p.add_argument("--json", action="store_true", help="Output as JSON")

    return parser


# --- Main ---------------------------------------------------------------------

COMMAND_MAP = {
    "init": cmd_init, "add": cmd_add, "list": cmd_list, "show": cmd_show,
    "set": cmd_set, "done": cmd_done, "link": cmd_link, "unlink": cmd_unlink,
    "next": cmd_next, "log": cmd_log, "land": cmd_land,
}


def main():
    parser = build_parser()
    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        sys.exit(EXIT_USAGE)
    handler = COMMAND_MAP.get(args.command)
    if handler:
        sys.exit(handler(args))
    else:
        parser.print_help()
        sys.exit(EXIT_USAGE)


if __name__ == "__main__":
    main()
