# Wayfound

**Autonomous recovery that accounts for everyone.** Daytona HackSprint Singapore, 31 Oct 2026.

When a venue becomes unavailable, Wayfound finds the person the quick replacement overlooks, searches
for workable alternatives in a Daytona sandbox, applies the plan only after the organiser approves it, then
independently verifies the result and records the evidence in Neo4j.

> "Most recovery systems ask whether the operation can continue. Wayfound asks whether everyone can continue with it."

Pitch, judging-criteria mapping and demo script: **[PITCH.md](PITCH.md)** · Team proposal: [docs/Exception_One_Hackathon_Team_Proposal.pdf](docs/Exception_One_Hackathon_Team_Proposal.pdf)

## How it works

| Step | What happens | Where |
|---|---|---|
| **Detect** | Organiser reports an incident (free text) or closes a room | Dashboard → FastAPI |
| **Trace** | Cypher finds affected sessions, attendee counts, equipment, and people with hard requirements | Neo4j |
| **Check** | A capacity-only "quick fix" is tested against explicit rules. It fits the seats but breaks step-free access for one attendee | Rule engine |
| **Recover** | Branch-and-bound solver searches every reassignment: fewest sessions moved, tightest rooms | **Daytona sandbox** |
| **Approve** | Nothing changes until the organiser approves; moves are applied in one Neo4j transaction, guarded against stale state | FastAPI → Neo4j |
| **Verify** | State is re-read from Neo4j and every hard constraint is re-checked; `RecoveryAction` and `Verification` nodes are stored | **Daytona** → Neo4j |
| **Remember** | Next time the same room fails, the last verified plan is read back as a precedent, re-checked against today's state, and reused or rejected with a reason (`INFORMED_BY`) | Neo4j → Daytona |

Two graph views make the graph's contribution visible: the **Impact graph** (incident → room → session → attendee → requirement → rooms that `PROVIDE` it) and the **Provenance graph** (verification ← recovery → incident, sessions, rooms, precedent).

**Feasibility is decided only by deterministic code.** The LLM (on Nosana) only interprets free-text
reports and words the explanation. It never certifies accessibility.

### Sponsor integration

- **Neo4j AuraDB**: graph of `Event`, `Session`, `Venue`, `Resource`, `Participant`, `Requirement` (with
  `(:Venue)-[:PROVIDES]->(:Requirement)`), plus `Incident`, `RecoveryAction`, `Verification` for the audit trail
  and memory.
- **Daytona**: the engine ([backend/app/engine.py](backend/app/engine.py), standard library only) is shipped
  into a sandbox and executed for both `solve` and `verify`. The dashboard shows the sandbox id, exit code and
  timings for every run. One sandbox is reused (auto-stops after 30 idle minutes) so the demo stays fast.
- **Nosana**: Wayfound's language model (Qwen 3.5 9B on Ollama) runs on a Nosana GPU. It turns a free-text
  incident report into the affected room and writes the plain-English explanation of each plan. It never
  decides feasibility. `backend/scripts/nosana.py up` deploys Nosana's official Ollama template through the
  Nosana API, waits for the endpoint, and writes it to `.env`; `down` stops it. Without Nosana, keyword
  matching and a deterministic template are used and the header says *Nosana off*.

### Hard constraints checked

Venue available · capacity ≥ attendees · session equipment present · every attendee's requirement met
(step-free access, hearing loop, wheelchair space) · no double-booking of overlapping sessions.

## Run it

Prerequisites: [uv](https://docs.astral.sh/uv/), Node 20+.

```bash
cp .env.example .env   # then fill in Neo4j + Daytona keys (ask Elkan for the shared Neo4j credentials)
./dev.sh
```

Open http://localhost:5173. The first load seeds Neo4j with the synthetic event if it's empty.
**Reset demo** reopens rooms and restores the timetable but keeps recovery history (the memory); **Wipe memory**
also deletes history. Only nodes labelled `:Wayfound` are ever touched.

Without a Daytona key, recovery is disabled and the dashboard says why. For offline UI work only, set
`ALLOW_LOCAL_EXECUTION=true` to run the same engine as a local subprocess (a warning banner stays visible).

API docs: http://localhost:8010/docs

## Demo

The three-minute script, judging-criteria mapping and likely questions are in [PITCH.md](PITCH.md).

### Scenario facts (synthetic)

| Venue | Seats | Step-free | Notes |
|---|---|---|---|
| Lecture Theatre 1 | 250 | yes | Closed by the incident |
| Seminar Room 3-1 | 165 | **no** | The capacity-only quick fix |
| Hall B | 175 | yes | First recommendation |
| Auditorium 2 | 300 | yes | Hosts the 09:00 clinic and 14:00 panel |
| Seminar Room 2-2 | 90 | yes | |
| Studio 5 | 60 | **no** | Can take the 40-person clinic |

## Layout

```
backend/   FastAPI app (uv): engine, Neo4j graph access, Daytona executor, Nosana narrator
frontend/  Vue 3 + TypeScript + Vite dashboard
docs/      Team proposal
```

## Out of scope

Real university systems, real bookings or notifications, production accessibility certification, and any
sensitive medical data. All participants are synthetic.
