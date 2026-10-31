"""Runs the constraint engine inside a Daytona sandbox.

One sandbox is created lazily and reused across runs (auto-stops after 30 idle
minutes) so the live demo isn't waiting on sandbox creation every click. The
engine source and the problem are shipped to the sandbox on every run; nothing
is pre-installed there.
"""

from __future__ import annotations

import json
import subprocess
import sys
import threading
import time
from pathlib import Path

from . import config

ENGINE_PATH = Path(__file__).with_name("engine.py")
MARKER = "WAYFOUND_RESULT:"

_lock = threading.Lock()
_client = None
_sandbox = None
_status = {"state": "idle", "detail": ""}


class ExecutionError(RuntimeError):
    pass


def mode() -> str:
    if config.HOSTED_SANDBOX_ID:
        return "hosted"
    if config.DAYTONA_API_KEY:
        return "daytona"
    return "local" if config.ALLOW_LOCAL_EXECUTION else "unconfigured"


def status() -> dict:
    if mode() == "hosted":
        return {"mode": "daytona", "sandboxId": config.HOSTED_SANDBOX_ID, "state": "ready",
                "detail": "App and engine run in this Daytona sandbox"}
    sb = _sandbox
    return {"mode": mode(), "sandboxId": getattr(sb, "id", None), **_status}


def _engine_program(payload: dict) -> str:
    src = ENGINE_PATH.read_text()
    src = src.split('if __name__ == "__main__":')[0]
    return src + f"\nprint(RESULT_MARKER + json.dumps(run(json.loads({json.dumps(json.dumps(payload))}))))\n"


def _parse(output: str) -> dict:
    for line in reversed(output.splitlines()):
        if line.startswith(MARKER):
            return json.loads(line[len(MARKER):])
    raise ExecutionError(f"Engine produced no result. Output:\n{output[-2000:]}")


def _get_sandbox():
    global _client, _sandbox
    from daytona import CreateSandboxFromSnapshotParams, Daytona, DaytonaConfig

    if _client is None:
        kwargs = {"api_key": config.DAYTONA_API_KEY}
        if config.DAYTONA_API_URL:
            kwargs["api_url"] = config.DAYTONA_API_URL
        if config.DAYTONA_TARGET:
            kwargs["target"] = config.DAYTONA_TARGET
        _client = Daytona(DaytonaConfig(**kwargs))

    if _sandbox is not None:
        try:
            _sandbox.refresh_data()
            if str(getattr(_sandbox, "state", "")).lower().endswith("started"):
                return _sandbox
            _status.update(state="starting", detail="Restarting stopped sandbox")
            _sandbox.start(timeout=90)
            return _sandbox
        except Exception:
            _sandbox = None

    # Reuse this app's solver sandbox from a previous run instead of piling up new ones.
    from daytona import ListSandboxesQuery
    for existing in _client.list(ListSandboxesQuery(labels={"app": "wayfound", "purpose": "venue-recovery-solver"})):
        state = str(existing.state).lower()
        if state.endswith(("started", "stopped")):
            if not state.endswith("started"):
                _status.update(state="starting", detail="Restarting the existing sandbox")
                existing.start(timeout=120)
            _sandbox = existing
            return _sandbox

    _status.update(state="creating", detail="Creating Daytona sandbox")
    _sandbox = _client.create(
        CreateSandboxFromSnapshotParams(
            language="python",
            labels={"app": "wayfound", "purpose": "venue-recovery-solver"},
            auto_stop_interval=30,
            auto_delete_interval=120,
        ),
        timeout=120,
    )
    return _sandbox


def warm_up() -> None:
    if mode() != "daytona":  # "hosted" needs no second sandbox
        return
    try:
        with _lock:
            _get_sandbox()
            _status.update(state="ready", detail="Sandbox ready")
    except Exception as e:  # surfaced via /api/health
        _status.update(state="error", detail=f"{type(e).__name__}: {e}")


def run_engine(payload: dict) -> tuple[dict, dict]:
    """Returns (engine result, execution metadata)."""
    m = mode()
    started = time.perf_counter()
    if m == "unconfigured":
        raise ExecutionError("DAYTONA_API_KEY is not set. Add it to .env (or set ALLOW_LOCAL_EXECUTION=true "
                             "for offline development only).")

    if m in ("local", "hosted"):
        proc = subprocess.run([sys.executable, "-I", str(ENGINE_PATH)], input=json.dumps(payload),
                              capture_output=True, text=True, timeout=60)
        if proc.returncode:
            raise ExecutionError(proc.stderr[-2000:])
        result = _parse(proc.stdout)
        hosted = m == "hosted"
        return result, {"engine": "daytona" if hosted else "local",
                        "sandboxId": config.HOSTED_SANDBOX_ID if hosted else None, "exitCode": proc.returncode,
                        "elapsedMs": round((time.perf_counter() - started) * 1000)}

    with _lock:
        try:
            sb = _get_sandbox()
            _status.update(state="running", detail=f"Running {payload['op']} in {sb.id}")
            resp = sb.process.code_run(_engine_program(payload), timeout=60)
        except Exception as e:
            _status.update(state="error", detail=f"{type(e).__name__}: {e}")
            raise ExecutionError(f"Daytona execution failed: {type(e).__name__}: {e}") from e
        _status.update(state="ready", detail="Sandbox ready")
    if resp.exit_code != 0:
        raise ExecutionError(f"Engine exited {resp.exit_code} in sandbox {sb.id}:\n{resp.result[-2000:]}")
    result = _parse(resp.result)
    return result, {"engine": "daytona", "sandboxId": sb.id, "exitCode": resp.exit_code,
                    "elapsedMs": round((time.perf_counter() - started) * 1000),
                    "sandboxRuntime": result.get("runtime")}
