/**
 * Step 4d: Close channel — on-chain settlement.
 * After auth, when server sends "channels" with an open channel we send close_channel
 * (funds to self); when server responds with "close_channel" we submit the on-chain
 * close tx and log success.
 *
 * Run: npm run step4d
 * Prereq: .env with PRIVATE_KEY; at least one open channel (e.g. after step4a or step4c).
 *         Wallet needs a little Sepolia ETH for gas.
 */

import "dotenv/config";
import WebSocket from "ws";
import { createPublicClient, createWalletClient, http, getAddress } from "viem";
import { sepolia } from "viem/chains";
import { privateKeyToAccount, generatePrivateKey } from "viem/accounts";
import {
  NitroliteClient,
  WalletStateSigner,
  createECDSAMessageSigner,
  createEIP712AuthMessageSigner,
  createAuthRequestMessage,
  createAuthVerifyMessageFromChallenge,
  createCloseChannelMessage,
} from "@erc7824/nitrolite";

const SANDBOX_WS = "wss://clearnet-sandbox.yellow.com/ws";
const CUSTODY = "0x019B65A265EB3363822f2752141b3dF16131b262" as const;
const ADJUDICATOR = "0x7c7ccbc98469190849BCC6c926307794fDfB11F2" as const;

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

  console.log("Step 4d: Auth + close channel (on-chain settlement)\n");
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
        if (!open?.channel_id) {
          console.log("[action] No open channel. Run step4a first (or step4c); then run step4d to close.\n");
          setTimeout(() => ws.close(1000), 2000);
          return;
        }
        console.log("[action] Open channel:", open.channel_id, "- sending close_channel (funds to self)...\n");
        const closeMsg = await createCloseChannelMessage(
          sessionSigner,
          open.channel_id as `0x${string}`,
          account.address
        );
        ws.send(closeMsg);
        return;
      }

      if (method === "close_channel" && payload) {
        const { channel_id, state, server_signature } = payload as {
          channel_id: string;
          state: { intent: unknown; version: unknown; state_data?: unknown; data?: unknown; allocations: { destination: string; token: string; amount: string }[] };
          server_signature: unknown;
        };
        const rawData = state.state_data ?? state.data;
        const dataHex =
          typeof rawData === "string"
            ? rawData.startsWith("0x")
              ? (rawData as `0x${string}`)
              : (`0x${rawData}` as `0x${string}`)
            : ("0x" as `0x${string}`);
        const finalState = {
          intent: typeof state.intent === "number" ? state.intent : parseInt(String(state.intent), 10),
          version: BigInt(state.version as number),
          data: dataHex,
          allocations: state.allocations.map((a) => ({
            destination: getAddress(a.destination),
            token: getAddress(a.token),
            amount: BigInt(a.amount),
          })),
          channelId: channel_id as `0x${string}`,
          serverSignature: server_signature as `0x${string}`,
        };
        try {
          const txHash = await nitroliteClient.closeChannel({
            finalState,
            stateData: dataHex,
          });
          console.log("[action] Channel closed on-chain:", channel_id, "tx:", txHash);
          await publicClient.waitForTransactionReceipt({ hash: txHash as `0x${string}` });
          console.log("[action] On-chain settlement done.\n");
        } catch (err) {
          console.error("[action] closeChannel failed:", (err as Error).message);
          throw err;
        }
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
    console.log("Closing after 90s...\n");
    ws.close(1000);
  }, 90000);
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
