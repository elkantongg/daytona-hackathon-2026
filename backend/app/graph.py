"""Neo4j access: the operational source of truth for the event.

Graph model (every node also carries the :Wayfound label so a reset never
touches anything else in the database):

    (:Event)-[:HAS_SESSION]->(:Session)-[:ASSIGNED_TO]->(:Venue)
    (:Venue)-[:HAS_RESOURCE]->(:Resource)<-[:REQUIRES]-(:Session)
    (:Participant)-[:ATTENDS]->(:Session)
    (:Participant)-[:HAS_REQUIREMENT]->(:Requirement)
    (:Incident)-[:CLOSED]->(:Venue)
    (:RecoveryAction)-[:RESOLVES]->(:Incident)
    (:RecoveryAction)-[:REASSIGNED {from, to}]->(:Session)
    (:RecoveryAction)-[:VERIFIED_BY]->(:Verification)
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone

from neo4j import GraphDatabase

from . import config
from .scenario import build

_driver = None


def driver():
    global _driver
    if _driver is None:
        if not (config.NEO4J_URI and config.NEO4J_PASSWORD):
            raise RuntimeError("NEO4J_URI and NEO4J_PASSWORD must be set in .env")
        _driver = GraphDatabase.driver(config.NEO4J_URI, auth=(config.NEO4J_USERNAME, config.NEO4J_PASSWORD),
                                       notifications_min_severity="OFF")
    return _driver


def q(cypher: str, **params) -> list[dict]:
    records, _, _ = driver().execute_query(cypher, params, database_=config.NEO4J_DATABASE)
    return [r.data() for r in records]


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def new_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8].upper()}"


def ping() -> dict:
    row = q("CALL dbms.components() YIELD name, versions, edition RETURN name, versions[0] AS version, edition")[0]
    seeded = q("MATCH (e:Event:Wayfound) RETURN count(e) AS n")[0]["n"] > 0
    return {"ok": True, "version": row["version"], "edition": row["edition"], "seeded": seeded,
            "database": config.NEO4J_DATABASE or "default"}


# ---------------------------------------------------------------- seeding

def reset(full: bool = False) -> dict:
    """Restore the scenario. Keeps recovery history (the system's memory) unless ``full``."""
    seeded = q("MATCH (e:Event:Wayfound) RETURN count(e) AS n")[0]["n"] > 0
    if seeded and not full:
        return restore_scenario()
    data = build()
    q("MATCH (n:Wayfound) DETACH DELETE n")
    for label, key in (("Event", "id"), ("Venue", "id"), ("Session", "id"), ("Participant", "id"),
                       ("Resource", "id"), ("Requirement", "id"), ("Incident", "id"),
                       ("RecoveryAction", "id"), ("Verification", "id")):
        q(f"CREATE CONSTRAINT {label.lower()}_{key} IF NOT EXISTS FOR (n:{label}) REQUIRE n.{key} IS UNIQUE")

    q("CREATE (:Event:Wayfound $e)", e=data["event"])
    q("UNWIND $rows AS r CREATE (:Resource:Wayfound {id: r.id, label: r.label})",
      rows=[{"id": k, "label": v} for k, v in data["resources"].items()])
    q("UNWIND $rows AS r CREATE (:Requirement:Wayfound {id: r.id, label: r.label})",
      rows=[{"id": k, "label": v} for k, v in data["requirements"].items()])
    q("""
      UNWIND $rows AS r
      CREATE (v:Venue:Wayfound {id: r.id, name: r.name, building: r.building, level: r.level,
              capacity: r.capacity, stepFree: r.stepFree, wheelchairSpaces: r.wheelchairSpaces,
              accessNote: coalesce(r.accessNote, ''), available: true})
      WITH v, r UNWIND r.resources AS res
      MATCH (x:Resource:Wayfound {id: res}) CREATE (v)-[:HAS_RESOURCE]->(x)
    """, rows=data["venues"])
    q("""
      MATCH (e:Event:Wayfound)
      UNWIND $rows AS r
      MATCH (v:Venue:Wayfound {id: r.venue})
      CREATE (e)-[:HAS_SESSION]->(s:Session:Wayfound {id: r.id, title: r.title, start: r.start, end: r.end})
             -[:ASSIGNED_TO]->(v)
      WITH s, r UNWIND r.requiredResources AS res
      MATCH (x:Resource:Wayfound {id: res}) CREATE (s)-[:REQUIRES]->(x)
    """, rows=data["sessions"])
    q("""
      UNWIND $rows AS r
      CREATE (p:Participant:Wayfound {id: r.id, name: r.name, email: r.email})
      WITH p, r UNWIND r.requirements AS req
      MATCH (x:Requirement:Wayfound {id: req}) CREATE (p)-[:HAS_REQUIREMENT]->(x)
    """, rows=data["participants"])
    q("""
      UNWIND $rows AS r
      MATCH (s:Session:Wayfound {id: r.id})
      UNWIND r.attendees AS pid
      MATCH (p:Participant:Wayfound {id: pid}) CREATE (p)-[:ATTENDS]->(s)
    """, rows=[{"id": s["id"], "attendees": s["attendees"]} for s in data["sessions"]])
    link_provisions()
    return counts_summary()


def link_provisions() -> None:
    """(:Venue)-[:PROVIDES]->(:Requirement): which rooms satisfy which personal requirement."""
    q("MATCH (:Venue:Wayfound)-[r:PROVIDES]->() DELETE r")
    q("""MATCH (v:Venue:Wayfound {stepFree: true}), (r:Requirement:Wayfound {id: 'step_free'})
         CREATE (v)-[:PROVIDES]->(r)""")
    q("""MATCH (v:Venue:Wayfound)-[:HAS_RESOURCE]->(:Resource {id: 'hearing_loop'}),
               (r:Requirement:Wayfound {id: 'hearing_loop'})
         CREATE (v)-[:PROVIDES]->(r)""")
    q("""MATCH (v:Venue:Wayfound) WHERE v.wheelchairSpaces > 0
         MATCH (r:Requirement:Wayfound {id: 'wheelchair_space'})
         CREATE (v)-[:PROVIDES]->(r)""")


def restore_scenario() -> dict:
    """Reopen every room and put sessions back where the timetable had them. History stays."""
    original = [{"id": s["id"], "venue": s["venue"]} for s in build()["sessions"]]
    q("MATCH (v:Venue:Wayfound) SET v.available = true")
    q("""UNWIND $rows AS r
         MATCH (s:Session:Wayfound {id: r.id})-[a:ASSIGNED_TO]->()
         DELETE a
         WITH s, r MATCH (v:Venue:Wayfound {id: r.venue})
         CREATE (s)-[:ASSIGNED_TO]->(v)""", rows=original)
    q("MATCH (i:Incident:Wayfound {status: 'open'}) SET i.status = 'withdrawn'")
    q("MATCH (ra:RecoveryAction:Wayfound {status: 'proposed'}) SET ra.status = 'superseded'")
    if not q("MATCH (:Venue:Wayfound)-[r:PROVIDES]->() RETURN count(r) AS n")[0]["n"]:
        link_provisions()
    return counts_summary() | {"historyKept": True}


def counts_summary() -> dict:
    counts = q("""
      MATCH (n:Wayfound) WITH labels(n) AS l
      RETURN [x IN l WHERE x <> 'Wayfound'][0] AS label, count(*) AS n ORDER BY label
    """)
    rels = q("MATCH (:Wayfound)-[r]->(:Wayfound) RETURN count(r) AS n")[0]["n"]
    return {"nodes": {c["label"]: c["n"] for c in counts}, "relationships": rels}


# ---------------------------------------------------------------- reading state

def load_problem() -> dict:
    """Current event state from Neo4j, in the engine's problem format."""
    venues = q("""
      MATCH (v:Venue:Wayfound)
      OPTIONAL MATCH (v)-[:HAS_RESOURCE]->(r:Resource)
      RETURN v {.*} AS v, collect(r.id) AS resources ORDER BY v.id
    """)
    sessions = q("""
      MATCH (s:Session:Wayfound)-[:ASSIGNED_TO]->(v:Venue)
      OPTIONAL MATCH (s)-[:REQUIRES]->(r:Resource)
      WITH s, v, collect(r.id) AS resources
      OPTIONAL MATCH (p:Participant)-[:ATTENDS]->(s)
      RETURN s {.*} AS s, v.id AS venue, resources, collect(p.id) AS attendees ORDER BY s.start, s.id
    """)
    holders = q("""
      MATCH (p:Participant:Wayfound)-[:HAS_REQUIREMENT]->(r:Requirement)
      RETURN p.id AS id, p.name AS name, collect(r.id) AS requirements
    """)
    participants = {h["id"]: {"name": h["name"], "requirements": h["requirements"]} for h in holders}
    total = q("MATCH (p:Participant:Wayfound) RETURN count(p) AS n")[0]["n"]
    return {
        "venues": [r["v"] | {"resources": sorted(r["resources"])} for r in venues],
        "sessions": [r["s"] | {"venue": r["venue"], "requiredResources": sorted(r["resources"]),
                               "attendees": sorted(r["attendees"]), "attendeeCount": len(r["attendees"])}
                     for r in sessions],
        # Only requirement holders are needed for checks; everyone else has no constraint.
        "participants": participants,
        "participantTotal": total,
    }


def event() -> dict:
    rows = q("MATCH (e:Event:Wayfound) RETURN e {.*} AS e")
    return rows[0]["e"] if rows else {}


TRACE_CYPHER = """MATCH (v:Venue {id: $venueId})<-[:ASSIGNED_TO]-(s:Session)
OPTIONAL MATCH (s)-[:REQUIRES]->(res:Resource)
WITH v, s, collect(DISTINCT res.label) AS equipment
OPTIONAL MATCH (p:Participant)-[:ATTENDS]->(s)
WITH v, s, equipment, count(DISTINCT p) AS attendees
OPTIONAL MATCH (h:Participant)-[:ATTENDS]->(s),
               (h)-[:HAS_REQUIREMENT]->(req:Requirement)
RETURN s.id AS session, s.title AS title, s.start AS start,
       attendees, equipment,
       collect(DISTINCT {id: h.id, name: h.name,
                         requirement: req.label}) AS needs"""


def trace(venue_id: str) -> dict:
    rows = q(TRACE_CYPHER, venueId=venue_id)
    for r in rows:
        r["needs"] = [n for n in r["needs"] if n.get("id")]
    return {"cypher": TRACE_CYPHER, "params": {"venueId": venue_id}, "rows": rows,
            "sessions": len(rows), "attendees": sum(r["attendees"] for r in rows),
            "requirementHolders": sum(len(r["needs"]) for r in rows)}


# ---------------------------------------------------------------- writing

def set_availability(venue_id: str, available: bool) -> dict:
    rows = q("MATCH (v:Venue:Wayfound {id: $id}) SET v.available = $a RETURN v {.*} AS v",
             id=venue_id, a=available)
    if not rows:
        raise KeyError(venue_id)
    return rows[0]["v"]


def create_incident(venue_id: str, note: str, source: str) -> dict:
    inc = {"id": new_id("INC"), "createdAt": now(), "venueId": venue_id, "note": note,
           "source": source, "status": "open"}
    q("""MATCH (v:Venue:Wayfound {id: $venueId})
         CREATE (i:Incident:Wayfound $inc)-[:CLOSED]->(v)""", venueId=venue_id, inc=inc)
    return inc


def open_incident() -> dict | None:
    rows = q("""MATCH (i:Incident:Wayfound {status: 'open'})
                RETURN i {.*} AS i ORDER BY i.createdAt DESC LIMIT 1""")
    return rows[0]["i"] if rows else None


def record_recovery(incident_id: str | None, proposal: dict, execution: dict, before: dict) -> dict:
    ra = {
        "id": new_id("RA"), "createdAt": now(), "status": "proposed" if proposal["status"] == "feasible" else "infeasible",
        "engine": execution["engine"], "sandboxId": execution.get("sandboxId") or "",
        "elapsedMs": execution.get("elapsedMs", 0), "nodesExplored": proposal.get("nodesExplored", 0),
        "movesJson": json.dumps(proposal.get("moves", [])),
        "assignmentJson": json.dumps(proposal.get("assignment", {})),
        "beforeJson": json.dumps(before),
        "summary": proposal.get("reason", "") or f"{len(proposal.get('moves', []))} session(s) reassigned",
    }
    # Only the newest proposal can be approved; older ones were computed against stale state.
    q("MATCH (old:RecoveryAction:Wayfound {status: 'proposed'}) SET old.status = 'superseded'")
    q("CREATE (:RecoveryAction:Wayfound $ra)", ra=ra)
    if incident_id:
        q("""MATCH (ra:RecoveryAction:Wayfound {id: $ra}), (i:Incident:Wayfound {id: $i})
             CREATE (ra)-[:RESOLVES]->(i)""", ra=ra["id"], i=incident_id)
    return ra


def get_recovery(ra_id: str) -> dict | None:
    rows = q("""MATCH (ra:RecoveryAction:Wayfound {id: $id})
                OPTIONAL MATCH (ra)-[:RESOLVES]->(i:Incident)
                RETURN ra {.*} AS ra, i.id AS incidentId""", id=ra_id)
    if not rows:
        return None
    return rows[0]["ra"] | {"incidentId": rows[0]["incidentId"]}


def apply_assignment(ra_id: str, moves: list[dict]) -> None:
    """Move sessions in one transaction, guarding that each is still where the plan expects."""
    def work(tx):
        for m in moves:
            res = tx.run("""
              MATCH (ra:RecoveryAction:Wayfound {id: $ra})
              MATCH (s:Session:Wayfound {id: $sid})-[old:ASSIGNED_TO]->(f:Venue {id: $from})
              MATCH (t:Venue:Wayfound {id: $to})
              DELETE old
              CREATE (s)-[:ASSIGNED_TO]->(t)
              CREATE (ra)-[:REASSIGNED {from: $from, to: $to, at: $at}]->(s)
              RETURN s.id AS id
            """, ra=ra_id, sid=m["sessionId"], to=m["to"], at=now(), **{"from": m["from"]}).data()
            if not res:
                raise RuntimeError(f"State changed since the proposal: {m['sessionId']} is no longer in {m['from']}")
        tx.run("MATCH (ra:RecoveryAction:Wayfound {id: $id}) SET ra.status = 'applied', ra.appliedAt = $at",
               id=ra_id, at=now())

    with driver().session(database=config.NEO4J_DATABASE) as s:
        s.execute_write(work)


def record_verification(ra_id: str, result: dict, execution: dict) -> dict:
    ver = {
        "id": new_id("VER"), "createdAt": now(), "engine": execution["engine"],
        "sandboxId": execution.get("sandboxId") or "", "unresolved": result["unresolved"],
        "constraintChecks": result.get("constraintChecks", 0),
        "violationsJson": json.dumps(result["violations"]),
        "passed": result["unresolved"] == 0,
    }
    status = "verified" if ver["passed"] else "verification_failed"
    q("""MATCH (ra:RecoveryAction:Wayfound {id: $ra})
         CREATE (ra)-[:VERIFIED_BY]->(:Verification:Wayfound $ver)
         SET ra.status = $status
         WITH ra
         OPTIONAL MATCH (ra)-[:RESOLVES]->(i:Incident)
         FOREACH (_ IN CASE WHEN $passed THEN [1] ELSE [] END | SET i.status = 'resolved', i.resolvedAt = $at)""",
      ra=ra_id, ver=ver, status=status, passed=ver["passed"], at=now())
    return ver | {"status": status}


def history(limit: int = 20) -> list[dict]:
    rows = q("""
      MATCH (ra:RecoveryAction:Wayfound)
      OPTIONAL MATCH (ra)-[:RESOLVES]->(i:Incident)-[:CLOSED]->(v:Venue)
      OPTIONAL MATCH (ra)-[:VERIFIED_BY]->(ver:Verification)
      RETURN ra {.id, .createdAt, .status, .engine, .sandboxId, .summary, .movesJson, .elapsedMs} AS ra,
             i {.id, .note, .createdAt} AS incident, v.name AS venue,
             ver {.id, .unresolved, .constraintChecks, .passed, .createdAt, .engine, .sandboxId} AS verification
      ORDER BY ra.createdAt DESC LIMIT $limit
    """, limit=limit)
    for r in rows:
        r["ra"]["moves"] = json.loads(r["ra"].pop("movesJson") or "[]")
    return rows


# ---------------------------------------------------------------- memory

PRECEDENT_CYPHER = """MATCH (prior:Incident)-[:CLOSED]->(v:Venue {id: $venueId})
WHERE prior.id <> $exclude
WITH v, count(prior) AS incidents
OPTIONAL MATCH (ra:RecoveryAction {status: 'verified'})
              -[:RESOLVES]->(:Incident)-[:CLOSED]->(v)
WITH incidents, ra ORDER BY ra.createdAt DESC LIMIT 1
OPTIONAL MATCH (ra)-[m:REASSIGNED]->(s:Session)
OPTIONAL MATCH (ra)-[:VERIFIED_BY]->(ver:Verification)
RETURN incidents, ra.id AS recoveryId, ra.createdAt AS at,
       ver.id AS verificationId,
       collect({session: s.id, from: m.from, to: m.to}) AS moves"""


def precedent(venue_id: str, exclude_incident: str | None) -> dict:
    """What the graph remembers about this venue failing before, and what fixed it."""
    rows = q(PRECEDENT_CYPHER, venueId=venue_id, exclude=exclude_incident or "")
    r = rows[0] if rows else {"incidents": 0, "recoveryId": None, "moves": []}
    moves = [m for m in r.get("moves", []) if m.get("session")]
    return {"priorIncidents": r.get("incidents", 0), "recoveryId": r.get("recoveryId"),
            "at": r.get("at"), "verificationId": r.get("verificationId"), "moves": moves,
            "cypher": PRECEDENT_CYPHER}


def link_precedent(ra_id: str, prior_ra_id: str) -> None:
    q("""MATCH (ra:RecoveryAction:Wayfound {id: $ra}), (p:RecoveryAction:Wayfound {id: $p})
         MERGE (ra)-[:INFORMED_BY]->(p)""", ra=ra_id, p=prior_ra_id)


# ---------------------------------------------------------------- graph views

IMPACT_CYPHER = """MATCH (i:Incident {id: $incidentId})-[:CLOSED]->(v:Venue)
      <-[:ASSIGNED_TO]-(s:Session)
OPTIONAL MATCH (s)<-[:ATTENDS]-(a:Participant)
WITH i, v, s, count(a) AS attendees
OPTIONAL MATCH (s)<-[:ATTENDS]-(p:Participant)-[:HAS_REQUIREMENT]->(r:Requirement)
OPTIONAL MATCH (ok:Venue {available: true})-[:PROVIDES]->(r)
WHERE ok.capacity >= attendees
OPTIONAL MATCH (trap:Venue {available: true})
WHERE r IS NOT NULL AND trap.capacity >= attendees
  AND NOT (trap)-[:PROVIDES]->(r)
RETURN i, v, s, attendees, p, r,
       collect(DISTINCT ok) AS provides,
       collect(DISTINCT trap) AS lacks"""


def _node(id_, kind, label, sub="", tone=""):
    return {"id": id_, "kind": kind, "label": label, "sub": sub, "tone": tone}


def impact_graph(incident_id: str) -> dict:
    """The graph-only question: who does this closure reach, what do they need, and which rooms provide it?"""
    rows = q(IMPACT_CYPHER, incidentId=incident_id)
    nodes, edges, seen = [], [], set()

    def add(n, col):
        if n["id"] not in seen:
            seen.add(n["id"])
            nodes.append(n | {"col": col})

    for r in rows:
        i, v, s = r["i"], r["v"], r["s"]
        add(_node(i["id"], "Incident", "Incident", i.get("note", "")[:40], "bad"), 0)
        add(_node(v["id"], "Venue", v["name"], "unavailable", "bad"), 1)
        add(_node(s["id"], "Session", s["title"].split(":")[0], f"{s['start']} · {r['attendees']} attendees"), 2)
        edges += [{"from": i["id"], "to": v["id"], "label": "CLOSED", "tone": "bad"},
                  {"from": s["id"], "to": v["id"], "label": "ASSIGNED_TO"}]
        holders = 0
        if r["p"]:
            p, req = r["p"], r["r"]
            holders += 1
            add(_node(p["id"], "Participant", p["name"], p["id"], "info"), 3)
            add(_node("req:" + req["id"], "Requirement", req["label"], "hard requirement", "info"), 4)
            edges += [{"from": p["id"], "to": s["id"], "label": "ATTENDS", "tone": "info"},
                      {"from": p["id"], "to": "req:" + req["id"], "label": "HAS_REQUIREMENT", "tone": "info"}]
            for ok in r["provides"]:
                add(_node(ok["id"], "Venue", ok["name"], f"{ok['capacity']} seats · provides", "go"), 5)
                edges.append({"from": ok["id"], "to": "req:" + req["id"], "label": "PROVIDES", "tone": "go"})
            for t in r["lacks"]:
                add(_node(t["id"], "Venue", t["name"], f"{t['capacity']} seats · fits, but no", "bad"), 5)
                edges.append({"from": t["id"], "to": "req:" + req["id"], "label": "NO PROVIDES", "tone": "bad",
                              "dashed": True})
        others = r["attendees"] - holders
        if others > 0 and ("others:" + s["id"]) not in seen:
            add(_node("others:" + s["id"], "Participant", f"{others} other attendees", "no recorded requirement"), 3)
            edges.append({"from": "others:" + s["id"], "to": s["id"], "label": "ATTENDS"})
    return {"nodes": nodes, "edges": edges, "cypher": IMPACT_CYPHER,
            "columns": ["Incident", "Closed venue", "Sessions", "Attendees", "Requirements", "Rooms"]}


def provenance_graph(ra_id: str) -> dict:
    rows = q("""
      MATCH (ra:RecoveryAction:Wayfound {id: $id})
      OPTIONAL MATCH (ra)-[:VERIFIED_BY]->(ver:Verification)
      OPTIONAL MATCH (ra)-[:RESOLVES]->(i:Incident)-[:CLOSED]->(cv:Venue)
      OPTIONAL MATCH (ra)-[:INFORMED_BY]->(prev:RecoveryAction)
      OPTIONAL MATCH (ra)-[m:REASSIGNED]->(s:Session)-[:ASSIGNED_TO]->(nv:Venue)
      RETURN ra, ver, i, cv, prev, collect({m: m {.*}, s: s {.id, .title, .start}, nv: nv {.id, .name}}) AS moves
    """, id=ra_id)
    if not rows:
        return {"nodes": [], "edges": []}
    r = rows[0]
    nodes, edges = [], []
    ra = r["ra"]
    nodes.append(_node(ra["id"], "RecoveryAction", "RecoveryAction", ra["id"], "go") | {"col": 1})
    if r["ver"]:
        ver = r["ver"]
        nodes.append(_node(ver["id"], "Verification", "Verification",
                           f"{ver['unresolved']} unresolved · {ver['engine']}", "go" if ver["passed"] else "bad") | {"col": 0})
        edges.append({"from": ra["id"], "to": ver["id"], "label": "VERIFIED_BY", "tone": "go"})
    if r["prev"]:
        nodes.append(_node(r["prev"]["id"], "RecoveryAction", "Precedent", r["prev"]["id"], "info") | {"col": 0})
        edges.append({"from": ra["id"], "to": r["prev"]["id"], "label": "INFORMED_BY", "tone": "info"})
    if r["i"]:
        nodes.append(_node(r["i"]["id"], "Incident", "Incident", r["i"]["status"], "") | {"col": 2})
        nodes.append(_node(r["cv"]["id"], "Venue", r["cv"]["name"], "closed", "bad") | {"col": 3})
        edges += [{"from": ra["id"], "to": r["i"]["id"], "label": "RESOLVES"},
                  {"from": r["i"]["id"], "to": r["cv"]["id"], "label": "CLOSED", "tone": "bad"}]
    for mv in r["moves"]:
        if not mv["s"]:
            continue
        s, nv = mv["s"], mv["nv"]
        nodes.append(_node(s["id"], "Session", s["title"].split(":")[0], f"{mv['m']['from']} → {mv['m']['to']}") | {"col": 2})
        if nv["id"] not in {n["id"] for n in nodes}:
            nodes.append(_node(nv["id"], "Venue", nv["name"], "now assigned", "go") | {"col": 3})
        edges += [{"from": ra["id"], "to": s["id"], "label": "REASSIGNED", "tone": "go"},
                  {"from": s["id"], "to": nv["id"], "label": "ASSIGNED_TO", "tone": "go"}]
    return {"nodes": nodes, "edges": edges, "columns": ["Evidence", "Action", "Incident & sessions", "Venues"]}
