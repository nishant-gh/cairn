#!/usr/bin/env python3
"""Cairn MCP Server - Exposes Cairn commands as MCP tools.

Optional companion to cairn.py. Requires: pip install fastmcp

Usage with Claude Code:
    claude mcp add --transport stdio cairn -- python cairn_mcp.py

Usage with Cursor (~/.cursor/mcp.json):
    {"mcpServers": {"cairn": {"command": "python", "args": ["cairn_mcp.py"]}}}
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from mcp.server.fastmcp import FastMCP
import cairn

mcp = FastMCP("cairn", description="Cairn - minimal AI agent memory system")


def _get_root():
    current = Path.cwd()
    while True:
        if (current / cairn.CAIRN_DIR).is_dir():
            return current / cairn.CAIRN_DIR
        parent = current.parent
        if parent == current:
            raise FileNotFoundError("No .cairn/ directory found. Run 'cairn init' first.")
        current = parent


def _ok(data):
    return json.dumps(data, indent=2)


def _err(msg):
    return json.dumps({"error": str(msg)})


@mcp.tool()
def cairn_next() -> str:
    """Get the highest-priority unblocked task. Call this at the start of every session."""
    try:
        root = _get_root()
        tasks = cairn.list_tasks(root)
        blocked = cairn.compute_blocked_set(tasks)
        ready = [t for t in tasks if t["status"] in ("open", "active") and t["id"] not in blocked]
        ready.sort(key=lambda t: (t["priority"], t["created"]))
        handoff = cairn.latest_handoff(root)
        ctx = None
        if handoff and ready and ready[0]["id"] in handoff.get("still_active", []):
            ctx = handoff.get("next_prompt")
        return _ok({"ready": ready, "blocked_ids": sorted(blocked), "handoff_context": ctx})
    except Exception as e:
        return _err(e)


@mcp.tool()
def cairn_add(title: str, priority: int = 2, task_type: str = "task", parent: str = "") -> str:
    """Create a new task. priority: 0=critical, 1=high, 2=normal, 3=low. task_type: task|bug|epic."""
    try:
        root = _get_root()
        task_id = cairn.generate_id()
        parent_id = None
        if parent:
            parent_id = cairn.resolve_id(root, parent)
        task = {
            "id": task_id, "title": title, "status": "open", "priority": priority,
            "type": task_type, "blocks": [], "parent": parent_id,
            "created": cairn.now_iso(), "updated": cairn.now_iso(),
            "notes": "", "log": [{"ts": cairn.now_iso(), "msg": "Created: " + title}],
        }
        cairn.write_task(root, task)
        return _ok(task)
    except Exception as e:
        return _err(e)


@mcp.tool()
def cairn_list(status: str = "", priority: int = -1, task_type: str = "") -> str:
    """List tasks. Optional filters: status (open|active|done), priority (0-3), task_type."""
    try:
        root = _get_root()
        tasks = cairn.list_tasks(root)
        if status:
            tasks = [t for t in tasks if t["status"] == status]
        if priority >= 0:
            tasks = [t for t in tasks if t["priority"] == priority]
        if task_type:
            tasks = [t for t in tasks if t["type"] == task_type]
        return _ok(tasks)
    except Exception as e:
        return _err(e)


@mcp.tool()
def cairn_show(task_id: str) -> str:
    """Show full details of a task. Supports partial ID matching."""
    try:
        root = _get_root()
        full_id = cairn.resolve_id(root, task_id)
        return _ok(cairn.read_task(root, full_id))
    except Exception as e:
        return _err(e)


@mcp.tool()
def cairn_set(task_id: str, title: str = "", status: str = "", priority: int = -1, note: str = "") -> str:
    """Update task fields. Only provided fields are changed."""
    try:
        root = _get_root()
        full_id = cairn.resolve_id(root, task_id)
        task = cairn.read_task(root, full_id)
        changes = []
        if title:
            task["title"] = title
            changes.append("title")
        if status:
            task["status"] = status
            changes.append("status -> " + status)
        if priority >= 0:
            task["priority"] = priority
            changes.append("priority -> P" + str(priority))
        if note:
            task["notes"] = note
            changes.append("notes")
        if changes:
            task["updated"] = cairn.now_iso()
            task["log"].append({"ts": cairn.now_iso(), "msg": "Updated: " + ", ".join(changes)})
            cairn.write_task(root, task)
        return _ok(task)
    except Exception as e:
        return _err(e)


@mcp.tool()
def cairn_done(task_id: str, reason: str = "Completed") -> str:
    """Mark a task as done with an optional reason."""
    try:
        root = _get_root()
        full_id = cairn.resolve_id(root, task_id)
        task = cairn.read_task(root, full_id)
        task["status"] = "done"
        task["updated"] = cairn.now_iso()
        task["log"].append({"ts": cairn.now_iso(), "msg": "Done: " + reason})
        cairn.write_task(root, task)
        return _ok(task)
    except Exception as e:
        return _err(e)


@mcp.tool()
def cairn_link(source_id: str, blocks_id: str) -> str:
    """Add dependency: source task must be done before blocks_id can start."""
    try:
        root = _get_root()
        src = cairn.resolve_id(root, source_id)
        tgt = cairn.resolve_id(root, blocks_id)
        if src == tgt:
            return _err("A task cannot block itself")
        if cairn.would_create_cycle(root, src, tgt):
            return _err("Would create a dependency cycle")
        task = cairn.read_task(root, src)
        if tgt not in task["blocks"]:
            task["blocks"].append(tgt)
            task["updated"] = cairn.now_iso()
            task["log"].append({"ts": cairn.now_iso(), "msg": "Now blocks " + tgt})
            cairn.write_task(root, task)
        return _ok(task)
    except Exception as e:
        return _err(e)


@mcp.tool()
def cairn_log(task_id: str, message: str) -> str:
    """Add a progress log entry to a task."""
    try:
        root = _get_root()
        full_id = cairn.resolve_id(root, task_id)
        task = cairn.read_task(root, full_id)
        task["log"].append({"ts": cairn.now_iso(), "msg": message})
        task["updated"] = cairn.now_iso()
        cairn.write_task(root, task)
        return _ok(task)
    except Exception as e:
        return _err(e)


@mcp.tool()
def cairn_land(summary: str = "Session ended - see active tasks for status.") -> str:
    """Generate a session handoff record. Call this before ending your session."""
    try:
        root = _get_root()
        tasks = cairn.list_tasks(root)
        active = [t for t in tasks if t["status"] == "active"]
        done_ids = [t["id"] for t in tasks if t["status"] == "done" and t.get("log")
                    and t["log"][-1]["msg"].startswith("Done:")]
        blocked = cairn.compute_blocked_set(tasks)
        ready = [t for t in tasks if t["status"] in ("open", "active") and t["id"] not in blocked]
        ready.sort(key=lambda t: (t["priority"], t["created"]))
        next_prompt = None
        if ready:
            top = ready[0]
            last_msg = top["log"][-1]["msg"] if top.get("log") else ""
            next_prompt = "Continue work on {}: {} (P{}, {}). Last progress: {}".format(
                top["id"], top["title"], top["priority"], top["status"], last_msg)
        handoff = {
            "timestamp": cairn.now_iso(), "summary": summary, "completed": done_ids,
            "still_active": [t["id"] for t in active],
            "open_remaining": [t["id"] for t in ready if t["status"] == "open"],
            "blocked": sorted(blocked), "next_prompt": next_prompt,
        }
        cairn.write_handoff(root, handoff)
        return _ok(handoff)
    except Exception as e:
        return _err(e)


if __name__ == "__main__":
    mcp.run(transport="stdio")
