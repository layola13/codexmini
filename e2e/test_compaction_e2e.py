#!/usr/bin/env python3
"""Compaction E2E: 200-turn mock session, resume triggers summarization.
Verifies:
  1. Mock received exactly one SCODEX_COMPACT_REQ summarization request.
  2. The final resume request contains the "以下是压缩摘要" marker.
  3. All 3 DECISION_* lines are preserved in the final request.
  4. Estimated tokens of the final request < 32000.
  5. The summarized raw text does not appear verbatim (no duplication).

Usage: python3 e2e/test_compaction_e2e.py <binary> [turns]
Env: SCODEX_BASE_URL must point at mock_compaction.py (port 8081).
"""
import json, os, subprocess, sys, time

BINARY = sys.argv[1]
TURNS = int(sys.argv[2]) if len(sys.argv) > 2 else 200
LOGFILE = "/tmp/mock_compact_requests.jsonl"
HOME = "/tmp/e2e-compact-home"

ENV = dict(os.environ)
ENV["HOME"] = HOME
ENV["SCODEX_BASE_URL"] = "http://127.0.0.1:8081/v1"
ENV["OPENAI_API_KEY"] = "sk-test"
# keep default budget 32000


def run(args, prompt_text=None):
    cmd = [BINARY] + args
    if prompt_text is not None:
        cmd.append(prompt_text)
    r = subprocess.run(cmd, capture_output=True, text=True, env=ENV, timeout=120)
    return r


def main():
    os.system("rm -rf " + HOME)
    os.makedirs(HOME, exist_ok=True)

    # 1. Create session with a first prompt.
    r = run([], "hello")
    assert r.returncode == 0, "initial run failed: %s\n%s" % (r.stdout, r.stderr)
    # session id should be 1
    r = run(["--list"])
    assert "id=1" in r.stdout or "1" in r.stdout, "no session listed: " + r.stdout

    pad = "x" * 900  # ~1KB per user message
    # 2. Build up TURNS turns via --resume. Plant decisions at fixed turns.
    for t in range(TURNS):
        extra = ""
        if t == 10:
            extra = " DECISION_ALPHA=use-postgres"
        elif t == 100:
            extra = " DECISION_BETA=retry-5-times"
        elif t == 190:
            extra = " DECISION_GAMMA=cache-ttl-60"
        prompt = "turn %d %s%s" % (t, pad, extra)
        r = run(["--resume", "1"], prompt)
        if r.returncode != 0:
            print("resume failed at turn %d: %s\n%s" % (t, r.stdout, r.stderr))
            sys.exit(1)
        if t % 50 == 0:
            print("... turn %d/%d" % (t, TURNS), flush=True)

    # 3. Final resume triggers compaction (history >> 32k budget).
    r = run(["--resume", "1"], "final question " + pad)
    assert r.returncode == 0, "final resume failed: %s\n%s" % (r.stdout, r.stderr)
    print("final resume ok", flush=True)

    # 4. Analyze logged requests.
    reqs = [json.loads(l) for l in open(LOGFILE, encoding="utf-8") if l.strip()]
    compacts = [q for q in reqs if q["type"] == "compact"]
    normals = [q for q in reqs if q["type"] == "normal"]
    print("total requests: %d, normal: %d, compact: %d"
          % (len(reqs), len(normals), len(compacts)))

    ok = True
    def check(name, cond, detail=""):
        global ok
        status = "PASS" if cond else "FAIL"
        if not cond:
            ok = False
        print("[%s] %s %s" % (status, name, detail))

    check("exactly one summarization request", len(compacts) == 1,
          "(got %d)" % len(compacts))

    final = reqs[-1]
    check("final request is a normal (conversation) request",
          final["type"] == "normal")
    body = final["body"]
    check("summary marker present",
          "以下是压缩摘要" in body)
    check("marker says non-verbatim",
          "非原文" in body)
    for d in ["DECISION_ALPHA=use-postgres",
              "DECISION_BETA=retry-5-times",
              "DECISION_GAMMA=cache-ttl-60"]:
        check("decision preserved: " + d.split("=")[0], d in body)
    # token estimate: ceil(bytes/3) + 512 overhead (conservative)
    est = (len(body.encode("utf-8")) + 2) // 3 + 512
    check("final request est tokens < 32000", est < 32000, "(est=%d)" % est)
    # The summarized portion must not appear as raw duplicate text:
    # raw turn markers "turn 10 " etc. from the compacted region should be gone.
    # We only assert the compacted region's distinctive padding-run is absent;
    # the summary itself contains the decisions.
    check("no raw duplicate of compacted turns",
          body.count("turn 10 " + "x" * 50) == 0)

    if compacts:
        cbody = compacts[0]["body"]
        check("summarization request carries marker id",
              "SCODEX_COMPACT_REQ" in cbody)
        check("summarization request is non-streaming (no stream flag)",
              '"stream":true' not in cbody and '"stream": true' not in cbody)

    print("E2E_RESULT:", "PASS" if ok else "FAIL")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
