#!/usr/bin/env node
// mcp-bridge.js — minimal MCP stdio client bridge for scodex-mini.
// Usage:
//   node mcp-bridge.js --server "<cmd>" list
//   node mcp-bridge.js --server "<cmd>" call <tool_name> <args_json_file>
// Speaks JSON-RPC 2.0 over stdio: initialize -> notifications/initialized
// -> tools/list | tools/call. Prints result JSON to stdout, exits.
const { spawn } = require("child_process");
const fs = require("fs");

function parseArgs(argv) {
  let server = null;
  let rest = [];
  for (let i = 0; i < argv.length; i++) {
    if (argv[i] === "--server" && i + 1 < argv.length) {
      server = argv[++i];
    } else {
      rest.push(argv[i]);
    }
  }
  return { server, rest };
}

async function main() {
  const { server, rest } = parseArgs(process.argv.slice(2));
  if (!server) {
    console.error("mcp-bridge: missing --server");
    process.exit(2);
  }
  const mode = rest[0];
  if (mode !== "list" && mode !== "call") {
    console.error("mcp-bridge: mode must be list|call");
    process.exit(2);
  }

  const child = spawn("sh", ["-c", server], { stdio: ["pipe", "pipe", "inherit"] });
  let buf = "";
  let nextId = 1;
  const pending = new Map();

  child.stdout.setEncoding("utf8");
  child.stdout.on("data", (chunk) => {
    buf += chunk;
    let idx;
    while ((idx = buf.indexOf("\n")) >= 0) {
      const line = buf.slice(0, idx).trim();
      buf = buf.slice(idx + 1);
      if (!line) continue;
      let msg;
      try { msg = JSON.parse(line); } catch { continue; }
      if (msg.id !== undefined && pending.has(msg.id)) {
        pending.get(msg.id).resolve(msg);
        pending.delete(msg.id);
      }
    }
  });

  function send(obj) {
    return new Promise((resolve, reject) => {
      if (obj.id !== undefined) pending.set(obj.id, { resolve, reject, method: obj.method });
      else resolve();
      child.stdin.write(JSON.stringify(obj) + "\n", (err) => {
        if (err) reject(err);
      });
    });
  }

  function request(method, params) {
    const id = nextId++;
    return send({ jsonrpc: "2.0", id, method, params: params || {} });
  }

  child.on("error", (e) => {
    console.error("mcp-bridge: spawn failed: " + e.message);
    process.exit(1);
  });

  // If the server dies mid-handshake (e.g. instant exit), pending requests
  // would hang forever. Reject them so the caller gets an explicit error.
  let exited = false;
  child.on("exit", (code, signal) => {
    exited = true;
    const why = signal ? ("signal " + signal) : ("code " + code);
    for (const [id, p] of pending) {
      p.reject(new Error("mcp server exited during " + p.method + " (" + why + ")"));
    }
    pending.clear();
  });

  try {
    // 1. initialize
    const initResp = await request("initialize", {
      protocolVersion: "2024-11-05",
      capabilities: {},
      clientInfo: { name: "scodex-mini", version: "0.1.0" },
    });
    if (initResp.error) throw new Error("initialize: " + JSON.stringify(initResp.error));
    // 2. notifications/initialized
    await send({ jsonrpc: "2.0", method: "notifications/initialized" });

    if (mode === "list") {
      const resp = await request("tools/list", {});
      if (resp.error) throw new Error("tools/list: " + JSON.stringify(resp.error));
      console.log(JSON.stringify(resp.result || { tools: [] }));
    } else {
      const toolName = rest[1];
      const argsFile = rest[2];
      if (!toolName || !argsFile) throw new Error("call needs <tool> <args_file>");
      const argsJson = fs.readFileSync(argsFile, "utf8");
      let args;
      try { args = JSON.parse(argsJson); } catch { args = {}; }
      const resp = await request("tools/call", { name: toolName, arguments: args });
      if (resp.error) throw new Error("tools/call: " + JSON.stringify(resp.error));
      // Extract text from content blocks.
      const result = resp.result || {};
      const parts = [];
      for (const c of result.content || []) {
        if (c.type === "text" && typeof c.text === "string") parts.push(c.text);
        else parts.push(JSON.stringify(c));
      }
      console.log(JSON.stringify({ text: parts.join("\n"), isError: !!result.isError }));
    }
  } catch (e) {
    console.error("mcp-bridge: " + e.message);
    process.exit(1);
  } finally {
    child.kill();
  }
}

main();
