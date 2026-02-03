/**
 * Step 4c: One off-chain transfer to WORKER_ADDRESS.
 * Assumes an open, funded channel exists (run step4a and step4b first).
 * After auth, when server sends "channels" with an open channel we send transfer;
 * when server responds with "transfer" we log success and exit.
 *
 * Run: npm run step4c
 * Prereq: .env with PRIVATE_KEY and WORKER_ADDRESS; step4a + step4b already run.
 */

import "dotenv/config";
import WebSocket from "ws";
import { createWalletClient, http } from "viem";
import { sepolia } from "viem/chains";
import { privateKeyToAccount, generatePrivateKey } from "viem/accounts";
import {
  createECDSAMessageSigner,
  createEIP712AuthMessageSigner,
  createAuthRequestMessage,
  createAuthVerifyMessageFromChallenge,
  createTransferMessage,
} from "@erc7824/nitrolite";

const SANDBOX_WS = "wss://clearnet-sandbox.yellow.com/ws";

// Small amount for one off-chain transfer (ytest.usd, 6 decimals: "1000000" = 1 ytest.usd)
const TRANSFER_AMOUNT = process.env.TRANSFER_AMOUNT ?? "1";

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
    application: "AgentPay steps",
    ...authParams,
  });

  console.log("Step 4c: Auth + one off-chain transfer to WORKER_ADDRESS (no close/withdraw)\n");
  console.log("Endpoint:", SANDBOX_WS);
  console.log("Wallet:", account.address);
  console.log("Worker (destination):", workerAddress);
  console.log("Amount:", TRANSFER_AMOUNT, "ytest.usd\n");

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
          name: "AgentPay steps",
        });
        const verifyMsg = await createAuthVerifyMessageFromChallenge(signer, challenge);
        ws.send(verifyMsg);
        console.log("[action] Sent auth_verify\n");
        return;
      }

      if (method === "auth_verify") {
        console.log("[action] Authenticated (waiting for channels)...\n");
        return;
      }

      if (method === "channels") {
        const channels = (payload?.channels as { status?: string; channel_id?: string; amount?: string }[]) ?? [];
        const open = channels.find((c) => c.status === "open");
        if (!open?.channel_id) {
          console.log("[action] No open channel. Run step4a first (do not run step4b — 0.5.x blocks transfer if any channel has non-zero balance).\n");
          setTimeout(() => ws.close(1000), 2000);
          return;
        }
        // 0.5.x: Transfer is from unified balance; blocked if any channel has non-zero amount. So use step4a only (channel with 0), not step4b.
        console.log("[action] Open channel:", open.channel_id, "- sending off-chain transfer (from unified balance)...\n");
        const transferMsg = await createTransferMessage(
          sessionSigner,
          {
            destination: workerAddress,
            allocations: [{ asset: "ytest.usd", amount: TRANSFER_AMOUNT }],
          },
          Date.now()
        );
        ws.send(transferMsg);
        return;
      }

      if (method === "transfer") {
        console.log("[action] Off-chain transfer succeeded.\n");
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
