/**
 * Step 5b: After auth, send get_app_sessions and log the list.
 * Success = we see our app session(s) (e.g. from step5a).
 *
 * Run: npm run step5b
 * Prereq: .env with PRIVATE_KEY.
 */

import "dotenv/config";
import WebSocket from "ws";
import { createWalletClient, http } from "viem";
import { sepolia } from "viem/chains";
import { privateKeyToAccount, generatePrivateKey } from "viem/accounts";
import {
  createAuthRequestMessage,
  createAuthVerifyMessageFromChallenge,
  createEIP712AuthMessageSigner,
  createGetAppSessionsMessage,
  createECDSAMessageSigner,
} from "@erc7824/nitrolite";

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
  const sessionPrivateKey = generatePrivateKey();
  const sessionAccount = privateKeyToAccount(sessionPrivateKey);
  const sessionSigner = createECDSAMessageSigner(sessionPrivateKey);

  const rpcUrl = process.env.ALCHEMY_RPC_URL ?? process.env.SEPOLIA_RPC_URL ?? "https://1rpc.io/sepolia";
  const walletClient = createWalletClient({
    chain: sepolia,
    transport: http(rpcUrl),
    account,
  });
  if (!walletClient) throw new Error("Wallet client failed");

  const authParams = {
    session_key: sessionAccount.address,
    allowances: [{ asset: "ytest.usd", amount: "1000000000" }],
    expires_at: BigInt(Math.floor(Date.now() / 1000) + 3600),
    scope: "agentpay.steps",
  };

  const authRequestMsg = await createAuthRequestMessage({
    address: account.address,
    application: "agentpay.steps.escrow", // match app session application so we can use sessions in 5c
    ...authParams,
  });

  console.log("Step 5b: Auth + get app sessions\n");
  console.log("Endpoint:", SANDBOX_WS);
  console.log("Wallet:", account.address);
  console.log("");

  const ws = new WebSocket(SANDBOX_WS);

  ws.on("open", () => {
    console.log("[open] Connected, sending auth request...\n");
    ws.send(authRequestMsg);
  });

  ws.on("message", async (data: WebSocket.Data) => {
    const raw = data.toString();
    try {
      const parsed = JSON.parse(raw) as { res?: unknown[]; error?: { message?: string } };
      if (parsed.error) {
        console.log("[message] error:", parsed.error.message ?? parsed.error);
        return;
      }
      const res = parsed.res as unknown[] | undefined;
      const method = res?.[1] as string | undefined;
      const payload = res?.[2] as Record<string, unknown> | undefined;

      if (method) console.log("[message] method:", method);

      if (method === "auth_challenge") {
        const challenge = (payload?.challenge_message as string) ?? "";
        const signer = createEIP712AuthMessageSigner(walletClient, authParams, {
          name: "agentpay.steps.escrow",
        });
        const verifyMsg = await createAuthVerifyMessageFromChallenge(signer, challenge);
        ws.send(verifyMsg);
        console.log("[action] Sent auth_verify\n");
        return;
      }

      if (method === "auth_verify") {
        console.log("[action] Authenticated, sending get_app_sessions...\n");
        const getSessionsMsg = await createGetAppSessionsMessage(sessionSigner, account.address);
        ws.send(getSessionsMsg);
        return;
      }

      // Server can return appSessions or app_sessions
      if (method === "get_app_sessions" && payload) {
        const sessions = (payload.appSessions ?? payload.app_sessions) as Record<string, unknown>[] | undefined;
        if (!sessions?.length) {
          console.log("[action] App sessions: (none)");
        } else {
          console.log("[action] App sessions:", sessions.length);
          sessions.forEach((s, i) => {
            const id = s.appSessionId ?? s.app_session_id;
            const app = (s as { application?: string }).application ?? "";
            const status = s.status;
            const version = s.version;
            console.log(`  ${i + 1}. ${id}  application: ${app}  status: ${status}  version: ${version}`);
          });
        }
        console.log("");
        setTimeout(() => ws.close(1000), 2000);
        return;
      }

      if (method === "error") {
        console.error("[message] Server error:", JSON.stringify(payload ?? res, null, 2));
        return;
      }

      if (method !== "assets") {
        console.log("[message] raw length:", raw.length);
      }
    } catch (e) {
      console.log("[message] (parse error):", (e as Error).message);
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
    console.log("Closing after 30s...\n");
    ws.close(1000);
  }, 30000);
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
