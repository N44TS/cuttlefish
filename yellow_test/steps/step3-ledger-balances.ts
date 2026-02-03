/**
 * Step 3: After auth, send "get ledger balances" and log the result.
 * No channels, no payments. Success = we see our ledger balances in the log.
 *
 * Run: npm run step3
 * Prereq: .env with PRIVATE_KEY
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
  createGetLedgerBalancesMessage,
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
    application: "AgentPay steps",
    ...authParams,
  });

  console.log("Step 3: Auth + get ledger balances (no channels or payments)\n");
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
          name: "AgentPay steps",
        });
        const verifyMsg = await createAuthVerifyMessageFromChallenge(signer, challenge);
        ws.send(verifyMsg);
        console.log("[action] Sent auth_verify\n");
        return;
      }

      if (method === "auth_verify") {
        console.log("[action] Authenticated, sending get_ledger_balances...\n");
        const ledgerMsg = await createGetLedgerBalancesMessage(
          sessionSigner,
          account.address,
          Date.now()
        );
        ws.send(ledgerMsg);
        return;
      }

      // Ledger response: server sends method "get_ledger_balances", payload.ledger_balances
      if (method === "get_ledger_balances" && payload) {
        const balances = (payload.ledger_balances as { asset: string; amount: string }[]) ?? [];
        console.log("[action] Ledger balances:");
        balances.forEach((b) => console.log(`  ${b.asset}: ${b.amount}`));
        console.log("");
        return;
      }

      // Other messages: log briefly (skip big assets dump)
      if (method !== "assets") {
        console.log("[message] raw length:", raw.length);
        console.log(JSON.stringify(parsed, null, 2));
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
    console.log("Closing after 10s...\n");
    ws.close(1000);
  }, 10000);
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
