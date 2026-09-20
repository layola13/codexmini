#!/usr/bin/env python3
"""SSE mock of the OpenAI Responses API for scodex-mini E2E tests.
Listens on 127.0.0.1:8080. Behavior:
  - Request without function_call_output -> SSE stream with one shell_exec function_call
  - Request with function_call_output  -> SSE stream with final text message
Uses Server-Sent Events format as required by stream:true.
"""
import http.server, json, sys

CALL_ID = "call_e2e_1"

def sse_event(data):
    """Format a single SSE event."""
    return ("data: %s\n\n" % json.dumps(data)).encode()

def sse_done():
    return b"data: [DONE]\n\n"

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

        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.end_headers()

        if has_fco:
            # SSE stream with final text message
            # response.created
            self.wfile.write(sse_event({"type": "response.created", "response": {"id": "resp_e2e_2"}}))
            # output item added (message)
            self.wfile.write(sse_event({
                "type": "response.output_item.added",
                "output_index": 0,
                "item": {"type": "message", "id": "msg_e2e_2", "role": "assistant"}
            }))
            # text delta
            self.wfile.write(sse_event({
                "type": "response.output_text.delta",
                "output_index": 0,
                "delta": "tool loop done"
            }))
            # output item done
            self.wfile.write(sse_event({
                "type": "response.output_item.done",
                "output_index": 0,
                "item": {
                    "type": "message",
                    "content": [{"type": "output_text", "text": "tool loop done"}]
                }
            }))
            # response completed
            self.wfile.write(sse_event({"type": "response.completed"}))
        else:
            # SSE stream with function_call
            self.wfile.write(sse_event({"type": "response.created", "response": {"id": "resp_e2e_1"}}))
            # function call item added
            self.wfile.write(sse_event({
                "type": "response.output_item.added",
                "output_index": 0,
                "item": {
                    "type": "function_call",
                    "id": CALL_ID,
                    "call_id": CALL_ID,
                    "name": "shell_exec"
                }
            }))
            # function call arguments delta
            args = json.dumps({"command": "echo hello-mock"})
            self.wfile.write(sse_event({
                "type": "response.function_call_arguments.delta",
                "output_index": 0,
                "delta": args
            }))
            # function call arguments done
            self.wfile.write(sse_event({
                "type": "response.function_call_arguments.done",
                "output_index": 0,
                "arguments": args
            }))
            # output item done
            self.wfile.write(sse_event({
                "type": "response.output_item.done",
                "output_index": 0,
                "item": {
                    "type": "function_call",
                    "call_id": CALL_ID,
                    "name": "shell_exec",
                    "arguments": args
                }
            }))
            self.wfile.write(sse_event({"type": "response.completed"}))

        self.wfile.write(sse_done())
        self.wfile.flush()

if __name__ == "__main__":
    srv = http.server.HTTPServer(("127.0.0.1", 8080), Handler)
    sys.stderr.write("mock: listening on 127.0.0.1:8080 (SSE)\n")
    srv.serve_forever()
