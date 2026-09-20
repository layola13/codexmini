#!/usr/bin/env python3
"""Compaction E2E mock for scodex-mini.
Listens on 127.0.0.1:PORT (argv[1], default 8081). Logs every request body to
LOGFILE (argv[2], default /tmp/mock_compact_requests.jsonl) as one JSON object
per line: {"type": "compact"|"normal", "body_len": N, "body": "<raw>"}.

Behavior:
  - Request whose raw body contains "SCODEX_COMPACT_REQ" -> summarization.
    Extracts every line containing "DECISION_" from the raw body and returns a
    Responses-API summary message that preserves them verbatim.
  - Any other request -> plain text "ok" (no tool calls, keeps the E2E simple).
Both are plain (non-SSE) JSON responses.
"""
import http.server, json, os, sys

PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8081
LOGFILE = sys.argv[2] if len(sys.argv) > 2 else "/tmp/mock_compact_requests.jsonl"

SUMMARY_MARK = "SCODEX_COMPACT_REQ"


def extract_decisions(raw_text):
    seen = []
    for line in raw_text.splitlines():
        if "DECISION_" in line:
            s = line.strip()
            if s and s not in seen:
                seen.append(s)
    return seen


class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_POST(self):
        n = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(n)
        try:
            text = body.decode("utf-8", "replace")
        except Exception:
            text = ""
        is_compact = SUMMARY_MARK in text
        with open(LOGFILE, "a", encoding="utf-8") as f:
            f.write(json.dumps({
                "type": "compact" if is_compact else "normal",
                "body_len": len(body),
                "body": text,
            }, ensure_ascii=False) + "\n")
        if is_compact:
            decisions = extract_decisions(text)
            lines = ["以下是本会话早前部分的压缩摘要（非原文）。"]
            lines.append("早前对话包含多轮用户提问与助手回答，主题为常规测试对话。")
            lines.append("关键决策记录：")
            for d in decisions:
                lines.append(d)
            if not decisions:
                lines.append("（未发现 DECISION_ 记录）")
            payload = {"output": [
                {"type": "message",
                 "content": [{"type": "output_text",
                              "text": "\n".join(lines)}]}
            ]}
            data = json.dumps(payload, ensure_ascii=False).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
        else:
            # Minimal Responses SSE: one text delta then completed.
            ev1 = 'data: {"type": "response.output_text.delta", "delta": "ok"}\n\n'
            ev2 = 'data: {"type": "response.completed"}\n\n'
            data = (ev1 + ev2).encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)


if __name__ == "__main__":
    # truncate log on start
    open(LOGFILE, "w").close()
    srv = http.server.HTTPServer(("127.0.0.1", PORT), Handler)
    sys.stderr.write("mock_compact: listening on 127.0.0.1:%d log=%s\n" % (PORT, LOGFILE))
    srv.serve_forever()
