/**
 * Step 2a: Send auth request only. testing nitrolite.
 * Connect, send one auth request (using Nitrolite), log every message.
 * NOT replying reply to auth_challenge yet — just verify the server sends it.
 *
 * Success = we see a message with method "auth_challenge" in the log.
 *
 * Run: npm run step2a
 * Prereq: .env with PRIVATE_KEY
 */

import "dotenv/config";
import WebSocket from "ws";
import { privateKeyToAccount, generatePrivateKey } from "viem/accounts";
import { createAuthRequestMessage } from "@erc7824/nitrolite";

const SANDBOX_WS = "wss://clearnet-sandbox.yellow.com/ws";

function getEnv(name: string): string {
  const v = process.env[name];
  if (!v) throw new Error(`Missing env: ${name}. Copy .env.example to .env and set PRIVATE_KEY.`);
  return v;
}

async function main() {
  const rawKey = getEnv("PRIVATE_KEY");
  const privateKey = rawKey.startsWith("0x") ? (rawKey as `0x${string}`) : (`0x${rawKey}` as `0x${string}`);
  const account = privateKeyToAccount(privateKey);
  const sessionAccount = privateKeyToAccount(generatePrivateKey());

  const authParams = {
    session_key: sessionAccount.address,
    allowances: [{ asset: "ytest.usd", amount: "1000000000" }],
    expires_at: BigInt(Math.floor(Date.now() / 1000) + 3600),
    scope: "agentpay.steps",
  };

  const authRequestMsg = await createAuthRequestMessage({
    address: account.address,
    application: "AgentPay steps",
    ...authParams,
  });

  console.log("Step 2a: Connect and send auth request (do not reply to challenge)\n");
  console.log("Endpoint:", SANDBOX_WS);
  console.log("Wallet:", account.address);
  console.log("");

  const ws = new WebSocket(SANDBOX_WS);

  ws.on("open", () => {
    console.log("[open] Connected, sending auth request...\n");
    ws.send(authRequestMsg);
  });

  ws.on("message", (data: WebSocket.Data) => {
    const raw = data.toString();
    try {
      const parsed = JSON.parse(raw) as { res?: unknown[]; error?: { message?: string } };
      if (parsed.error) {
        console.log("[message] error:", parsed.error.message ?? parsed.error);
        return;
      }
      const res = parsed.res as unknown[] | undefined;
      const method = res?.[1] as string | undefined;
      if (method) console.log("[message] method:", method);
      console.log("[message] raw length:", raw.length);
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

  setTimeout(() => {
    console.log("Closing after 10s...\n");
    ws.close(1000);
  }, 10000);
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
