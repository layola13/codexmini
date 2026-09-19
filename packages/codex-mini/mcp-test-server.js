#!/usr/bin/env node
// mcp-test-server.js — minimal MCP server over stdio for connectivity testing.
// Tools: echo(text) -> echoes back, add(a, b) -> sum.
const readline = require("readline");

const TOOLS = [
  {
    name: "echo",
    description: "Echo back the input text. Use to test MCP connectivity.",
    inputSchema: {
      type: "object",
      properties: {
        text: { type: "string", description: "Text to echo back." },
      },
      required: ["text"],
    },
  },
  {
    name: "add",
    description: "Add two numbers and return the sum.",
    inputSchema: {
      type: "object",
      properties: {
        a: { type: "number", description: "First number." },
        b: { type: "number", description: "Second number." },
      },
      required: ["a", "b"],
    },
  },
];

function reply(id, result) {
  console.log(JSON.stringify({ jsonrpc: "2.0", id, result }));
}
function replyError(id, code, message) {
  console.log(JSON.stringify({ jsonrpc: "2.0", id, error: { code, message } }));
}

const rl = readline.createInterface({ input: process.stdin, terminal: false });
rl.on("line", (line) => {
  line = line.trim();
  if (!line) return;
  let msg;
  try { msg = JSON.parse(line); } catch { return; }
  if (msg.method === "initialize") {
    reply(msg.id, {
      protocolVersion: "2024-11-05",
      capabilities: { tools: {} },
      serverInfo: { name: "mcp-test-server", version: "0.1.0" },
    });
  } else if (msg.method === "notifications/initialized") {
    // no-op
  } else if (msg.method === "tools/list") {
    reply(msg.id, { tools: TOOLS });
  } else if (msg.method === "tools/call") {
    const name = msg.params && msg.params.name;
    const args = (msg.params && msg.params.arguments) || {};
    if (name === "echo") {
      reply(msg.id, { content: [{ type: "text", text: "echo: " + String(args.text || "") }] });
    } else if (name === "add") {
      const sum = Number(args.a || 0) + Number(args.b || 0);
      reply(msg.id, { content: [{ type: "text", text: "sum: " + sum }] });
    } else {
      replyError(msg.id, -32602, "unknown tool: " + name);
    }
  } else if (msg.id !== undefined) {
    replyError(msg.id, -32601, "method not found: " + msg.method);
  }
});
