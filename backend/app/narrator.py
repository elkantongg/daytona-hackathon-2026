"""Language layer: incident interpretation and plain-English explanations.

Uses a Nosana-hosted LLM (any OpenAI-compatible endpoint, e.g. an Ollama
deployment on Nosana) when NOSANA_LLM_URL is set. The LLM only words things;
it never decides feasibility. Without Nosana, deterministic fallbacks are used
and the response says so.
"""

from __future__ import annotations

import json
import re

import httpx

from . import config


def enabled() -> bool:
    return bool(config.NOSANA_LLM_URL)


def _chat(system: str, user: str, max_tokens: int = 300) -> str:
    url = config.NOSANA_LLM_URL
    if not url.endswith("/chat/completions"):
        url = url + ("/chat/completions" if url.endswith("/v1") else "/v1/chat/completions")
    headers = {"Content-Type": "application/json"}
    if config.NOSANA_API_KEY:
        headers["Authorization"] = f"Bearer {config.NOSANA_API_KEY}"
    r = httpx.post(url, headers=headers, timeout=25, json={
        "model": config.NOSANA_LLM_MODEL or "llama3.1:8b",
        "temperature": 0.1, "max_tokens": max_tokens,
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
    })
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"].strip()


def interpret(text: str, venues: list[dict]) -> dict:
    """Map a free-text incident report to a venue id."""
    if enabled():
        try:
            listing = "\n".join(f"{v['id']}: {v['name']} ({v['building']})" for v in venues)
            out = _chat(
                "You map incident reports to exactly one venue id from a list. "
                'Reply with JSON only: {"venueId": "<id or null>", "summary": "<10 words>"}',
                f"Venues:\n{listing}\n\nReport: {text}", max_tokens=80)
            data = json.loads(re.search(r"\{.*\}", out, re.S).group(0))
            if data.get("venueId") in {v["id"] for v in venues}:
                return {"venueId": data["venueId"], "summary": data.get("summary", ""), "by": "nosana"}
        except Exception as e:
            fallback = _match(text, venues)
            return fallback | {"by": "keyword", "warning": f"Nosana unavailable ({type(e).__name__}); used keyword match"}
    return _match(text, venues) | {"by": "keyword"}


def _match(text: str, venues: list[dict]) -> dict:
    t = text.lower()
    best, score = None, 0
    for v in venues:
        name = v["name"].lower()
        aliases = {name, v["id"].lower(), re.sub(r"lecture theatre ", "lt", name),
                   re.sub(r"seminar room ", "sr", name).replace("-", ""), name.replace("auditorium ", "aud")}
        s = max((len(a) for a in aliases if a and a in t), default=0)
        if s > score:
            best, score = v, s
    if best is None:
        return {"venueId": None, "summary": "No venue recognised in the report"}
    return {"venueId": best["id"], "summary": f"{best['name']} reported unusable"}


def explain(proposal: dict, quick_fix: dict | None, venues: dict, memory: dict | None = None) -> dict:
    facts = _facts(proposal, quick_fix, venues, memory)
    if enabled():
        try:
            text = _chat(
                "You explain a venue-recovery plan to an event organiser in at most 3 short sentences. "
                "Use only the facts given. Never claim a venue is accessible unless the facts say so. "
                "Never invent numbers.",
                json.dumps(facts), max_tokens=180)
            return {"text": text, "by": "nosana"}
        except Exception as e:
            return {"text": _template(facts), "by": "template",
                    "warning": f"Nosana unavailable ({type(e).__name__}); used deterministic template"}
    return {"text": _template(facts), "by": "template"}


def _facts(proposal, quick_fix, venues, memory=None):
    pre = proposal.get("precedent")
    return {
        "precedent": None if not pre else {
            "fromRecovery": (memory or {}).get("recoveryId"), "stillValid": pre["valid"],
            "followed": pre.get("followed"), "whyInvalid": pre["violations"][:2],
            "priorIncidents": (memory or {}).get("priorIncidents", 0)},
        "status": proposal["status"],
        "moves": [{"session": m["sessionTitle"], "from": venues.get(m["from"], {}).get("name", m["from"]),
                   "to": m["toName"], "attendees": m["attendees"], "capacity": m["capacity"],
                   "why": m["reason"]} for m in proposal.get("moves", [])],
        "quickFixProblems": [v["detail"] for v in (quick_fix or {}).get("violations", [])],
        "infeasibleReason": proposal.get("reason"),
        "remainingViolations": len(proposal.get("violationsAfter", [])),
    }


def _template(f) -> str:
    if f["status"] != "feasible":
        return (f"No feasible plan exists with the venues currently available. {f['infeasibleReason']} "
                "Re-open a venue or relax a requirement with the affected attendee before proceeding.")
    parts = []
    if f["quickFixProblems"]:
        parts.append(f"The capacity-only quick fix fails: {f['quickFixProblems'][0]}.")
    moves = "; ".join(f"{m['session']} moves from {m['from']} to {m['to']} ({m['attendees']}/{m['capacity']} seats)"
                      for m in f["moves"])
    parts.append(f"Recommended plan: {moves}.")
    pre = f.get("precedent")
    if pre and pre["stillValid"] and pre["followed"]:
        parts.append(f"This reuses the plan verified after this room's last closure ({pre['fromRecovery']}), re-checked against today's state.")
    elif pre and not pre["stillValid"]:
        why = pre["whyInvalid"][0] if pre["whyInvalid"] else "live state changed"
        parts.append(f"The plan that worked last time ({pre['fromRecovery']}) no longer holds: {why}. A new plan was computed.")
    if len(f["moves"]) > 1:
        parts.append("Extra moves are needed only to free a suitable room; every hard constraint is satisfied.")
    else:
        parts.append("Every hard constraint is satisfied with a single move.")
    return " ".join(parts)
