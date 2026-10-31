"""Wayfound API: detect -> trace -> check -> recover -> approve -> verify."""

from __future__ import annotations

import json
import threading
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from . import config, executor, graph, narrator
from .engine import Model


@asynccontextmanager
async def lifespan(_: FastAPI):
    threading.Thread(target=executor.warm_up, daemon=True).start()
    yield


app = FastAPI(title="Wayfound", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
                   allow_methods=["*"], allow_headers=["*"])


# ---------------------------------------------------------------- helpers

def current_assignment(problem: dict) -> dict:
    return {s["id"]: s["venue"] for s in problem["sessions"]}


def disrupted_sessions(problem: dict) -> list[str]:
    closed = {v["id"] for v in problem["venues"] if not v.get("available", True)}
    return [s["id"] for s in problem["sessions"] if s["venue"] in closed]


def quick_fix(problem: dict) -> dict | None:
    """What a rushed organiser does: the smallest free room with enough seats. Nothing else is checked."""
    m = Model(problem)
    assign = current_assignment(problem)
    disrupted = disrupted_sessions(problem)
    if not disrupted:
        return None
    moves = []
    for sid in disrupted:
        s = m.sessions[sid]
        n = m.attendee_count(sid)
        options = sorted(
            (v for v in problem["venues"]
             if v.get("available", True) and v["capacity"] >= n
             and not any(assign.get(o) == v["id"] and o != sid and _overlap(s, m.sessions[o]) for o in m.sessions)),
            key=lambda v: (v["capacity"], v["id"]))
        if options:
            moves.append({"sessionId": sid, "sessionTitle": s["title"], "from": assign[sid],
                          "to": options[0]["id"], "toName": options[0]["name"],
                          "attendees": n, "capacity": options[0]["capacity"]})
            assign[sid] = options[0]["id"]
    violations = m.check(assign)
    return {"rule": "Smallest free room with enough seats (capacity-only)", "moves": moves,
            "violations": violations, "unresolved": len(violations),
            "looksFine": all(mv["capacity"] >= mv["attendees"] for mv in moves) and bool(moves)}


def _overlap(a, b):
    from .engine import _overlaps
    return _overlaps(a, b)


def public_state() -> dict:
    problem = graph.load_problem()
    m = Model(problem)
    violations = m.check(current_assignment(problem))
    holders = problem["participants"]
    sessions = []
    for s in problem["sessions"]:
        needs = [{"id": pid, "name": holders[pid]["name"], "requirements": holders[pid]["requirements"]}
                 for pid in s["attendees"] if pid in holders]
        sessions.append({k: v for k, v in s.items() if k != "attendees"} | {"needs": needs})
    incident = graph.open_incident()
    return {
        "event": graph.event(),
        "venues": problem["venues"],
        "sessions": sessions,
        "participantTotal": problem["participantTotal"],
        "requirementHolders": [{"id": k} | v for k, v in holders.items()],
        "violations": violations,
        "incident": incident,
        "quickFix": quick_fix(problem),
        "history": graph.history(10),
    }


def guard(fn):
    try:
        return fn()
    except executor.ExecutionError as e:
        raise HTTPException(502, str(e))
    except RuntimeError as e:
        raise HTTPException(409, str(e))


# ---------------------------------------------------------------- routes

@app.get("/api/health")
def health():
    out = {"daytona": executor.status(),
           "nosana": {"enabled": narrator.enabled(), "model": config.NOSANA_LLM_MODEL or None}}
    try:
        out["neo4j"] = graph.ping()
    except Exception as e:
        out["neo4j"] = {"ok": False, "error": f"{type(e).__name__}: {e}"}
    return out


@app.get("/api/state")
def state():
    return guard(public_state)


@app.post("/api/reset")
def reset(full: bool = False):
    """Restore the scenario. History is kept so the next run can learn from it, unless full=true."""
    counts = graph.reset(full=full)
    return {"seeded": counts, "state": public_state()}


class InterpretIn(BaseModel):
    text: str


@app.post("/api/interpret")
def interpret(body: InterpretIn):
    venues = graph.load_problem()["venues"]
    return narrator.interpret(body.text, venues)


class CloseIn(BaseModel):
    note: str = ""
    source: str = "dashboard"


@app.post("/api/venues/{venue_id}/close")
def close_venue(venue_id: str, body: CloseIn):
    """Detect: the organiser marks a venue unavailable. Then trace and check."""
    try:
        venue = graph.set_availability(venue_id, False)
    except KeyError:
        raise HTTPException(404, f"Unknown venue {venue_id}")
    incident = graph.open_incident() or graph.create_incident(
        venue_id, body.note or f"{venue['name']} is unavailable", body.source)
    return {"incident": incident, "trace": graph.trace(venue_id),
            "memory": graph.precedent(incident["venueId"], incident["id"]), "state": public_state()}


class AvailabilityIn(BaseModel):
    available: bool


@app.post("/api/venues/{venue_id}/availability")
def set_availability(venue_id: str, body: AvailabilityIn):
    try:
        graph.set_availability(venue_id, body.available)
    except KeyError:
        raise HTTPException(404, f"Unknown venue {venue_id}")
    return public_state()


@app.get("/api/trace/{venue_id}")
def trace(venue_id: str):
    return graph.trace(venue_id)


@app.post("/api/recover")
def recover():
    """Recover: run the solver in a Daytona sandbox against live graph state."""
    def go():
        problem = graph.load_problem()
        before = current_assignment(problem)
        if not disrupted_sessions(problem) and not Model(problem).check(before):
            raise RuntimeError("Nothing to recover: every session already satisfies its hard constraints.")
        incident = graph.open_incident()
        memory = graph.precedent(incident["venueId"], incident["id"]) if incident else None
        hints = {m["session"]: m["to"] for m in (memory or {}).get("moves", [])}
        proposal, execution = executor.run_engine({"op": "solve", "problem": problem, "assignment": before,
                                                   "precedent": hints})
        ra = graph.record_recovery(incident["id"] if incident else None, proposal, execution, before)
        if memory and memory.get("recoveryId"):
            graph.link_precedent(ra["id"], memory["recoveryId"])
        venues = {v["id"]: v for v in problem["venues"]}
        explanation = narrator.explain(proposal, quick_fix(problem), venues, memory)
        return {"recovery": ra, "proposal": proposal, "execution": execution, "explanation": explanation,
                "memory": memory}
    return guard(go)


@app.post("/api/recoveries/{ra_id}/approve")
def approve(ra_id: str):
    """Approve and apply, then verify independently from fresh graph state."""
    def go():
        ra = graph.get_recovery(ra_id)
        if ra is None:
            raise HTTPException(404, "Unknown recovery")
        if ra["status"] != "proposed":
            raise RuntimeError(f"Recovery is {ra['status']}; only a proposed recovery can be approved.")
        moves = json.loads(ra["movesJson"])
        graph.apply_assignment(ra_id, moves)
        problem = graph.load_problem()  # re-read: verification must not trust the proposal
        result, execution = executor.run_engine({"op": "verify", "problem": problem,
                                                 "assignment": current_assignment(problem)})
        ver = graph.record_verification(ra_id, result, execution)
        return {"verification": ver | {"violations": result["violations"], "sessions": result.get("sessions")},
                "execution": execution, "state": public_state()}
    return guard(go)


@app.get("/api/memory/{venue_id}")
def memory(venue_id: str):
    inc = graph.open_incident()
    return graph.precedent(venue_id, inc["id"] if inc else None)


@app.get("/api/graph/impact")
def impact_graph():
    inc = graph.open_incident()
    if not inc:
        raise HTTPException(404, "No open incident")
    return graph.impact_graph(inc["id"])


@app.get("/api/graph/provenance/{ra_id}")
def provenance_graph(ra_id: str):
    return graph.provenance_graph(ra_id)


@app.get("/api/history")
def history():
    return graph.history(20)
