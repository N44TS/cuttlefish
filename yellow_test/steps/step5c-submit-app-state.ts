/**
 * Step 5c: Submit one app state (signed state update) in an existing app session.
 * After auth we get_app_sessions, then submit_app_state for the first session with
 * a minimal state (intent operate, version+1, zero allocations). Success = server accepts.
 *
 * Run: npm run step5c
 * Prereq: .env with PRIVATE_KEY and WORKER_ADDRESS. At least one open app session (run step5a first).
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
  createSubmitAppStateMessage,
  createECDSAMessageSigner,
  RPCProtocolVersion,
  RPCAppStateIntent,
} from "@erc7824/nitrolite";

const SANDBOX_WS = "wss://clearnet-sandbox.yellow.com/ws";

function getEnv(name: string): string {
  const v = process.env[name];
  if (!v) throw new Error(`Missing env: ${name}. Copy .env.example to .env and set PRIVATE_KEY, WORKER_ADDRESS.`);
  return v;
}

async function main() {
  const rawKey = getEnv("PRIVATE_KEY");
  const privateKey = rawKey.startsWith("0x") ? (rawKey as `0x${string}`) : (`0x${rawKey}` as `0x${string}`);
  const workerAddressRaw = getEnv("WORKER_ADDRESS");
  const workerAddress = workerAddressRaw.startsWith("0x") ? (workerAddressRaw as `0x${string}`) : (`0x${workerAddressRaw}` as `0x${string}`);
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
    application: "agentpay.steps.escrow", // must match app session so session key can sign submit_app_state
    ...authParams,
  });

  console.log("Step 5c: Auth + get app sessions + submit one app state\n");
  console.log("Endpoint:", SANDBOX_WS);
  console.log("Wallet (client):", account.address);
  console.log("Worker:", workerAddress);
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
        ws.send(await createGetAppSessionsMessage(sessionSigner, account.address));
        return;
      }

      if (method === "get_app_sessions" && payload) {
        const sessions = (payload.appSessions ?? payload.app_sessions) as Record<string, unknown>[] | undefined;
        const openSessions = sessions?.filter((s) => (s.status ?? (s as { status?: string }).status) === "open") ?? [];
        // Prefer session with quorum 1 so client can submit state alone (5a now creates with quorum 1)
        const session = openSessions.find((s) => (s.quorum as number) === 1) ?? openSessions[0] ?? sessions?.[0];
        if (!session) {
          console.log("[action] No app session found. Run step5a first.\n");
          setTimeout(() => ws.close(1000), 2000);
          return;
        }
        const appSessionId = (session.appSessionId ?? session.app_session_id) as `0x${string}`;
        const currentVersion = (session.version as number) ?? 1;
        const nextVersion = currentVersion + 1;
        console.log("[action] Using session:", appSessionId, "current version:", currentVersion, "- sending submit_app_state (version", nextVersion + ")...\n");
        const submitMsg = await createSubmitAppStateMessage(
          sessionSigner,
          {
            app_session_id: appSessionId,
            intent: RPCAppStateIntent.Operate,
            version: nextVersion,
            allocations: [
              { asset: "ytest.usd", amount: "0", participant: account.address as `0x${string}` },
              { asset: "ytest.usd", amount: "0", participant: workerAddress },
            ],
          },
          undefined,
          undefined
        );
        ws.send(submitMsg);
        return;
      }

      if (method === "submit_app_state" && payload) {
        const ver = payload.version;
        const status = payload.status;
        console.log("[action] App state submitted. version:", ver, "status:", status);
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
