# Wayfound demo script

What to click, what each part of the system is doing, and what to say. The annotated screenshots are in
`docs/demo-guide.html` (open it locally; it's not in the repo because of its size).

**Who does what:** *Nosana AI* is a Qwen 3.5 language model on a Nosana GPU. It reads incident reports and writes
explanations, and never decides feasibility. *Neo4j* is the graph: who is affected, the audit trail and memory.
The *Daytona solver* is deterministic rule-checking code that runs in a Daytona sandbox; it is not AI.
*You* (the organiser) approve every change.

Before starting: open http://localhost:5173 and click **Wipe memory**, then OK.

## Step 1 · The problem

**Click:** Click Report incident.  
**Wait:** ~10 s while the AI reads the report

- **Nosana AI:** A Qwen 3.5 language model on a Nosana GPU reads the free-text report and works out which room it means (Lecture Theatre 1).
- **Neo4j:** Marks that room unavailable and opens an incident in the graph.

> Picture a university event: 200 people, 5 sessions, 6 rooms. A pipe bursts and Lecture Theatre 1 is closed. I just typed that in plain English. Right now an AI model running on a Nosana GPU is reading my message and working out which room I mean.

## Step 2 · Who is affected

**Click:** Point at the graph from left to right, then click the Quick fix tab.

- **Neo4j:** One graph query follows the closure: room → keynote → 160 attendees → Aisha → step-free access → the rooms that provide it.
- **Nosana AI:** Already done: it identified the room. It takes no part in this step.

> The AI understood the report: Lecture Theatre 1. Now Neo4j takes over. One graph query follows the closure to the keynote, 160 people, and Aisha, who needs step-free access, and on to the only rooms that provide it: Hall B and Auditorium 2.

## Step 3 · The quick fix fails

**Click:** Point at the red block and the red Overlooked box.

- **Rule checker (no AI):** Tests the quick fix (smallest free room with enough seats) against every hard rule and finds it breaks Aisha's step-free requirement.

> This is what a stressed organiser would do: 160 people, 165 seats, looks fine. Our rule checker catches that it fails Aisha. Notice this is plain code checking recorded facts. We never let an AI decide whether a room is accessible.

## Step 4 · Find a real fix

**Click:** Scroll the right side down and click Run recovery in Daytona.  
**Wait:** ~10 s while the AI writes the explanation

- **Daytona solver (no AI):** Ships the live data from Neo4j into an isolated Daytona sandbox and searches every arrangement for the fewest moves that break no rule.
- **Nosana AI:** Once the plan is found, turns the solver's result into a plain-English explanation for the organiser.

> Two things happen now. A solver runs inside a Daytona sandbox and checks every possible arrangement. It decides the plan. Then the AI on Nosana writes the explanation in plain English. The AI explains; it doesn't decide.

## Step 5 · The plan

**Click:** Point at the black Daytona strip and the moved keynote. Click Why not the other rooms?

- **Daytona solver:** The black strip is the proof: sandbox ID, exit code 0, search steps and timing.
- **Nosana AI:** The "Explanation · Nosana LLM" paragraph is the AI's summary of the plan.

> That black strip is the real Daytona sandbox and its exit code. The plan: keynote to Hall B. This paragraph was written by the AI on Nosana. And here is why every other room was rejected, rule by rule.

## Step 6 · Live twist

**Click:** Click Disable Hall B & rerun.  
**Wait:** ~10 s

- **Neo4j:** Marks Hall B unavailable too.
- **Daytona solver:** Searches again from scratch with the new situation.
- **Nosana AI:** Writes a new explanation for the new plan.

> To prove nothing is scripted, let's take Hall B away as well. The solver reruns in Daytona and the AI re-explains.

## Step 7 · A smarter plan

**Click:** Point at the 3 moves, then click Approve & apply 3 moves.

- **Daytona solver:** Found a 3-move chain: clinic → Studio 5 frees Auditorium 2 for the keynote; workshop → Seminar Room 3-1.
- **You (the organiser):** Nothing changes until you approve. The AI cannot apply changes on its own.

> It found a chain of three moves: the small clinic goes to Studio 5, which frees Auditorium 2 for the keynote. A human is always in control: nothing changes until I approve.

## Step 8 · Verified

**Click:** Point at the provenance graph and the big green 0.

- **Neo4j:** Applies the moves in one transaction, then stores the audit trail: what closed, what moved, and the verification.
- **Daytona verifier (no AI):** Re-reads fresh data from Neo4j and re-checks every rule in a sandbox: 0 unresolved.

> After approval it doesn't trust its own plan. It re-reads the live data and re-checks every rule in Daytona: zero problems. And the evidence is written back to Neo4j as this audit trail.

## Step 9 · Next week

**Click:** Click Reset demo (top right).

- **Neo4j:** Reopens the rooms and restores the timetable, but keeps the recovery history as memory.

> Now imagine it's next week, and the same room fails again.

## Step 10 · Report again

**Click:** Click Report incident.  
**Wait:** ~10 s while the AI reads the report

- **Nosana AI:** Reads the report again and identifies the room.

> Same report, and the AI on Nosana reads it again.

## Step 11 · It remembers

**Click:** Point at the purple Graph memory box, then click Run recovery in Daytona.  
**Wait:** ~10 s

- **Neo4j:** Looks up this room's history: it failed before, and finds the last fix that was verified.

> This time Neo4j remembers. This room failed before, and here is the fix that was verified last time.

## Step 12 · Smarter second run, then close

**Click:** Point at the purple Precedent box, then deliver the closing line.

- **Daytona solver:** Re-checks last week's fix against today's situation. It still works, but with Hall B back a one-move plan is simpler, so it picks that.
- **Nosana AI:** Explains the new plan in plain English.

> It re-checked last week's fix against today. It still works, but with Hall B back, a single move is simpler, so it chooses that. It learns without blindly repeating the past. To sum up: Neo4j is the memory and the reasoning, Daytona is where every action runs safely, and the AI on Nosana is the voice. Most recovery systems ask whether the operation can continue. Wayfound asks whether everyone can continue with it.
