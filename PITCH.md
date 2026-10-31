# Wayfound: pitch and demo playbook

> "Most recovery systems ask whether the operation can continue. **Wayfound asks whether everyone can continue with it.**"

## The pitch in four parts

**1. Problem.** When a room is lost at the last minute, organisers grab the first room with enough seats. Capacity
is easy to check, but personal requirements (step-free access, a hearing loop, a wheelchair space) live in
other systems and get missed under time pressure. The fix works for 159 people and silently fails one.
*(Problem hypothesis: we have not measured how often this happens in practice.)*

**2. Solution.** Wayfound is a recovery workflow, not a chatbot. It reads the live event graph, traces exactly
who a disruption reaches and what they need, runs a real solver in a Daytona sandbox, changes the schedule only
after a human approves, then re-verifies from fresh state and writes the evidence back to Neo4j. The next time
the same room fails, it starts from what worked last time.

**3. Impact (measured in our demo, not extrapolated)**

| Measure | Result |
|---|---|
| Quick-fix failures caught | 1 of 1 (the capacity-only swap breaks Aisha's step-free requirement) |
| Hard-constraint checks per verification | 35, across 5 sessions, all re-read from Neo4j |
| Unresolved hard constraints after recovery | **0** |
| Solver time inside the sandbox | ~0.1 ms (14–15 search nodes) |
| Daytona round trip, warm sandbox | ~0.5–0.7 s (first run ~2 s) |
| Plan when a key room is also lost (live twist) | Re-plans to 3 coordinated moves, or honestly reports "no feasible plan" |

**4. USP.**
- **The overlooked person is the headline**, not a footnote: the quick fix is shown failing before the solution appears.
- **Graph-only reasoning**: one traversal (Incident → room → session → attendee → requirement → rooms that `PROVIDE` it) answers a question a spreadsheet can't.
- **Deterministic feasibility**: no LLM decides accessibility. The LLM (Nosana) only words things.
- **Memory with honesty**: last time's verified plan is reused only after being re-checked against today's state, and the dashboard says when it no longer holds.
- **Auditability**: every recovery is a `RecoveryAction` with `REASSIGNED`, `VERIFIED_BY` and `INFORMED_BY` edges.

## Judging criteria → evidence on screen

| Criterion | What judges see |
|---|---|
| **Completeness**: functional MVP | Full loop live: detect → trace → check → recover → approve → verify, plus history, against real Neo4j and real Daytona. No mocks in the demo path. |
| **Innovation**: original idea | Recovery framed around the *exception*, not the majority; precedent memory that re-validates itself; impact and provenance as graphs. |
| **Real-life problem solving** | Last-minute venue loss is common for university events; the failure mode (capacity yes, access no) is concrete and human. |
| **Sponsor usage** | **Neo4j**: source of truth, the path query, `PROVIDES` reasoning, memory and provenance. **Daytona**: every solve and every verification runs in a sandbox (id and exit code on screen). **Nosana**: a Qwen 3.5 9B model on a Nosana GPU reads the free-text incident report and writes each plan's explanation; the header shows *Nosana LLM* and each explanation is labelled with its source. |

## How we meet Neo4j's "one visible loop"

| Neo4j slide | Wayfound |
|---|---|
| 1. Model the smallest useful graph (5–8 types) | `Venue`, `Session`, `Participant`, `Requirement`, `Resource`, plus `Incident`, `RecoveryAction`, `Verification` for the loop |
| 2. Ask one graph-only question; show a path | **Impact graph** tab: the path from incident to the person, their requirement, and the rooms that provide it; the quick-fix room shown as a red `NO PROVIDES` edge |
| 3. Let the agent take a real action with Daytona | The solver and the verifier both execute in a Daytona sandbox; approval applies real changes to the graph |
| 4. Write the outcome back so the second run is smarter | `RecoveryAction`/`Verification` written back; run 2 reads the precedent, re-checks it, reuses it or explains why not, and links `INFORMED_BY` |

## Three-minute demo

**Before going on stage:** open http://localhost:5173, click **Wipe memory** (fresh graph), and check that the header shows *Neo4j*, *Daytona ready*, and *Nosana* green.

| Time | Say | Click |
|---|---|---|
| 0:00–0:20 | "200 people, 5 sessions, 6 rooms. When a room fails, most fixes work for most people. We built for the one they miss." | Schedule visible |
| 0:20–0:40 | "Facilities just closed Lecture Theatre 1." | **Report incident** |
| 0:40–1:05 | "One Neo4j traversal: the closure reaches the keynote, 160 attendees, and Aisha, who needs step-free access. Only Hall B and Auditorium 2 provide it. The obvious swap, Seminar Room 3-1, has the seats but only stairs." | **Impact graph** tab, then **Quick fix** tab |
| 1:05–1:30 | "The solver runs in a Daytona sandbox; here's the sandbox id and exit code. Keynote to Hall B, and here's why every other room was rejected." | **Run recovery in Daytona**, open *Why not the other rooms?* |
| 1:30–1:55 | "Live twist: Hall B is gone too. It re-plans with three coordinated moves, freeing Auditorium 2 for the keynote." | **Disable Hall B & rerun** |
| 1:55–2:25 | "Nothing changes until I approve. Then it re-reads Neo4j and re-verifies in Daytona: zero unresolved constraints, and the evidence is written back as a graph." | **Approve**, **Provenance graph** |
| 2:25–2:50 | "The room fails again next week. Wayfound remembers what worked, re-checks it against today, and tells you if it no longer holds." | **Reset demo**, **Report incident**, point at *Graph memory*, **Run recovery** shows *Reused* |
| 2:50–3:00 | Closing line. | |

## Likely questions

- **"Isn't this just ChatGPT with documents?"** No model decides feasibility. A deterministic solver checks every hard constraint against live records, runs in an isolated sandbox, and the result is re-verified after the change. You can read the Cypher and the rejected-room reasons on screen.
- **"Does it scale?"** The demo is 5 sessions and 6 rooms by design. The engine is branch and bound with per-session pruning; for timetable-scale problems you'd swap in a constraint solver such as OR-Tools inside the same sandbox contract.
- **"What if there is no solution?"** Disable three rooms: it says so and lists why each room fails. It never guesses.
- **"Where does accessibility data come from?"** In production, from the registration system's declared requirements and the estates database's venue facts, both as explicit records. Here it's synthetic.
- **"Why a graph?"** The question "who does this closure reach, and which rooms provide what they need" is a multi-hop path. In Neo4j it's one traversal, and the same graph holds the audit trail and the memory.
- **Privacy.** All participants are synthetic. Real deployments would store only the requirement category, never medical detail.
