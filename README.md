# Wayfound

**Autonomous recovery that accounts for everyone.** Daytona HackSprint Singapore, 31 Oct 2026.

When a venue becomes unavailable, Wayfound finds the person the quick replacement overlooks, searches
for workable alternatives in a Daytona sandbox, applies the plan only after the organiser approves it, then
independently verifies the result and records the evidence in Neo4j.

> "Most recovery systems ask whether the operation can continue. Wayfound asks whether everyone can continue with it."

Pitch, judging-criteria mapping and demo script: **[PITCH.md](PITCH.md)** · Team proposal: [docs/Exception_One_Hackathon_Team_Proposal.pdf](docs/Exception_One_Hackathon_Team_Proposal.pdf)

**Live on Daytona:** https://8000-12d5996b-5056-41e0-bac0-f6de994a6a38.daytonaproxy01.eu (Daytona shows a one-time
preview warning; click *I Understand, Continue*).

## Sponsor integration: Daytona, Neo4j, Nosana

All three sponsors are integrated and were verified end to end on 31 Oct 2026. Each has a real job in the
product, not a token call.

| Sponsor | Its job in Wayfound | Code | Verified result |
|---|---|---|---|
| **Daytona** | Runs the constraint solver and the post-change verifier in an isolated sandbox for every recovery; also hosts the whole app (API, dashboard, Neo4j, engine) at the public link above | [executor.py](backend/app/executor.py), [engine.py](backend/app/engine.py), [scripts/daytona_app.py](backend/scripts/daytona_app.py) | Recovery in sandbox `abff8f36…`, exit 0: keynote → Hall B. Verification in a sandbox: **0 unresolved hard constraints** (35 checks). The sandbox id and exit code are shown on screen for every run. |
| **Neo4j** | Source of truth for the event graph; the path query that finds who a closure reaches and which rooms `PROVIDE` what they need; audit trail (`RecoveryAction`, `REASSIGNED`, `VERIFIED_BY`); memory of verified fixes (`INFORMED_BY`) | [graph.py](backend/app/graph.py) | Neo4j AuraDB 5.27: trace found 160 attendees and 1 hard requirement; second run reused the verified precedent, or rejected it with a reason when it no longer held. |
| **Nosana** | A Qwen 3.5 9B model (Ollama) on a Nosana RTX 3090 GPU reads free-text incident reports and writes the plain-English explanation of each plan. It never decides feasibility. | [narrator.py](backend/app/narrator.py), [scripts/nosana.py](backend/scripts/nosana.py) | Deployment `BjEWJiaajTYybjsdgy8XAgW2Bu2rcoVkXJ1uxgenjbPq` (RUNNING). "Facilities just closed Lecture Theatre 1 because a pipe burst" → `LT1`, `by: nosana`; explanations labelled *Nosana LLM* in the UI. |

### Known limitation and how we handled it

Our Daytona organisation is on a **restricted network tier (Tier 1/2)**. Sandboxes on these tiers can only reach
an allow-list of essential services (package registries, GitHub, some AI providers), and this cannot be
overridden per sandbox ([Daytona docs: tier-based network restrictions](https://www.daytona.io/docs/en/network-limits/#tier-based-network-restrictions)).
We confirmed it from inside the sandbox: Neo4j Aura (`*.databases.neo4j.io`) and the Nosana GPU node
(`*.node.k8s.prd.nos.ci`) both time out, and `update_network_settings` returns *"Network access is restricted and
cannot be overridden at the sandbox level."*

So there are two ways to run Wayfound, and between them every sponsor is used for real:

| Where it runs | Daytona | Neo4j | Nosana |
|---|---|---|---|
| **Laptop** (`./dev.sh`): the main demo | Solver and verifier run in Daytona sandboxes | Neo4j AuraDB | Live Qwen 3.5 model on Nosana |
| **Daytona-hosted** (public link above) | The whole app runs in a Daytona sandbox; the engine runs in that same sandbox | Neo4j 5 Community **inside** the sandbox (built from the official `neo4j:5-community` image), because Aura is unreachable | Unreachable from the sandbox on this tier, so it falls back to keyword matching and a deterministic template, and the header says *Nosana off* |

On Daytona Tier 3+ the hosted version uses Aura and Nosana too: `uv run python scripts/daytona_app.py deploy --neo4j aura`.

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

### Run it on Daytona (public link)

```bash
cd backend && uv run python scripts/daytona_app.py deploy
```

This builds a Daytona sandbox from Neo4j's official image and runs the Neo4j database, the API, the
dashboard and the constraint engine all inside it, then prints a public preview URL (Daytona shows a one-time
warning page; click *I Understand, Continue*). It works on Daytona's restricted network tiers. On Tier 3+,
`--neo4j aura` uses the Aura instance and the Nosana model from `.env` instead. `url`, `logs`, `stop` and
`delete` manage it. Anyone with the link can use the demo.

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
