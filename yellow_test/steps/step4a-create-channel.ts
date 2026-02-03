/**
 * Step 4a: Create channel only (on-chain). No resize, no transfer.
 * After auth, when server sends "channels" (empty), we send create_channel;
 * when server responds with create_channel we submit the on-chain tx and log success.
 *
 * Run: npm run step4a
 * Prereq: .env with PRIVATE_KEY; wallet needs a little Sepolia ETH for gas.
 */

import "dotenv/config";
import WebSocket from "ws";
import { createPublicClient, createWalletClient, http } from "viem";
import { sepolia } from "viem/chains";
import { privateKeyToAccount, generatePrivateKey } from "viem/accounts";
import {
  NitroliteClient,
  WalletStateSigner,
  createECDSAMessageSigner,
  createEIP712AuthMessageSigner,
  createAuthRequestMessage,
  createAuthVerifyMessageFromChallenge,
  createCreateChannelMessage,
} from "@erc7824/nitrolite";

const SANDBOX_WS = "wss://clearnet-sandbox.yellow.com/ws";
const CUSTODY = "0x019B65A265EB3363822f2752141b3dF16131b262" as const;
const ADJUDICATOR = "0x7c7ccbc98469190849BCC6c926307794fDfB11F2" as const;
const SEPOLIA_CHAIN_ID = 11155111;
// ytest.usd on Sepolia (from sandbox assets response)
const DEFAULT_TOKEN = "0xDB9F293e3898c9E5536A3be1b0C56c89d2b32DEb";

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
  const publicClient = createPublicClient({
    chain: sepolia,
    transport: http(rpcUrl),
  });
  const walletClient = createWalletClient({
    chain: sepolia,
    transport: http(rpcUrl),
    account,
  });
  if (!walletClient) throw new Error("Wallet client failed");

  const nitroliteClient = new NitroliteClient({
    publicClient,
    walletClient,
    stateSigner: new WalletStateSigner(walletClient),
    addresses: { custody: CUSTODY, adjudicator: ADJUDICATOR },
    chainId: sepolia.id,
    challengeDuration: 3600n,
  });

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

  console.log("Step 4a: Auth + create channel only (no resize, no transfer)\n");
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
        console.log("[action] Authenticated (waiting for channels)...\n");
        return;
      }

      if (method === "channels") {
        const channels = (payload?.channels as { status?: string; channel_id?: string }[]) ?? [];
        const open = channels.find((c) => c.status === "open");
        if (open) {
          console.log("[action] Channel already exists:", open.channel_id, "\n");
          setTimeout(() => ws.close(1000), 2000);
          return;
        }
        console.log("[action] No open channel, sending create_channel...\n");
        const createMsg = await createCreateChannelMessage(sessionSigner, {
          chain_id: SEPOLIA_CHAIN_ID,
          token: DEFAULT_TOKEN as `0x${string}`,
        });
        ws.send(createMsg);
        return;
      }

      if (method === "create_channel" && payload) {
        const { channel_id, channel, state, server_signature } = payload as {
          channel_id: string;
          channel: unknown;
          state: { intent: unknown; version: unknown; state_data?: unknown; allocations: { destination: string; token: string; amount: string }[] };
          server_signature: unknown;
        };
        const unsignedInitialState = {
          intent: state.intent,
          version: BigInt(state.version as number),
          data: state.state_data ?? (state as { data?: unknown }).data ?? "0x",
          allocations: state.allocations.map((a) => ({
            destination: a.destination,
            token: a.token,
            amount: BigInt(a.amount),
          })),
        };
        const createResult = await nitroliteClient.createChannel({
          channel,
          unsignedInitialState,
          serverSignature: server_signature,
        });
        const txHash = typeof createResult === "string" ? createResult : (createResult as { txHash: string }).txHash;
        console.log("[action] Channel created on-chain:", txHash);
        console.log("[action] Channel ID:", channel_id);
        await publicClient.waitForTransactionReceipt({ hash: txHash as `0x${string}` });
        console.log("[action] Tx confirmed. Done (no resize/transfer).\n");
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
    console.log("Closing after 90s (create channel may take a while)...\n");
    ws.close(1000);
  }, 90000);
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
