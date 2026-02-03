/**
 * Close all open Yellow sandbox channels for the wallet in .env.
 * Connects → auth → gets channels → for each open channel sends close_channel
 * (funds to self), submits on-chain close, then next. No resize, no transfer.
 *
 * Run: npm run close-all
 * Prereq: .env with PRIVATE_KEY; wallet needs Sepolia ETH for gas.
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
    application: "AgentPay close-all",
    ...authParams,
  });

  const openChannelIds: `0x${string}`[] = [];
  let currentIndex = 0;

  console.log("Close-all: connect and close every open channel for this wallet\n");
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
          name: "AgentPay close-all",
        });
        const verifyMsg = await createAuthVerifyMessageFromChallenge(signer, challenge);
        ws.send(verifyMsg);
        console.log("[action] Sent auth_verify\n");
        return;
      }

      if (method === "auth_verify") {
        console.log("[action] Authenticated. Fetching open channels from chain...\n");
        try {
          const fromChain = await nitroliteClient.getOpenChannels();
          openChannelIds.push(...fromChain);
        } catch (e) {
          console.error("[action] getOpenChannels failed:", (e as Error).message);
        }
        if (openChannelIds.length === 0) {
          console.log("[action] No open channels on chain. Nothing to close.\n");
          setTimeout(() => ws.close(1000), 2000);
          return;
        }
        console.log("[action] Open channels (from chain):", openChannelIds.length);
        openChannelIds.forEach((id, i) => console.log(`  ${i + 1}. ${id}`));
        console.log("\nClosing first channel...\n");
        const closeMsg = await createCloseChannelMessage(
          sessionSigner,
          openChannelIds[0],
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
        } catch (err) {
          console.error("[action] closeChannel failed for", channel_id, err);
          // Continue to next channel anyway
        }
        currentIndex++;
        if (currentIndex >= openChannelIds.length) {
          console.log("\n[action] All channels closed.\n");
          setTimeout(() => ws.close(1000), 2000);
          return;
        }
        console.log("\nClosing next channel...\n");
        const nextMsg = await createCloseChannelMessage(
          sessionSigner,
          openChannelIds[currentIndex],
          account.address
        );
        ws.send(nextMsg);
        return;
      }

      if (method === "error") {
        console.error("[message] Server error:", JSON.stringify(payload ?? res, null, 2));
        // If we're in the middle of closing and server rejected one, try next channel
        if (openChannelIds.length > 0 && currentIndex < openChannelIds.length) {
          currentIndex++;
          if (currentIndex < openChannelIds.length) {
            console.log("\nTrying next channel...\n");
            const nextMsg = await createCloseChannelMessage(
              sessionSigner,
              openChannelIds[currentIndex],
              account.address
            );
            ws.send(nextMsg);
          } else {
            console.log("\n[action] No more channels to try.\n");
            setTimeout(() => ws.close(1000), 2000);
          }
        }
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
    console.log("Closing after 120s...\n");
    ws.close(1000);
  }, 120000);
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
