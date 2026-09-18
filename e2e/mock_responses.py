#!/usr/bin/env python3
"""Plain-HTTP mock of the OpenAI Responses API for scodex-mini E2E tests.
Listens on 127.0.0.1:8080. Behavior:
  - Request without function_call_output -> one shell_exec function_call
  - Request with function_call_output  -> final text message
"""
import http.server, json, sys

CALL_ID = "call_e2e_1"

class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_POST(self):
        n = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(n)
        try:
            req = json.loads(body)
        except Exception:
            req = {}
        inputs = req.get("input", [])
        kinds = []
        for it in inputs:
            if isinstance(it, dict):
                t = it.get("type", "?")
                kinds.append(t if t != "?" else "role=%s" % it.get("role", "?"))
        sys.stderr.write("mock: input items=%d kinds=%s\n" % (len(inputs), ",".join(kinds)))
        sys.stderr.flush()
        has_fco = any(isinstance(it, dict) and it.get("type") == "function_call_output" for it in inputs)
        if has_fco:
            payload = {"output": [
                {"type": "message",
                 "content": [{"type": "output_text", "text": "tool loop done"}]}
            ]}
        else:
            payload = {"output": [
                {"type": "function_call",
                 "call_id": CALL_ID,
                 "name": "shell_exec",
                 "arguments": json.dumps({"command": "echo hello-mock"})}
            ]}
        data = json.dumps(payload).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

if __name__ == "__main__":
    srv = http.server.HTTPServer(("127.0.0.1", 8080), Handler)
    sys.stderr.write("mock: listening on 127.0.0.1:8080\n")
    srv.serve_forever()
