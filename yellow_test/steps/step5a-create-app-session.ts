/**
 * Step 5a: Create an application session (Nitrolite app session).
 * After auth we send create_app_session; when server responds we log app_session_id.
 * Sandbox requires two participants (client + worker). We use WORKER_ADDRESS as second.
 *
 * Run: npm run step5a
 * Prereq: .env with PRIVATE_KEY and WORKER_ADDRESS (any Sepolia address; can be a second wallet for 5d).
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
  createAppSessionMessage,
  createECDSAMessageSigner,
  RPCProtocolVersion,
} from "@erc7824/nitrolite";

const SANDBOX_WS = "wss://clearnet-sandbox.yellow.com/ws";

// App definition: two participants (client + worker) — sandbox requires exactly two.
const APPLICATION_NAME = "agentpay.steps.escrow";

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
    application: APPLICATION_NAME, // must match app session so session key can sign for it
    ...authParams,
  });

  // App definition: two participants (client + worker). quorum: 1 so the client can submit state alone in 5c; 5d will need both to sign for real bilateral flow.
  const definition = {
    application: APPLICATION_NAME,
    protocol: RPCProtocolVersion.NitroRPC_0_4,
    participants: [account.address, workerAddress] as `0x${string}`[],
    weights: [1, 1],
    quorum: 1,
    challenge: 3600,
    nonce: Math.floor(Date.now() / 1000), // unique per session; server requires non-zero
  };

  // Initial allocation: zero amount per participant (just creating the session).
  const allocations = [
    { asset: "ytest.usd", amount: "0", participant: account.address as `0x${string}` },
    { asset: "ytest.usd", amount: "0", participant: workerAddress },
  ];

  console.log("Step 5a: Auth + create app session (client + worker)\n");
  console.log("Endpoint:", SANDBOX_WS);
  console.log("Wallet (client):", account.address);
  console.log("Worker:", workerAddress);
  console.log("Application:", APPLICATION_NAME);
  console.log("");

  const ws = new WebSocket(SANDBOX_WS);

  ws.on("open", () => {
    console.log("[open] Connected, sending auth request...\n");
    ws.send(authRequestMsg);
  });

  ws.on("message", async (data: WebSocket.Data) => {
    const raw = data.toString();
    try {
      const parsed = JSON.parse(raw) as { res?: unknown[]; error?: { message?: string; code?: number } };
      if (parsed.error) {
        console.log("[message] error:", parsed.error.message ?? parsed.error, parsed.error.code ?? "");
        return;
      }
      const res = parsed.res as unknown[] | undefined;
      const method = res?.[1] as string | undefined;
      const payload = res?.[2] as Record<string, unknown> | undefined;

      if (method) console.log("[message] method:", method);

      if (method === "auth_challenge") {
        const challenge = (payload?.challenge_message as string) ?? "";
        const signer = createEIP712AuthMessageSigner(walletClient, authParams, {
          name: APPLICATION_NAME,
        });
        const verifyMsg = await createAuthVerifyMessageFromChallenge(signer, challenge);
        ws.send(verifyMsg);
        console.log("[action] Sent auth_verify\n");
        return;
      }

      if (method === "auth_verify") {
        console.log("[action] Authenticated, sending create_app_session...\n");
        const createAppMsg = await createAppSessionMessage(sessionSigner, {
          definition,
          allocations,
        });
        ws.send(createAppMsg);
        return;
      }

      if (method === "create_app_session" && payload) {
        const appSessionId = payload.app_session_id ?? payload.appSessionId;
        const version = payload.version;
        const status = payload.status;
        console.log("[action] App session created.");
        console.log("[action] app_session_id:", appSessionId);
        console.log("[action] version:", version, "status:", status);
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
