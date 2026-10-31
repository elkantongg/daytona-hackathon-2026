"""Wayfound constraint engine.

Self-contained (standard library only) so the exact same source runs inside a
Daytona sandbox and, when explicitly allowed, as a local fallback. It does two
jobs:

* ``check``  - evaluate every hard constraint for a full venue assignment.
* ``solve``  - search for a feasible reassignment that moves as few sessions
               as possible, preferring the tightest-fitting rooms.

The engine is deterministic: the same problem always yields the same answer.
No language model is involved in deciding feasibility.

Input (JSON on stdin, or the ``PROBLEM_JSON`` env var):
    {"op": "solve" | "check" | "verify", "problem": {...}, "assignment": {...}}

Output: one line ``WAYFOUND_RESULT:<json>`` on stdout.
"""

from __future__ import annotations

import json
import os
import platform
import sys
import time

RESULT_MARKER = "WAYFOUND_RESULT:"

# Participant requirement -> predicate on a venue. Kept explicit on purpose:
# accessibility is decided by recorded facts, never inferred.
REQUIREMENT_RULES = {
    "step_free": {
        "test": lambda v: bool(v.get("stepFree")),
        "explain": "has no step-free route",
    },
    "hearing_loop": {
        "test": lambda v: "hearing_loop" in v.get("resources", []),
        "explain": "has no hearing loop",
    },
    "wheelchair_space": {
        "test": lambda v: bool(v.get("wheelchairSpaces", 0)),
        "explain": "has no wheelchair spaces",
    },
}


def _minutes(hhmm: str) -> int:
    h, m = hhmm.split(":")
    return int(h) * 60 + int(m)


def _overlaps(a: dict, b: dict) -> bool:
    return _minutes(a["start"]) < _minutes(b["end"]) and _minutes(b["start"]) < _minutes(a["end"])


class Model:
    def __init__(self, problem: dict):
        self.venues = {v["id"]: v for v in problem["venues"]}
        self.sessions = {s["id"]: s for s in problem["sessions"]}
        self.participants = problem.get("participants", {})
        # Requirement holders per session, precomputed once.
        self.needs = {}
        for sid, s in self.sessions.items():
            holders = []
            for pid in s.get("attendees", []):
                for req in self.participants.get(pid, {}).get("requirements", []):
                    holders.append((pid, req))
            self.needs[sid] = holders

    def attendee_count(self, sid: str) -> int:
        s = self.sessions[sid]
        return s.get("attendeeCount", len(s.get("attendees", [])))

    def venue_violations(self, sid: str, vid: str) -> list[dict]:
        """Hard constraints that depend only on (session, venue)."""
        s = self.sessions[sid]
        v = self.venues.get(vid)
        out: list[dict] = []
        if v is None:
            return [_violation("UNKNOWN_VENUE", s, vid, f"Venue {vid} does not exist")]
        if not v.get("available", True):
            out.append(_violation("VENUE_UNAVAILABLE", s, vid, f"{v['name']} is unavailable"))
        n = self.attendee_count(sid)
        if n > v["capacity"]:
            out.append(_violation(
                "CAPACITY", s, vid,
                f"{n} attendees exceed {v['name']} capacity of {v['capacity']}",
            ))
        missing = [r for r in s.get("requiredResources", []) if r not in v.get("resources", [])]
        if missing:
            out.append(_violation(
                "RESOURCE", s, vid,
                f"{v['name']} lacks required equipment: {', '.join(missing)}",
                resources=missing,
            ))
        for pid, req in self.needs[sid]:
            rule = REQUIREMENT_RULES.get(req)
            if rule is None:
                out.append(_violation(
                    "UNKNOWN_REQUIREMENT", s, vid,
                    f"Requirement '{req}' has no rule; cannot be verified",
                    participantId=pid, requirement=req,
                ))
            elif not rule["test"](v):
                name = self.participants.get(pid, {}).get("name", pid)
                out.append(_violation(
                    "ACCESS", s, vid,
                    f"{name} ({pid}) requires {req.replace('_', '-')} access, but {v['name']} {rule['explain']}",
                    participantId=pid, requirement=req,
                ))
        return out

    def check(self, assignment: dict) -> list[dict]:
        out: list[dict] = []
        for sid in sorted(self.sessions):
            vid = assignment.get(sid)
            if vid is None:
                out.append(_violation("UNASSIGNED", self.sessions[sid], None, "Session has no venue"))
                continue
            out.extend(self.venue_violations(sid, vid))
        ids = sorted(self.sessions)
        for i, a in enumerate(ids):
            for b in ids[i + 1:]:
                if assignment.get(a) and assignment.get(a) == assignment.get(b) \
                        and _overlaps(self.sessions[a], self.sessions[b]):
                    v = self.venues.get(assignment[a], {"name": assignment[a]})
                    out.append(_violation(
                        "CLASH", self.sessions[a], assignment[a],
                        f"{v['name']} is double-booked: {self.sessions[a]['title']} and {self.sessions[b]['title']} overlap",
                        otherSessionId=b,
                    ))
        return out

    def checks_run(self) -> dict:
        """How many individual hard-constraint checks a full check performs."""
        n = len(self.sessions)
        per_session = sum(
            3 + len(self.sessions[s].get("requiredResources", [])) + len(self.needs[s])
            for s in self.sessions
        )
        return {"sessions": n, "constraintChecks": per_session + n * (n - 1) // 2}


def _violation(code, session, vid, detail, **extra):
    d = {"code": code, "sessionId": session["id"], "sessionTitle": session.get("title"),
         "venueId": vid, "detail": detail}
    d.update(extra)
    return d


def solve(problem: dict, current: dict, precedent: dict | None = None) -> dict:
    """Branch and bound: minimise sessions moved, then unproven rooms, then wasted seats."""
    m = Model(problem)
    started = time.perf_counter()

    # Per-session feasible venues (independent of other sessions).
    domains: dict[str, list[str]] = {}
    rejected: dict[str, list[dict]] = {}
    for sid in m.sessions:
        ok, bad = [], []
        for vid in sorted(m.venues):
            vs = m.venue_violations(sid, vid)
            (bad if vs else ok).append((vid, vs))
        cur = current.get(sid)
        # Keep the current venue first, then tightest fit.
        ok.sort(key=lambda t: (t[0] != cur, m.venues[t[0]]["capacity"] - m.attendee_count(sid), t[0]))
        domains[sid] = [vid for vid, _ in ok]
        rejected[sid] = [{"venueId": vid, "venueName": m.venues[vid]["name"],
                          "reasons": [x["detail"] for x in vs]} for vid, vs in bad]

    disrupted = sorted(sid for sid in m.sessions if m.venue_violations(sid, current.get(sid, "")))

    # Precedent: a previously verified plan for the same disruption, read from the graph.
    # It is re-checked against live state, and among equally small plans the solver
    # prefers rooms that have already been proven to work. It never overrides a hard constraint.
    precedent = {s: v for s, v in (precedent or {}).items() if s in m.sessions}
    precedent_report = None
    if precedent:
        replay = dict(current)
        replay.update(precedent)
        pv = m.check(replay)
        precedent_report = {"moves": precedent, "valid": not pv,
                            "violations": list(dict.fromkeys(x["detail"] for x in pv))}
        for sid, vid in precedent.items():
            if vid in domains[sid]:
                domains[sid].sort(key=lambda x: (x != current.get(sid), x != vid))

    empty = [sid for sid in m.sessions if not domains[sid]]
    if empty:
        return {
            "status": "infeasible",
            "reason": "No venue satisfies every hard constraint for: "
                      + ", ".join(m.sessions[s]["title"] for s in sorted(empty)),
            "blockedSessions": [
                {"sessionId": s, "sessionTitle": m.sessions[s]["title"],
                 "attendees": m.attendee_count(s), "rejectedVenues": rejected[s]}
                for s in sorted(empty)
            ],
            "disrupted": disrupted,
            "precedent": precedent_report,
            "nodesExplored": 0,
            "elapsedMs": round((time.perf_counter() - started) * 1000, 2),
        }

    # Most constrained first, disrupted sessions before the rest.
    order = sorted(m.sessions, key=lambda s: (s not in disrupted, len(domains[s]), s))
    best = {"cost": None, "assignment": None}
    nodes = 0
    assign: dict[str, str] = {}

    def cost_of(sid, vid):
        if vid == current.get(sid):
            return (0, 0, 0)
        unproven = 0 if precedent.get(sid) == vid else 1
        return (1, unproven, m.venues[vid]["capacity"] - m.attendee_count(sid))

    def clashes(sid, vid):
        s = m.sessions[sid]
        return any(v == vid and _overlaps(s, m.sessions[o]) for o, v in assign.items())

    def search(i, cost):
        nonlocal nodes
        nodes += 1
        if best["cost"] is not None and cost >= best["cost"]:
            return
        if i == len(order):
            best["cost"] = cost
            best["assignment"] = dict(assign)
            return
        sid = order[i]
        for vid in domains[sid]:
            if clashes(sid, vid):
                continue
            c = cost_of(sid, vid)
            assign[sid] = vid
            search(i + 1, (cost[0] + c[0], cost[1] + c[1], cost[2] + c[2]))
            del assign[sid]

    search(0, (0, 0, 0))
    elapsed = round((time.perf_counter() - started) * 1000, 2)
    if precedent_report is not None and best["assignment"] is not None:
        precedent_report["followed"] = all(best["assignment"].get(s) == v for s, v in precedent.items())

    if best["assignment"] is None:
        return {
            "status": "infeasible",
            "reason": "Every venue combination leaves at least one double-booking; "
                      "not enough suitable rooms at the same time.",
            "blockedSessions": [
                {"sessionId": s, "sessionTitle": m.sessions[s]["title"],
                 "attendees": m.attendee_count(s), "rejectedVenues": rejected[s],
                 "candidateVenues": domains[s]}
                for s in disrupted
            ],
            "disrupted": disrupted,
            "precedent": precedent_report,
            "nodesExplored": nodes,
            "elapsedMs": elapsed,
        }

    a = best["assignment"]
    moves = []
    for sid in sorted(a, key=lambda s: (s not in disrupted, s)):
        if a[sid] != current.get(sid):
            v = m.venues[a[sid]]
            moves.append({
                "sessionId": sid, "sessionTitle": m.sessions[sid]["title"],
                "from": current.get(sid), "to": a[sid], "toName": v["name"],
                "attendees": m.attendee_count(sid), "capacity": v["capacity"],
                "reason": "disrupted" if sid in disrupted else "frees a suitable room",
            })
    remaining = m.check(a)
    return {
        "status": "feasible" if not remaining else "infeasible",
        "assignment": a,
        "moves": moves,
        "sessionsMoved": best["cost"][0],
        "spareSeats": best["cost"][2],
        "precedent": precedent_report,
        "violationsAfter": remaining,
        "disrupted": disrupted,
        "rejectedVenues": {s: rejected[s] for s in disrupted},
        "nodesExplored": nodes,
        "elapsedMs": elapsed,
    }


def run(payload: dict) -> dict:
    op = payload.get("op")
    problem = payload["problem"]
    assignment = payload.get("assignment") or {s["id"]: s.get("venue") for s in problem["sessions"]}
    m = Model(problem)
    if op == "solve":
        result = solve(problem, assignment, payload.get("precedent"))
    elif op in ("check", "verify"):
        violations = m.check(assignment)
        result = {"violations": violations, "unresolved": len(violations), **m.checks_run()}
    else:
        raise ValueError(f"unknown op {op!r}")
    result["op"] = op
    result["runtime"] = {"python": platform.python_version(), "host": platform.node()}
    return result


def main() -> None:
    raw = os.environ.get("PROBLEM_JSON") or sys.stdin.read()
    print(RESULT_MARKER + json.dumps(run(json.loads(raw))))


if __name__ == "__main__":
    main()
