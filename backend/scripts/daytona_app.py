"""Run the whole Wayfound app (API + dashboard) inside a Daytona sandbox.

    uv run python scripts/daytona_app.py deploy     # build, upload, start; prints the public URL
    uv run python scripts/daytona_app.py url        # print the URL again
    uv run python scripts/daytona_app.py logs       # server logs from the sandbox
    uv run python scripts/daytona_app.py stop       # stop the sandbox (keeps it for a later deploy)
    uv run python scripts/daytona_app.py delete     # remove it

The dashboard is built locally and served by FastAPI, so the app needs one port.
Settings come from .env and are passed to the sandbox as environment variables;
.env itself is never uploaded. The sandbox's preview URL is public, so anyone with
the link can use the demo.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import time
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import config  # noqa: E402

from daytona import (CreateSandboxFromSnapshotParams, Daytona, DaytonaConfig, FileUpload,  # noqa: E402
                     ListSandboxesQuery, SessionExecuteRequest)

ROOT = config.REPO_ROOT
REMOTE = "/home/daytona/wayfound"
PORT = 8000
LABELS = {"app": "wayfound", "role": "web"}
SESSION = "wayfound-server"
ENV_KEYS = ["NEO4J_URI", "NEO4J_USERNAME", "NEO4J_PASSWORD", "NEO4J_DATABASE", "DAYTONA_API_KEY",
            "DAYTONA_API_URL", "DAYTONA_TARGET", "NOSANA_LLM_URL", "NOSANA_LLM_MODEL", "NOSANA_LLM_KEY"]


def daytona() -> Daytona:
    if not config.DAYTONA_API_KEY:
        sys.exit("DAYTONA_API_KEY is not set in .env")
    kwargs = {"api_key": config.DAYTONA_API_KEY}
    if config.DAYTONA_API_URL:
        kwargs["api_url"] = config.DAYTONA_API_URL
    if config.DAYTONA_TARGET:
        kwargs["target"] = config.DAYTONA_TARGET
    return Daytona(DaytonaConfig(**kwargs))


def find_sandbox(d: Daytona):
    for sb in d.list(ListSandboxesQuery(labels=LABELS)):
        if str(sb.state).lower().split(".")[-1] not in ("destroyed", "destroying", "error"):
            return sb
    return None


def run(cmd: list[str], cwd: Path) -> str:
    print("$", " ".join(cmd))
    out = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    if out.returncode:
        sys.exit(out.stdout[-2000:] + out.stderr[-2000:])
    return out.stdout


def bundle() -> list[tuple[Path, str]]:
    run(["npm", "run", "build"], ROOT / "frontend")
    reqs = run(["uv", "export", "--no-hashes", "--no-dev", "--frozen", "--no-emit-project"], ROOT / "backend")
    req_file = ROOT / "backend" / ".wayfound-requirements.txt"
    req_file.write_text(reqs)
    files = [(req_file, f"{REMOTE}/backend/requirements.txt")]
    for f in sorted((ROOT / "backend" / "app").glob("*.py")):
        files.append((f, f"{REMOTE}/backend/app/{f.name}"))
    for f in sorted((ROOT / "frontend" / "dist").rglob("*")):
        if f.is_file():
            files.append((f, f"{REMOTE}/frontend/dist/{f.relative_to(ROOT / 'frontend' / 'dist')}"))
    return files


def cmd_deploy(args):
    d = daytona()
    files = bundle()
    env = {k: config.env(k) for k in ENV_KEYS if config.env(k)}
    sb = find_sandbox(d)
    if sb is None:
        print("Creating sandbox...")
        sb = d.create(CreateSandboxFromSnapshotParams(
            language="python", labels=LABELS, env_vars=env, public=True,
            auto_stop_interval=args.auto_stop,
        ), timeout=180)
    else:
        print(f"Reusing sandbox {sb.id}")
        if not str(sb.state).lower().endswith("started"):
            sb.start(timeout=120)
    print(f"Sandbox {sb.id}")

    print(f"Uploading {len(files)} files...")
    sb.fs.upload_files([FileUpload(str(src), dst) for src, dst in files])

    print("Installing Python dependencies (first deploy takes a minute)...")
    r = sb.process.exec(f"cd {REMOTE}/backend && python -m pip install -q -r requirements.txt", timeout=600)
    if r.exit_code:
        sys.exit(f"pip install failed:\n{r.result[-3000:]}")

    # Restart the server with the current settings.
    sb.process.exec("pkill -f 'uvicorn app.main:app' || true", timeout=30)
    try:
        sb.process.delete_session(SESSION)
    except Exception:
        pass
    sb.process.create_session(SESSION)
    exports = " ".join(f"{k}={_shell_quote(v)}" for k, v in env.items())
    sb.process.execute_session_command(SESSION, SessionExecuteRequest(
        command=f"cd {REMOTE}/backend && env {exports} python -m uvicorn app.main:app --host 0.0.0.0 --port {PORT}",
        run_async=True,
    ))

    url = sb.get_preview_link(PORT).url.rstrip("/")
    print("Waiting for the app to answer...")
    for _ in range(60):
        try:
            h = httpx.get(f"{url}/api/health", timeout=10)
            if h.status_code == 200:
                data = h.json()
                print(f"neo4j={data['neo4j'].get('ok')} daytona={data['daytona']['mode']} "
                      f"nosana={data['nosana']['enabled']}")
                print(f"\nWayfound is live: {url}\n")
                return
        except Exception:
            pass
        time.sleep(3)
    sys.exit(f"The app didn't answer at {url}. Run `logs` to see why.")


def _shell_quote(v: str) -> str:
    return "'" + v.replace("'", "'\\''") + "'"


def cmd_url(_):
    sb = find_sandbox(daytona())
    if sb is None:
        sys.exit("No Wayfound sandbox. Run `deploy`.")
    print(sb.get_preview_link(PORT).url)


def cmd_logs(_):
    sb = find_sandbox(daytona())
    if sb is None:
        sys.exit("No Wayfound sandbox.")
    session = sb.process.get_session(SESSION)
    for c in session.commands or []:
        logs = sb.process.get_session_command_logs(SESSION, c.id)
        print(getattr(logs, "output", None) or (getattr(logs, "stdout", "") + getattr(logs, "stderr", "")))


def cmd_stop(_):
    sb = find_sandbox(daytona())
    if sb:
        sb.stop()
        print(f"Stopped {sb.id}")


def cmd_delete(_):
    sb = find_sandbox(daytona())
    if sb:
        sb.delete()
        print(f"Deleted {sb.id}")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    dp = sub.add_parser("deploy")
    dp.add_argument("--auto-stop", type=int, default=240, help="minutes idle before the sandbox stops (0 = never)")
    dp.set_defaults(fn=cmd_deploy)
    for name, fn in (("url", cmd_url), ("logs", cmd_logs), ("stop", cmd_stop), ("delete", cmd_delete)):
        sub.add_parser(name).set_defaults(fn=fn)
    args = ap.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
