/**
 * Step 1: Connection only so can debug!!!
 * Connect to Yellow sandbox WebSocket. Send nothing. Log every message received.
 * No auth, no keys, no payments — just verify can connect and see server behaviour.
 *
 * Run: npm run step1
 */

import WebSocket from "ws";

const SANDBOX_WS = "wss://clearnet-sandbox.yellow.com/ws";

function main() {
  console.log("Step 1: Connect to Yellow sandbox (no auth, no send)\n");
  console.log("Endpoint:", SANDBOX_WS);
  console.log("");

  const ws = new WebSocket(SANDBOX_WS);

  ws.on("open", () => {
    console.log("[open] Connected to Yellow Network\n");
  });

  ws.on("message", (data: WebSocket.Data) => {
    const raw = data.toString();
    console.log("[message] raw length:", raw.length);
    try {
      const parsed = JSON.parse(raw);
      console.log("[message] JSON:", JSON.stringify(parsed, null, 2));
    } catch {
      console.log("[message] (not JSON):", raw.slice(0, 200));
    }
    console.log("");
  });

  ws.on("error", (err) => {
    console.error("[error]", err);
  });

  ws.on("close", (code, reason) => {
    console.log("[close] code:", code, "reason:", reason?.toString() || "(none)");
    process.exit(code === 1000 ? 0 : 1);
  });

  // Let it run a few seconds so can see any initial server messages, then close
  setTimeout(() => {
    console.log("Closing after 8s (no messages sent)...\n");
    ws.close(1000);
  }, 8000);
}

main();
