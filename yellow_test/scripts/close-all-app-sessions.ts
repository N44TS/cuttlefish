/**
 * Close all open app sessions (two-party). Required for quorum-2 sessions:
 * both client and worker connect and both sign close_app_session for each session.
 *
 * Run: npm run close-all-app-sessions
 * Prereq: .env with PRIVATE_KEY, WORKER_ADDRESS, WORKER_PRIVATE_KEY.
 *
 * Note: If the sandbox responds with "quorum not reached" and never sends
 * close_app_session/asu, the script will time out. In that case the Yellow
 * sandbox may not yet send a success response for two-party close; check
 * Yellow docs or try with a single quorum-1 session (step5a then step5f).
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
  createCloseAppSessionMessage,
  createECDSAMessageSigner,
} from "@erc7824/nitrolite";

const SANDBOX_WS = "wss://clearnet-sandbox.yellow.com/ws";
const APPLICATION_NAME = "agentpay.steps.escrow";

function getEnv(name: string): string {
  const v = process.env[name];
  if (!v) throw new Error("Missing env: " + name + ". Set PRIVATE_KEY, WORKER_ADDRESS, WORKER_PRIVATE_KEY.");
  return v;
}

async function connectAndAuth(
  ws: WebSocket,
  privateKey: `0x${string}`,
  authRequestMsg: string,
  walletClient: ReturnType<typeof createWalletClient>,
  authParams: { session_key: `0x${string}`; allowances: { asset: string; amount: string }[]; expires_at: bigint; scope: string }
): Promise<void> {
  return new Promise((resolve, reject) => {
    const handler = async (data: WebSocket.Data) => {
      const raw = data.toString();
      try {
        const parsed = JSON.parse(raw) as { res?: unknown[]; error?: { message?: string } };
        if (parsed.error) {
          reject(new Error(String(parsed.error.message ?? parsed.error)));
          return;
        }
        const res = parsed.res as unknown[] | undefined;
        const method = res?.[1] as string | undefined;
        const payload = res?.[2] as Record<string, unknown> | undefined;
        if (method === "auth_challenge") {
          const challenge = (payload?.challenge_message as string) ?? "";
          const signer = createEIP712AuthMessageSigner(walletClient, authParams, { name: APPLICATION_NAME });
          ws.send(await createAuthVerifyMessageFromChallenge(signer, challenge));
          return;
        }
        if (method === "auth_verify") {
          ws.off("message", handler);
          resolve();
        }
      } catch (e) {
        ws.off("message", handler);
        reject(e as Error);
      }
    };
    ws.on("message", handler);
  });
}

async function getOpenAppSessionIds(
  ws: WebSocket,
  sessionSigner: ReturnType<typeof createECDSAMessageSigner>,
  participantAddress: `0x${string}`
): Promise<`0x${string}`[]> {
  return new Promise((resolve, reject) => {
    const handler = (data: WebSocket.Data) => {
      const raw = data.toString();
      try {
        const parsed = JSON.parse(raw) as { res?: unknown[]; error?: { message?: string } };
        if (parsed.error) {
          reject(new Error(String(parsed.error.message ?? parsed.error)));
          return;
        }
        const res = parsed.res as unknown[] | undefined;
        const method = res?.[1] as string | undefined;
        const payload = res?.[2] as Record<string, unknown> | undefined;
        if (method === "get_app_sessions" && payload) {
          ws.off("message", handler);
          const sessions = (payload.appSessions ?? payload.app_sessions) as Record<string, unknown>[] | undefined;
          const open = sessions?.filter((s) => (s.status as string) === "open") ?? [];
          const ids = open.map((s) => (s.appSessionId ?? s.app_session_id) as `0x${string}`);
          resolve(ids);
        }
      } catch (e) {
        ws.off("message", handler);
        reject(e as Error);
      }
    };
    ws.on("message", handler);
    createGetAppSessionsMessage(sessionSigner, participantAddress).then((msg) => ws.send(msg)).catch(reject);
  });
}

function closeOneSessionAndWait(
  wsClient: WebSocket,
  wsWorker: WebSocket,
  clientSigner: ReturnType<typeof createECDSAMessageSigner>,
  workerSigner: ReturnType<typeof createECDSAMessageSigner>,
  appSessionId: `0x${string}`,
  clientAddress: `0x${string}`,
  workerAddress: `0x${string}`
): Promise<void> {
  let resolveClient: () => void;
  let resolveWorker: () => void;
  let handlerClient: (data: WebSocket.Data) => void;
  let handlerWorker: (data: WebSocket.Data) => void;
  const timeoutMs = 30000;

  const promiseClient = new Promise<void>((resolve, reject) => {
    resolveClient = resolve;
    const t = setTimeout(() => {
      wsClient.off("message", handlerClient);
      reject(new Error("Timeout waiting for close_app_session (client)"));
    }, timeoutMs);
    const done = () => {
      clearTimeout(t);
      wsClient.off("message", handlerClient);
      resolve();
    };
    handlerClient = (data: WebSocket.Data) => {
      const raw = data.toString();
      try {
        const parsed = JSON.parse(raw) as unknown;
        const res = parsed && typeof parsed === "object" && "res" in parsed ? (parsed as { res?: unknown[] }).res : undefined;
        const payload = Array.isArray(res) && res.length >= 3 ? res[2] : undefined;
        const method = Array.isArray(res) && res.length >= 2 ? String(res[1]) : "";
        if (method === "close_app_session" || method === "closeAppSession" || method === "asu") { done(); return; }
        if (method === "error" && payload && typeof payload === "object") {
          const msg = String((payload as { error?: string }).error ?? (payload as { message?: string }).message ?? payload);
          if (msg.includes("quorum not reached")) return;
        }
        const err = parsed && typeof parsed === "object" && "error" in parsed ? (parsed as { error?: { message?: string } }).error : undefined;
        if (err) {
          const msg = String((err as { message?: string }).message ?? err);
          if (msg.includes("quorum not reached")) return;
          clearTimeout(t);
          wsClient.off("message", handlerClient);
          reject(new Error(msg));
        }
      } catch {
        // ignore
      }
    };
    wsClient.on("message", handlerClient);
  });

  const promiseWorker = new Promise<void>((resolve, reject) => {
    resolveWorker = resolve;
    const t = setTimeout(() => {
      wsWorker.off("message", handlerWorker);
      reject(new Error("Timeout waiting for close_app_session (worker)"));
    }, timeoutMs);
    const done = () => {
      clearTimeout(t);
      wsWorker.off("message", handlerWorker);
      resolve();
    };
    handlerWorker = (data: WebSocket.Data) => {
      const raw = data.toString();
      try {
        const parsed = JSON.parse(raw) as unknown;
        const res = parsed && typeof parsed === "object" && "res" in parsed ? (parsed as { res?: unknown[] }).res : undefined;
        const payload = Array.isArray(res) && res.length >= 3 ? res[2] : undefined;
        const method = Array.isArray(res) && res.length >= 2 ? String(res[1]) : "";
        if (method === "close_app_session" || method === "closeAppSession" || method === "asu") { done(); return; }
        if (method === "error" && payload && typeof payload === "object") {
          const msg = String((payload as { error?: string }).error ?? (payload as { message?: string }).message ?? payload);
          if (msg.includes("quorum not reached")) return;
        }
        const err = parsed && typeof parsed === "object" && "error" in parsed ? (parsed as { error?: { message?: string } }).error : undefined;
        if (err) {
          const msg = String((err as { message?: string }).message ?? err);
          if (msg.includes("quorum not reached")) return;
          clearTimeout(t);
          wsWorker.off("message", handlerWorker);
          reject(new Error(msg));
        }
      } catch {
        // ignore
      }
    };
    wsWorker.on("message", handlerWorker);
  });

  const allocations = [
    { asset: "ytest.usd", amount: "0", participant: clientAddress },
    { asset: "ytest.usd", amount: "0", participant: workerAddress },
  ];
  const closePayload = { app_session_id: appSessionId, allocations };
  (async () => {
    const clientMsg = await createCloseAppSessionMessage(clientSigner, closePayload, undefined, undefined);
    wsClient.send(clientMsg);
    await new Promise((r) => setTimeout(r, 300));
    const workerMsg = await createCloseAppSessionMessage(workerSigner, closePayload, undefined, undefined);
    wsWorker.send(workerMsg);
  })().catch(() => {});

  promiseClient.then(() => resolveWorker()).catch(() => {});
  promiseWorker.then(() => resolveClient()).catch(() => {});

  return Promise.all([promiseClient, promiseWorker]).then(() => {});
}

async function main() {
  const clientKeyRaw = getEnv("PRIVATE_KEY");
  const clientKey = clientKeyRaw.startsWith("0x") ? (clientKeyRaw as `0x${string}`) : ("0x" + clientKeyRaw as `0x${string}`);
  const workerKeyRaw = getEnv("WORKER_PRIVATE_KEY");
  const workerKey = workerKeyRaw.startsWith("0x") ? (workerKeyRaw as `0x${string}`) : ("0x" + workerKeyRaw as `0x${string}`);
  const workerAddressRaw = getEnv("WORKER_ADDRESS");
  const workerAddress = workerAddressRaw.startsWith("0x") ? (workerAddressRaw as `0x${string}`) : ("0x" + workerAddressRaw as `0x${string}`);

  const clientAccount = privateKeyToAccount(clientKey);
  const workerAccount = privateKeyToAccount(workerKey);
  if (workerAccount.address.toLowerCase() !== workerAddress.toLowerCase()) {
    throw new Error("WORKER_ADDRESS must match WORKER_PRIVATE_KEY");
  }

  const rpcUrl = process.env.ALCHEMY_RPC_URL ?? process.env.SEPOLIA_RPC_URL ?? "https://1rpc.io/sepolia";
  const clientWallet = createWalletClient({ chain: sepolia, transport: http(rpcUrl), account: clientAccount });
  const workerWallet = createWalletClient({ chain: sepolia, transport: http(rpcUrl), account: workerAccount });
  if (!clientWallet || !workerWallet) throw new Error("Wallet client failed");

  const clientSessionKey = generatePrivateKey();
  const clientSessionAccount = privateKeyToAccount(clientSessionKey);
  const clientSessionSigner = createECDSAMessageSigner(clientSessionKey);
  const clientAuthParams = {
    session_key: clientSessionAccount.address as `0x${string}`,
    allowances: [{ asset: "ytest.usd", amount: "1000000000" }],
    expires_at: BigInt(Math.floor(Date.now() / 1000) + 3600),
    scope: "agentpay.steps",
  };
  const clientAuthMsg = await createAuthRequestMessage({
    address: clientAccount.address,
    application: APPLICATION_NAME,
    ...clientAuthParams,
  });

  const workerSessionKey = generatePrivateKey();
  const workerSessionAccount = privateKeyToAccount(workerSessionKey);
  const workerSessionSigner = createECDSAMessageSigner(workerSessionKey);
  const workerAuthParams = {
    session_key: workerSessionAccount.address as `0x${string}`,
    allowances: [{ asset: "ytest.usd", amount: "1000000000" }],
    expires_at: BigInt(Math.floor(Date.now() / 1000) + 3600),
    scope: "agentpay.steps",
  };
  const workerAuthMsg = await createAuthRequestMessage({
    address: workerAccount.address,
    application: APPLICATION_NAME,
    ...workerAuthParams,
  });

  console.log("Close all app sessions (two-party)\n");
  console.log("Client:", clientAccount.address);
  console.log("Worker:", workerAccount.address);
  console.log("");

  const wsClient = new WebSocket(SANDBOX_WS);
  await new Promise<void>((resolve, reject) => {
    wsClient.on("open", () => { wsClient.send(clientAuthMsg); resolve(); });
    wsClient.on("error", reject);
  });
  await connectAndAuth(wsClient, clientKey, clientAuthMsg, clientWallet, clientAuthParams);
  console.log("[client] Authenticated.");

  const wsWorker = new WebSocket(SANDBOX_WS);
  await new Promise<void>((resolve, reject) => {
    wsWorker.on("open", () => { wsWorker.send(workerAuthMsg); resolve(); });
    wsWorker.on("error", reject);
  });
  await connectAndAuth(wsWorker, workerKey, workerAuthMsg, workerWallet, workerAuthParams);
  console.log("[worker] Authenticated.\n");

  const openIds = await getOpenAppSessionIds(wsClient, clientSessionSigner, clientAccount.address as `0x${string}`);
  if (openIds.length === 0) {
    console.log("[action] No open app sessions.");
    wsClient.close(1000);
    wsWorker.close(1000);
    return;
  }

  console.log("[action] Found " + openIds.length + " open session(s). Closing each (both parties sign)...\n");

  for (let i = 0; i < openIds.length; i++) {
    const id = openIds[i];
    console.log("[action] Closing session " + (i + 1) + "/" + openIds.length + ": " + id.slice(0, 18) + "...");
    await closeOneSessionAndWait(
      wsClient,
      wsWorker,
      clientSessionSigner,
      workerSessionSigner,
      id,
      clientAccount.address as `0x${string}`,
      workerAddress
    );
    console.log("[action] Closed.");
  }

  console.log("\n[action] All " + openIds.length + " app session(s) closed.");
  wsClient.close(1000);
  wsWorker.close(1000);
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
