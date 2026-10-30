"""Sandbox guarantees (Phase 2): no network, hard timeout, failures
recorded honestly. These run the real sandbox runner."""
from variant_research_agent import sandbox

_OK_SCRIPT = '''
import json
with open("inputs.json") as f:
    data = json.load(f)
payload = {"summary": "doubled the input", "results": {"value": data["x"] * 2},
           "has_content": True}
with open("result.json", "w") as f:
    json.dump(payload, f)
print("done")
'''


def test_sandbox_happy_path():
    r = sandbox.run_script("toy", _OK_SCRIPT, {"x": 21}, timeout=10)
    assert r.status == "ok"
    assert r.counts_as_evidence is True
    assert r.results == {"value": 42}
    assert r.script_sha256  # source hash recorded for the trace
    assert "doubled the input" in r.summary


def test_sandbox_blocks_network_socket():
    src = ('import socket\n'
           's = socket.socket()\n'
           'print("SOCKET_CREATED")\n')
    r = sandbox.run_script("net", src, {}, timeout=10)
    assert r.status == "failed"
    assert r.counts_as_evidence is False
    assert "SOCKET_CREATED" not in r.stdout


def test_sandbox_blocks_network_connection():
    src = ('import socket\n'
           'c = socket.create_connection(("93.184.216.34", 80), timeout=5)\n'
           'print("NETWORK_OPEN")\n')
    r = sandbox.run_script("net", src, {}, timeout=10)
    assert r.status == "failed"
    assert r.counts_as_evidence is False
    assert "NETWORK_OPEN" not in r.stdout
    assert "network access is disabled" in (r.stderr or "")


def test_sandbox_timeout():
    r = sandbox.run_script("slow", "import time\ntime.sleep(120)\n", {},
                           timeout=2)
    assert r.status == "timeout"
    assert r.counts_as_evidence is False
    assert r.duration_s < 30  # killed promptly, not after 120 s


def test_sandbox_exception_is_a_failed_analysis():
    r = sandbox.run_script("boom", "raise ValueError('boom')\n", {},
                           timeout=10)
    assert r.status == "failed"
    assert r.counts_as_evidence is False
    assert "ValueError" in (r.error or "") or "ValueError" in r.stderr


def test_sandbox_missing_result_json_is_failed():
    r = sandbox.run_script("silent", "print('hello')\n", {}, timeout=10)
    assert r.status == "failed"
    assert "result.json" in (r.error or "")
    assert r.counts_as_evidence is False
