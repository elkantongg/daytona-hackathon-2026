"""Manage Wayfound's LLM deployment on Nosana.

    uv run python scripts/nosana.py balance
    uv run python scripts/nosana.py markets
    uv run python scripts/nosana.py up [--market nvidia-3090] [--hours 6]
    uv run python scripts/nosana.py status
    uv run python scripts/nosana.py down

`up` deploys Nosana's official Ollama template (Qwen 3.5 9B), waits until the
endpoint answers, and writes NOSANA_LLM_URL / NOSANA_LLM_MODEL /
NOSANA_DEPLOYMENT_ID into the repo's .env. Running a deployment spends credits;
`down` stops it.

Needs NOSANA_API_KEY in .env (deploy.nosana.com → Account → API Keys).
"""

from __future__ import annotations

import argparse
import re
import sys
import time
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import config  # noqa: E402

API = "https://api.nosana.com"
ENV_FILE = config.REPO_ROOT / ".env"
MODEL = "qwen3.5:9b"

# Nosana's official Ollama template for Qwen 3.5 9B (nosana-ci/pipeline-templates).
JOB_DEFINITION = {
    "version": "0.1",
    "type": "container",
    "meta": {"trigger": "api", "system_requirements": {"vram_total_mb": 9216}},
    "ops": [{
        "id": "server",
        "type": "container/run",
        "args": {
            "gpu": True,
            "image": "docker.io/ollama/ollama:0.32.6",
            "expose": [{
                "port": 11434,
                "health_checks": [{"type": "http", "path": "/api/tags", "method": "GET",
                                   "expected_status": 200, "continuous": False}],
            }],
            "resources": [{"type": "Ollama", "model": MODEL}],
        },
    }],
}


def client() -> httpx.Client:
    if not config.NOSANA_API_KEY:
        sys.exit("NOSANA_API_KEY is not set in .env (deploy.nosana.com → Account → API Keys).")
    return httpx.Client(base_url=API, timeout=30,
                        headers={"Authorization": f"Bearer {config.NOSANA_API_KEY}"})


def check(r: httpx.Response) -> dict:
    if r.status_code >= 400:
        sys.exit(f"Nosana API error {r.status_code}: {r.text[:500]}")
    return r.json() if r.content else {}


def set_env(**values: str) -> None:
    text = ENV_FILE.read_text() if ENV_FILE.exists() else ""
    for key, value in values.items():
        line = f"{key}={value}"
        if re.search(rf"^{key}=.*$", text, flags=re.M):
            text = re.sub(rf"^{key}=.*$", line, text, flags=re.M)
        else:
            text = text.rstrip("\n") + f"\n{line}\n"
    ENV_FILE.write_text(text)


def markets() -> list[dict]:
    return check(httpx.get(f"{API}/markets/", timeout=30))


def market_address(slug_or_address: str) -> tuple[str, dict]:
    for m in markets():
        if slug_or_address in (m["slug"], m["address"]):
            return m["address"], m
    sys.exit(f"Unknown market {slug_or_address!r}. Run `markets` to list them.")


def cmd_balance(_):
    with client() as c:
        print(check(c.get("/credits/balance")))


def cmd_markets(_):
    for m in sorted(markets(), key=lambda m: m["usd_reward_per_hour"] or 99):
        price = f"${m['usd_reward_per_hour']:.4f}/h" if m["usd_reward_per_hour"] is not None else "price n/a"
        print(f"{m['slug']:32} {m['type']:10} {price}")


def cmd_up(args):
    address, m = market_address(args.market)
    print(f"Market {m['name']} at about ${m['usd_reward_per_hour']:.3f}/hour, timeout {args.hours} h "
          f"(at most ~${m['usd_reward_per_hour'] * args.hours:.2f}).")
    with client() as c:
        dep = check(c.post("/deployments/create", json={
            "name": "wayfound-llm",
            "market": address,
            "replicas": 1,
            "timeout": int(args.hours * 60),
            "strategy": "SIMPLE",
            "autostart": True,
            "job_definition": JOB_DEFINITION,
        }))
        dep_id = dep["id"]
        set_env(NOSANA_DEPLOYMENT_ID=dep_id)
        print(f"Deployment {dep_id} created; waiting for the model endpoint (this can take a few minutes)...")
        deadline = time.time() + args.wait * 60
        while time.time() < deadline:
            d = check(c.get(f"/deployments/{dep_id}"))
            online = [e for e in d.get("endpoints", []) if e.get("online")]
            print(f"  status={d['status']} jobs={d.get('active_jobs')} endpoints={len(d.get('endpoints', []))} online={len(online)}")
            if d["status"] in ("ERROR", "INSUFFICIENT_FUNDS", "STOPPED"):
                sys.exit(f"Deployment ended with status {d['status']}.")
            if online:
                url = online[0]["url"].rstrip("/")
                if _model_ready(url):
                    set_env(NOSANA_LLM_URL=url, NOSANA_LLM_MODEL=MODEL)
                    print(f"Ready: {url} serving {MODEL}. Wrote NOSANA_LLM_URL and NOSANA_LLM_MODEL to .env.")
                    print("Restart the backend to pick it up.")
                    return
            time.sleep(15)
    sys.exit("Timed out waiting for the endpoint. Check `status`; the deployment is still running and spending credits.")


def _model_ready(url: str) -> bool:
    try:
        r = httpx.get(f"{url}/api/tags", timeout=15)
        return r.status_code == 200 and any(m.get("name", "").startswith(MODEL.split(":")[0])
                                            for m in r.json().get("models", []))
    except Exception:
        return False


def cmd_status(_):
    dep_id = config.env("NOSANA_DEPLOYMENT_ID")
    with client() as c:
        if not dep_id:
            for d in check(c.get("/deployments")).get("deployments", []):
                print(d["id"], d["name"], d["status"])
            return
        d = check(c.get(f"/deployments/{dep_id}"))
        print(f"{d['id']} {d['name']} {d['status']} jobs={d.get('active_jobs')}")
        for e in d.get("endpoints", []):
            print(f"  {e['url']} online={e['online']}")


def cmd_down(_):
    dep_id = config.env("NOSANA_DEPLOYMENT_ID")
    if not dep_id:
        sys.exit("No NOSANA_DEPLOYMENT_ID in .env; use `status` to find it.")
    with client() as c:
        d = check(c.post(f"/deployments/{dep_id}/stop"))
        print(f"Stopping {dep_id}: {d.get('status')}")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("balance").set_defaults(fn=cmd_balance)
    sub.add_parser("markets").set_defaults(fn=cmd_markets)
    up = sub.add_parser("up")
    up.add_argument("--market", default="nvidia-3090")
    up.add_argument("--hours", type=float, default=6)
    up.add_argument("--wait", type=float, default=20, help="minutes to wait for the endpoint")
    up.set_defaults(fn=cmd_up)
    sub.add_parser("status").set_defaults(fn=cmd_status)
    sub.add_parser("down").set_defaults(fn=cmd_down)
    args = ap.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
