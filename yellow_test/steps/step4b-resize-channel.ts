/**
 * Step 4b: Resize (fund) the channel from Unified Balance. No transfer.
 * Assumes an open channel exists (run step4a first if not). When server sends
 * "channels" with an open channel we send resize; when server responds with
 * resize_channel we submit the on-chain tx and log success.
 *
 * The custody contract requires proofStates.length > 0: proofs[0] is the
 * preceding on-chain state (candidate.version must equal preceding.version + 1).
 * We fetch it via getChannelData(channelId).lastValidState.
 * 
 * This has worked after step4a was run and a channel already existed. not been tested when channel is newly formed in 4a
 * *****SKIP THIS STEP IF GOING TO RUN STEP 4C cos it breaks it!! something about not allowing funded.
 *
 * Run: npm run step4b
 * Prereq: .env with PRIVATE_KEY; step4a already run (channel exists); Sepolia ETH for gas.
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
  createResizeChannelMessage,
} from "@erc7824/nitrolite";

const SANDBOX_WS = "wss://clearnet-sandbox.yellow.com/ws";
const CUSTODY = "0x019B65A265EB3363822f2752141b3dF16131b262" as const;
const ADJUDICATOR = "0x7c7ccbc98469190849BCC6c926307794fDfB11F2" as const;
const RESIZE_AMOUNT = 5n; // fund channel with 5 ytest.usd (match typical sandbox balance)

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

  console.log("Step 4b: Auth + resize (fund) channel from Unified Balance (no transfer)\n");
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
          console.log("[action] No open channel. Run step4a first.\n");
          setTimeout(() => ws.close(1000), 2000);
          return;
        }
        console.log("[action] Open channel:", open.channel_id, "- sending resize...\n");
        const resizeMsg = await createResizeChannelMessage(sessionSigner, {
          channel_id: open.channel_id as `0x${string}`,
          allocate_amount: RESIZE_AMOUNT,
          funds_destination: account.address,
        });
        ws.send(resizeMsg);
        return;
      }

      if (method === "resize_channel" && payload) {
        const { channel_id, state, server_signature } = payload as {
          channel_id: string;
          state: { intent: unknown; version: unknown; state_data?: unknown; data?: unknown; allocations: { destination: string; token: string; amount: string }[] };
          server_signature: unknown;
        };
        // Contract requires proofs.length > 0: proofs[0] is the preceding state (candidate.version must equal preceding.version + 1)
        const channelIdHex = channel_id as `0x${string}`;
        const channelData = await nitroliteClient.getChannelData(channelIdHex);
        const precedingState = channelData.lastValidState;
        if (!precedingState?.sigs?.length) {
          console.error("[action] No lastValidState on chain for this channel; cannot prove resize.");
          throw new Error("Missing preceding state for resize");
        }
        // Normalize data to Hex: contract expects 0x-prefixed string
        const rawData = state.state_data ?? state.data;
        const dataHex =
          typeof rawData === "string"
            ? rawData.startsWith("0x")
              ? (rawData as `0x${string}`)
              : (`0x${rawData}` as `0x${string}`)
            : ("0x" as `0x${string}`);
        const resizeState = {
          intent: typeof state.intent === "number" ? state.intent : parseInt(String(state.intent), 10),
          version: BigInt(state.version as number),
          data: dataHex,
          allocations: state.allocations.map((a) => ({
            destination: getAddress(a.destination),
            token: getAddress(a.token),
            amount: BigInt(a.amount),
          })),
          channelId: channelIdHex,
          serverSignature: server_signature as `0x${string}`,
        };
        try {
          const { txHash } = await nitroliteClient.resizeChannel({
            resizeState,
            proofStates: [precedingState],
          });
          console.log("[action] Channel resized on-chain:", txHash);
          await publicClient.waitForTransactionReceipt({ hash: txHash as `0x${string}` });
          console.log("[action] Channel funded. Done (no transfer).\n");
          setTimeout(() => ws.close(1000), 2000);
        } catch (resizeErr: unknown) {
          const err = resizeErr as Error & { cause?: Error & { message?: string; shortMessage?: string } };
          const causeMsg = err.cause?.shortMessage ?? err.cause?.message ?? err.cause;
          console.error("[action] resizeChannel failed:", err.message);
          if (causeMsg) console.error("[action] cause:", causeMsg);
          throw resizeErr;
        }
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
      const err = e as Error & { cause?: unknown };
      console.log("[message] (parse error):", err.message);
      if (err.cause) console.log("[message] cause:", err.cause);
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
