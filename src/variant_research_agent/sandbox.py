"""Sandboxed execution of agent-generated analysis scripts (Phase 2).

Design (be precise about what this is and is not — see
PHASE2_REPORT.md): each script runs as a subprocess of the project's
own interpreter in a fresh temporary directory, with

- a wrapper that replaces the socket API with stubs that raise, so
  any network attempt fails inside the script;
- a scrubbed environment (no proxy variables, no user site-packages,
  HOME and TMPDIR pointed at the sandbox dir);
- Unix resource limits (CPU seconds, max file size, no core dumps)
  set in the child before exec;
- a hard wall-clock timeout (default 30 s) enforced by subprocess;
- stdout/stderr captured, and the script source + outputs returned
  for the run trace.

The working directory is the sandbox dir and inputs arrive as
inputs.json in that dir; the script reports by writing result.json
there. After the run the directory is deleted.

This is process isolation plus timeouts around OUR OWN template
scripts. It is a prudence boundary, not a security proof against
hostile code: a determined script running as the same OS user could
still attempt filesystem access outside its directory. The generated
scripts are therefore also constrained by construction (stdlib-only
templates; LLM proposals are token-screened) — defence in depth, not
a guarantee.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Optional

from .schema import AnalysisResult

DEFAULT_TIMEOUT = 30.0

# Wrapper executed instead of the analysis script. It neuters the
# socket layer, then runs the script as __main__. Any exception in
# the script propagates: non-zero exit + traceback on stderr, which
# the runner records as a FAILED analysis.
_RUNNER = '''\
import runpy
import socket
import sys


class _BlockedSocket:
    """Any socket construction raises — the sandbox has no network."""

    def __init__(self, *args, **kwargs):
        raise OSError("network access is disabled in the analysis sandbox")


def _blocked(*args, **kwargs):
    raise OSError("network access is disabled in the analysis sandbox")


socket.socket = _BlockedSocket
socket.create_connection = _blocked
socket.create_server = _blocked
socket.getaddrinfo = _blocked
socket.gethostbyname = _blocked
socket.gethostbyname_ex = _blocked
socket.getnameinfo = _blocked

sys.argv = ["analysis.py"]
runpy.run_path("analysis.py", run_name="__main__")
'''


def _limits(timeout: float):
    """preexec_fn: cap CPU time and file writes in the child."""
    import resource

    def _apply() -> None:
        cpu = max(1, int(timeout) + 5)
        try:
            resource.setrlimit(resource.RLIMIT_CPU, (cpu, cpu))
        except (ValueError, OSError):
            pass
        try:
            resource.setrlimit(resource.RLIMIT_FSIZE, (16 * 1024 * 1024,) * 2)
        except (ValueError, OSError):
            pass
        try:
            resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
        except (ValueError, OSError):
            pass

    return _apply


def _sandbox_env(sandbox_dir: str) -> dict:
    """A minimal environment: no proxies, no inherited credentials,
    no user site-packages; HOME/TMPDIR inside the sandbox."""
    return {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "HOME": sandbox_dir,
        "TMPDIR": sandbox_dir,
        "LANG": "C.UTF-8",
        "PYTHONNOUSERSITE": "1",
        "PYTHONDONTWRITEBYTECODE": "1",
        "VRA_SANDBOX": "1",
    }


def run_script(name: str, source: str, inputs: dict,
               timeout: float = DEFAULT_TIMEOUT,
               origin: str = "template") -> AnalysisResult:
    """Execute one analysis script in the sandbox and record the run.

    Contract for scripts: read inputs.json from the cwd, write
    result.json ({"summary": str, "results": {...},
    "has_content": bool}) to the cwd. A script that errors, times
    out, or never writes result.json is a FAILED analysis — recorded,
    never hidden, and never counted as evidence.
    """
    sha = hashlib.sha256(source.encode("utf-8")).hexdigest()
    sandbox_dir = tempfile.mkdtemp(prefix="vra_sandbox_")
    started = time.monotonic()
    try:
        Path(sandbox_dir, "inputs.json").write_text(json.dumps(inputs))
        Path(sandbox_dir, "analysis.py").write_text(source)
        Path(sandbox_dir, "_runner.py").write_text(_RUNNER)
        timed_out = False
        try:
            proc = subprocess.run(
                [sys.executable, "_runner.py"],
                cwd=sandbox_dir, env=_sandbox_env(sandbox_dir),
                capture_output=True, text=True, timeout=timeout,
                preexec_fn=_limits(timeout) if os.name == "posix" else None)
            stdout, stderr, exit_code = proc.stdout, proc.stderr, proc.returncode
        except subprocess.TimeoutExpired as e:
            timed_out = True
            stdout = (e.stdout or b"").decode("utf-8", "replace") \
                if isinstance(e.stdout, bytes) else (e.stdout or "")
            stderr = (e.stderr or b"").decode("utf-8", "replace") \
                if isinstance(e.stderr, bytes) else (e.stderr or "")
            exit_code = None
        duration = time.monotonic() - started

        base = dict(name=name, script=source, script_sha256=sha,
                    stdout=stdout[-8000:], stderr=stderr[-8000:],
                    exit_code=exit_code, duration_s=round(duration, 3),
                    origin=origin)
        if timed_out:
            return AnalysisResult(
                status="timeout", **base,
                error=f"script exceeded the {timeout:g}s sandbox timeout "
                      "and was killed")
        if exit_code != 0:
            tail = stderr.strip().splitlines()
            return AnalysisResult(
                status="failed", **base,
                error=(tail[-1] if tail else f"script exited with code {exit_code}"))
        result_path = Path(sandbox_dir, "result.json")
        if not result_path.exists():
            return AnalysisResult(
                status="failed", **base,
                error="script exited 0 but wrote no result.json "
                      "(contract violation)")
        try:
            payload = json.loads(result_path.read_text())
        except ValueError as e:
            return AnalysisResult(
                status="failed", **base,
                error=f"result.json is not valid JSON: {e}")
        results = payload.get("results") or {}
        has_content = bool(payload.get("has_content")) and bool(results)
        return AnalysisResult(
            status="ok" if has_content else "no_content",
            summary=str(payload.get("summary") or ""),
            results=results, counts_as_evidence=has_content, **base)
    finally:
        shutil.rmtree(sandbox_dir, ignore_errors=True)
