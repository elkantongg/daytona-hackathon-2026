"""Synthetic demo scenario: a one-day university event with 200 participants.

Everything here is fabricated for the hackathon demo. No real people.
The data is deterministic (fixed seed) so every demo run tells the same story:

* Lecture Theatre 1 hosts the 09:00 keynote (160 attendees).
* When it closes, the quickest capacity-only swap is Seminar Room 3-1 (165 seats),
  which has stairs only - and one keynote attendee needs step-free access.
* The solver finds Hall B. Disable Hall B and it must move the 09:00 clinic out
  of Auditorium 2 to make room. Disable Auditorium 2 as well and no feasible plan exists.
"""

from __future__ import annotations

import random

EVENT = {
    "id": "EVT-2026-SMU-OPS",
    "name": "Campus Operations Summit 2026",
    "date": "2026-11-14",
    "organiser": "University Events Office",
}

RESOURCES = {
    "projector": "Projector",
    "microphone": "Microphone & PA",
    "hearing_loop": "Hearing loop",
    "lecture_capture": "Lecture capture",
}

REQUIREMENTS = {
    "step_free": "Step-free access",
    "hearing_loop": "Hearing loop",
    "wheelchair_space": "Wheelchair space",
}

VENUES = [
    {"id": "LT1", "name": "Lecture Theatre 1", "building": "Administration Building", "level": "L1",
     "capacity": 250, "stepFree": True, "wheelchairSpaces": 4,
     "resources": ["projector", "microphone", "hearing_loop", "lecture_capture"]},
    {"id": "SR31", "name": "Seminar Room 3-1", "building": "School of Computing", "level": "L3",
     "capacity": 165, "stepFree": False, "wheelchairSpaces": 0,
     "resources": ["projector", "microphone"],
     "accessNote": "Stairs only; the lift does not serve level 3 of this wing"},
    {"id": "HALLB", "name": "Hall B", "building": "Campus Green", "level": "L1",
     "capacity": 175, "stepFree": True, "wheelchairSpaces": 2,
     "resources": ["projector", "microphone"]},
    {"id": "AUD2", "name": "Auditorium 2", "building": "School of Business", "level": "B1",
     "capacity": 300, "stepFree": True, "wheelchairSpaces": 6,
     "resources": ["projector", "microphone", "hearing_loop", "lecture_capture"]},
    {"id": "SR22", "name": "Seminar Room 2-2", "building": "School of Economics", "level": "L2",
     "capacity": 90, "stepFree": True, "wheelchairSpaces": 1,
     "resources": ["projector"]},
    {"id": "ST5", "name": "Studio 5", "building": "Arts Annexe", "level": "L2",
     "capacity": 60, "stepFree": False, "wheelchairSpaces": 0,
     "resources": ["projector"],
     "accessNote": "Mezzanine studio reached by a spiral staircase"},
]

SESSIONS = [
    {"id": "S1", "title": "Opening Keynote: Resilient Campus Operations", "start": "09:00", "end": "10:30",
     "venue": "LT1", "requiredResources": ["projector", "microphone"], "size": 160},
    {"id": "S2", "title": "Industry Clinic: Supply-Chain Shocks", "start": "09:00", "end": "10:30",
     "venue": "AUD2", "requiredResources": ["projector"], "size": 40},
    {"id": "S3", "title": "Workshop: Thinking in Graphs", "start": "11:00", "end": "12:30",
     "venue": "SR22", "requiredResources": ["projector"], "size": 80},
    {"id": "S4", "title": "Workshop: Sandboxed Agents in Practice", "start": "11:00", "end": "12:30",
     "venue": "HALLB", "requiredResources": ["projector", "microphone"], "size": 70},
    {"id": "S5", "title": "Closing Panel: Who Gets Left Out?", "start": "14:00", "end": "15:00",
     "venue": "AUD2", "requiredResources": ["microphone"], "size": 190},
]

FIRST = ["Aisha", "Ben", "Chloe", "Daniel", "Elena", "Farhan", "Grace", "Hao", "Isaac", "Jia Hui",
         "Kavya", "Liam", "Mei Ling", "Nikhil", "Olivia", "Priya", "Qi", "Rahul", "Siti", "Tan",
         "Uma", "Victor", "Wei Jie", "Xin Yi", "Yusuf", "Zara", "Arjun", "Bella", "Cheng", "Divya"]
LAST = ["Rahman", "Tan", "Lim", "Ng", "Wong", "Kumar", "Lee", "Chua", "Goh", "Ong", "Teo", "Koh",
        "Singh", "Menon", "Ho", "Chen", "Yeo", "Low", "Ismail", "Pereira"]

# The person the quick fix overlooks.
STEP_FREE_PARTICIPANT = {"id": "P137", "name": "Aisha Rahman"}


def build(seed: int = 7) -> dict:
    rng = random.Random(seed)
    ids = [f"P{i:03d}" for i in range(1, 201)]
    names = {}
    used = set()
    for pid in ids:
        while True:
            n = f"{rng.choice(FIRST)} {rng.choice(LAST)}"
            if n not in used and n != STEP_FREE_PARTICIPANT["name"]:
                used.add(n)
                break
        names[pid] = n
    names[STEP_FREE_PARTICIPANT["id"]] = STEP_FREE_PARTICIPANT["name"]

    special = STEP_FREE_PARTICIPANT["id"]
    others = [p for p in ids if p != special]
    rng.shuffle(others)

    # 09:00 slot: everyone attends exactly one of S1 / S2. The step-free attendee is in the keynote.
    s1 = [special] + others[:159]
    s2 = others[159:199]
    pool = [p for p in ids]
    rng.shuffle(pool)
    s3 = [special] + [p for p in pool if p != special][:79]
    rest = [p for p in pool if p not in s3]
    s4 = rest[:70]
    s5 = [special] + [p for p in others if p != special][:189]
    attendees = {"S1": s1, "S2": s2, "S3": s3, "S4": s4, "S5": s5}

    participants = []
    for pid in ids:
        reqs = ["step_free"] if pid == special else []
        participants.append({"id": pid, "name": names[pid], "requirements": reqs,
                             "email": f"{pid.lower()}@example.edu"})

    sessions = []
    for s in SESSIONS:
        att = attendees[s["id"]]
        assert len(att) == s["size"], (s["id"], len(att))
        sessions.append({k: v for k, v in s.items() if k != "size"} | {"attendees": att})

    return {"event": EVENT, "venues": VENUES, "sessions": sessions, "participants": participants,
            "resources": RESOURCES, "requirements": REQUIREMENTS}
