"""Thread dump parsers for jcmd Thread.print and Spring Boot Actuator."""

from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from typing import Any

_JCMD_THREAD_HEADER_RE = re.compile(
    r'^"([^"]+)"\s+(?:#(\d+)\s+)?(?:(daemon)\s+)?'
    r'(?:prio=\d+\s+)?(?:os_prio=\S+\s+)?(?:cpu=[\d.]+ms\s+)?(?:elapsed=[\d.]+s\s+)?'
    r'tid=(\S+)\s+nid=(\S+)\s+(.*)$'
)
_JCMD_STATE_RE = re.compile(r'^\s*java\.lang\.Thread\.State:\s+(\S+)(?:\s+\(([^)]+)\))?')
_JCMD_FRAME_RE = re.compile(r'^\s+at\s+(.+)$')
_JCMD_LOCKED_RE = re.compile(r'^\s+-\s+locked\s+<0x([0-9a-fA-F]+)>\s+\(a\s+([^)]+)\)')
_JCMD_WAITING_LOCK_RE = re.compile(
    r'^\s+-\s+(?:waiting to lock|waiting to re-lock in wait\(\))\s+<0x([0-9a-fA-F]+)>\s+\(a\s+([^)]+)\)'
)
_JCMD_PARKING_RE = re.compile(
    r'^\s+-\s+(?:parking to wait for|waiting on)\s+<0x([0-9a-fA-F]+)>\s+\(a\s+([^)]+)\)'
)
_JCMD_OWNABLE_SYNC_RE = re.compile(r'^\s+-\s+<0x([0-9a-fA-F]+)>\s+\(a\s+([^)]+)\)')
_JCMD_DEADLOCK_HEADER_RE = re.compile(r'^Found\s+(?:one|\d+)\s+Java-level\s+deadlocks?:', re.IGNORECASE)

_GENERIC_FRAME_PREFIXES = (
    "java.lang.Object.wait",
    "java.lang.Thread.sleep",
    "java.lang.Thread.yield",
    "java.lang.ref.",
    "jdk.internal.misc.Unsafe.park",
    "sun.misc.Unsafe.park",
    "java.util.concurrent.locks.LockSupport.park",
    "java.util.concurrent.locks.AbstractQueuedSynchronizer",
    "java.util.concurrent.SynchronousQueue",
    "java.util.concurrent.LinkedBlockingQueue",
    "java.util.concurrent.LinkedBlockingDeque",
    "java.util.concurrent.ArrayBlockingQueue",
    "java.util.concurrent.ThreadPoolExecutor.getTask",
    "java.util.concurrent.ScheduledThreadPoolExecutor",
    "sun.nio.ch.",
    "java.net.SocketInputStream",
    "java.net.PlainSocketImpl",
    "io.netty.channel.epoll.Epoll.wait",
    "io.netty.channel.epoll.Native.epollWait",
)


def _thread_group_name(name: str) -> str:
    """Normalize numbered thread names into pool/group names."""
    cleaned = re.sub(r'\s*#\d+$', '', name).strip()
    cleaned = re.sub(r'[-_]\d+(?:[-_]\d+)*$', '', cleaned).strip()
    cleaned = re.sub(r'\s+\d+$', '', cleaned).strip()
    return cleaned or name


def _pick_informative_frame(frames: list[str]) -> str:
    """Return the first non-JDK-parking stack frame, falling back to the top frame."""
    if not frames:
        return "native / no stack"
    for frame in frames:
        if not any(frame.startswith(prefix) for prefix in _GENERIC_FRAME_PREFIXES):
            return frame.split("(", 1)[0]
    return frames[0].split("(", 1)[0]



def _summarize_threads(threads: list[dict[str, Any]], deadlocks: list[dict[str, Any]], source_format: str) -> dict[str, Any]:
    """Build a compact structured summary from normalized thread records."""
    state_counts: Counter[str] = Counter()
    groups: dict[str, dict[str, Any]] = {}
    lock_holders: dict[str, dict[str, Any]] = {}
    lock_waiters: dict[str, list[dict[str, Any]]] = defaultdict(list)
    waiting_stacks: dict[tuple[str, str], dict[str, Any]] = {}

    for t in threads:
        state = t.get("state") or "UNKNOWN"
        state_counts[state] += 1
        grp = _thread_group_name(t["name"])
        if grp not in groups:
            groups[grp] = {"prefix": grp, "count": 0, "states": Counter()}
        groups[grp]["count"] += 1
        groups[grp]["states"][state] += 1

        for lock in t.get("locks_held", []):
            lid = lock["id"]
            if lid not in lock_holders:
                lock_holders[lid] = {
                    "lock_id": lid,
                    "lock_class": lock["class"],
                    "owner_thread": t["name"],
                    "owner_state": state,
                }

        waiting_on = t.get("waiting_on_lock")
        if waiting_on:
            lock_waiters[waiting_on["id"]].append(
                {
                    "thread": t["name"],
                    "state": state,
                    "lock_class": waiting_on["class"],
                    "top_frames": t.get("frames", [])[:4],
                }
            )
            if waiting_on["id"] not in lock_holders and waiting_on.get("owner_thread"):
                lock_holders[waiting_on["id"]] = {
                    "lock_id": waiting_on["id"],
                    "lock_class": waiting_on["class"],
                    "owner_thread": waiting_on["owner_thread"],
                    "owner_state": waiting_on.get("owner_state", "UNKNOWN"),
                }

        if state in ("BLOCKED", "WAITING", "TIMED_WAITING"):
            top_frame = _pick_informative_frame(t.get("frames", []))
            key = (state, top_frame)
            if key not in waiting_stacks:
                waiting_stacks[key] = {
                    "state": state,
                    "top_frame": top_frame,
                    "count": 0,
                    "sample_thread": t["name"],
                }
            waiting_stacks[key]["count"] += 1

    lock_owners = []
    for lid, waiters in lock_waiters.items():
        holder = lock_holders.get(lid, {})
        lock_owners.append(
            {
                "lock_id": lid,
                "lock_class": holder.get("lock_class") or waiters[0]["lock_class"],
                "owner_thread": holder.get("owner_thread", "unknown"),
                "owner_state": holder.get("owner_state", "UNKNOWN"),
                "waiter_count": len(waiters),
                "waiter_threads": [w["thread"] for w in waiters[:5]],
            }
        )
    lock_owners.sort(key=lambda item: item["waiter_count"], reverse=True)

    blocked_threads = []
    for t in threads:
        if t.get("state") == "BLOCKED":
            waiting_on = t.get("waiting_on_lock") or {}
            lid = waiting_on.get("id")
            owner = lock_holders.get(lid, {}).get("owner_thread") if lid else None
            blocked_threads.append(
                {
                    "thread": t["name"],
                    "waiting_on_lock": waiting_on.get("class") or lid,
                    "owner_thread": owner or waiting_on.get("owner_thread") or "unknown",
                    "top_frames": t.get("frames", [])[:4],
                }
            )

    sorted_groups = [
        {"prefix": g["prefix"], "count": g["count"], "states": dict(g["states"])}
        for g in sorted(groups.values(), key=lambda x: x["count"], reverse=True)[:10]
    ]
    sorted_waiting = sorted(waiting_stacks.values(), key=lambda x: x["count"], reverse=True)[:10]

    return {
        "source_format": source_format,
        "total_threads": len(threads),
        "states": dict(state_counts),
        "deadlock_count": len(deadlocks),
        "deadlocks": deadlocks[:5],
        "lock_owners": lock_owners[:10],
        "blocked_threads": blocked_threads[:10],
        "top_waiting_stacks": sorted_waiting,
        "thread_groups": sorted_groups,
    }


def parse_jcmd_thread_dump(raw: str) -> dict[str, Any]:
    """Parse `jcmd <pid> Thread.print` (or `jstack`) output into a compact summary."""
    lines = raw.splitlines()
    threads: list[dict[str, Any]] = []
    deadlocks: list[dict[str, Any]] = []

    current: dict[str, Any] | None = None
    in_ownable_sync = False
    in_deadlock = False
    deadlock_lines: list[str] = []

    for line in lines:
        if _JCMD_DEADLOCK_HEADER_RE.match(line):
            if current is not None:
                threads.append(current)
                current = None
            in_deadlock = True
            deadlock_lines = [line.strip()]
            continue

        if in_deadlock:
            deadlock_lines.append(line)
            continue

        header_match = _JCMD_THREAD_HEADER_RE.match(line)
        if header_match:
            if current is not None:
                threads.append(current)
            name, _tid_num, daemon, _tid, _nid, tail = header_match.groups()
            # Some VM/GC threads carry state on the header line (e.g. 'runnable') without Thread.State
            inferred_state = "RUNNABLE" if "runnable" in tail.lower() else "UNKNOWN"
            current = {
                "name": name,
                "daemon": bool(daemon),
                "state": inferred_state,
                "frames": [],
                "locks_held": [],
                "waiting_on_lock": None,
            }
            in_ownable_sync = False
            continue

        if current is None:
            continue

        if not line.strip():
            in_ownable_sync = False
            continue

        state_match = _JCMD_STATE_RE.match(line)
        if state_match:
            # If we haven't started a thread yet, create a placeholder thread
            if current is None:
                current = {
                    "name": "unknown",
                    "daemon": False,
                    "state": state_match.group(1),
                    "frames": [],
                    "locks_held": [],
                    "waiting_on_lock": None,
                }
            else:
                current["state"] = state_match.group(1)
            continue

        if "Locked ownable synchronizers:" in line:
            in_ownable_sync = True
            continue

        if in_ownable_sync:
            sync_match = _JCMD_OWNABLE_SYNC_RE.match(line)
            if sync_match:
                current["locks_held"].append({"id": f"0x{sync_match.group(1)}", "class": sync_match.group(2)})
            continue

        frame_match = _JCMD_FRAME_RE.match(line)
        if frame_match:
            current["frames"].append(frame_match.group(1).strip())
            continue

        locked_match = _JCMD_LOCKED_RE.match(line)
        if locked_match:
            current["locks_held"].append({"id": f"0x{locked_match.group(1)}", "class": locked_match.group(2)})
            continue

        wait_lock_match = _JCMD_WAITING_LOCK_RE.match(line)
        if wait_lock_match and current["waiting_on_lock"] is None:
            current["waiting_on_lock"] = {"id": f"0x{wait_lock_match.group(1)}", "class": wait_lock_match.group(2)}
            continue

        park_match = _JCMD_PARKING_RE.match(line)
        if park_match and current["waiting_on_lock"] is None:
            current["waiting_on_lock"] = {"id": f"0x{park_match.group(1)}", "class": park_match.group(2)}
            continue

    if current is not None:
        threads.append(current)

    if deadlock_lines:
        block_text = "\n".join(deadlock_lines)
        participants = re.findall(r'^"([^"]+)":', block_text, flags=re.MULTILINE)
        held_by = re.findall(r'which is held by "([^"]+)"', block_text)
        involved = list(dict.fromkeys(participants + held_by))
        deadlocks.append(
            {
                "threads": involved,
                "summary": " <-> ".join(involved) if involved else block_text[:200],
            }
        )

    return _summarize_threads(threads, deadlocks, "jcmd")


def parse_actuator_threaddump(payload: dict[str, Any] | str) -> dict[str, Any]:
    """Parse Spring Boot Actuator `/actuator/threaddump` JSON into a compact summary."""
    data = json.loads(payload) if isinstance(payload, str) else payload
    raw_threads = data.get("threads", [])
    threads: list[dict[str, Any]] = []
    by_id: dict[int, dict[str, Any]] = {}

    for item in raw_threads:
        tid = item.get("threadId")
        name = item.get("threadName", f"thread-{tid}")
        state = item.get("threadState", "UNKNOWN")
        frames = [
            f"{f.get('className', '?')}.{f.get('methodName', '?')}({f.get('fileName') or 'Unknown'}:{f.get('lineNumber', -1)})"
            for f in item.get("stackTrace", [])
        ]
        locks_held = []
        for mon in item.get("lockedMonitors", []) + item.get("lockedSynchronizers", []):
            code = mon.get("identityHashCode")
            locks_held.append(
                {
                    "id": f"0x{code:x}" if isinstance(code, int) else str(code or mon.get("className")),
                    "class": mon.get("className", "unknown"),
                }
            )

        waiting_on = None
        lock_info = item.get("lockInfo") or {}
        if item.get("lockName") or lock_info:
            code = lock_info.get("identityHashCode")
            lid = f"0x{code:x}" if isinstance(code, int) else str(item.get("lockName") or lock_info.get("className"))
            waiting_on = {
                "id": lid,
                "class": lock_info.get("className") or str(item.get("lockName", "")).split("@", 1)[0],
                "owner_thread": item.get("lockOwnerName"),
            }

        rec = {
            "id": tid,
            "name": name,
            "state": state,
            "frames": frames,
            "locks_held": locks_held,
            "waiting_on_lock": waiting_on,
            "lock_owner_id": item.get("lockOwnerId"),
        }
        threads.append(rec)
        if isinstance(tid, int):
            by_id[tid] = rec

    # Detect lock ownership cycles for deadlocks
    deadlocks: list[dict[str, Any]] = []
    seen_cycles: set[frozenset[int]] = set()
    for tid, rec in by_id.items():
        if rec.get("state") != "BLOCKED":
            continue
        path: list[int] = []
        pos: dict[int, int] = {}
        curr: int | None = tid
        while curr is not None and curr in by_id:
            if curr in pos:
                cycle_ids = path[pos[curr]:]
                key = frozenset(cycle_ids)
                if key not in seen_cycles and len(cycle_ids) >= 2:
                    seen_cycles.add(key)
                    names = [by_id[i]["name"] for i in cycle_ids]
                    deadlocks.append({"threads": names, "summary": " -> ".join(names + [names[0]])})
                break
            pos[curr] = len(path)
            path.append(curr)
            owner_id = by_id[curr].get("lock_owner_id")
            curr = owner_id if isinstance(owner_id, int) and owner_id >= 0 else None

    return _summarize_threads(threads, deadlocks, "actuator")


def parse_thread_dump(raw: str) -> dict[str, Any]:
    """Auto-detect jcmd text vs Actuator JSON thread dump and summarize."""
    stripped = raw.lstrip()
    if stripped.startswith("{"):
        return parse_actuator_threaddump(stripped)
    return parse_jcmd_thread_dump(raw)


