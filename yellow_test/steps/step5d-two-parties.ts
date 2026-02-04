/**
 * Step 5d: Two parties (client + worker) both in the same app session; both sign the same state.
 * Client creates a new app session with quorum 2, then client and worker each send
 * submit_app_state with the same state (version 2, zero allocations). Server accepts when both have signed.
 *
 * Run: npm run step5d
 * Prereq: .env with PRIVATE_KEY (client), WORKER_ADDRESS, and WORKER_PRIVATE_KEY (worker's key).
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
  createGetAppSessionsMessage,
  createSubmitAppStateMessage,
  createECDSAMessageSigner,
  RPCProtocolVersion,
  RPCAppStateIntent,
} from "@erc7824/nitrolite";

const SANDBOX_WS = "wss://clearnet-sandbox.yellow.com/ws";
const APPLICATION_NAME = "agentpay.steps.escrow";

function getEnv(name: string): string {
  const v = process.env[name];
  if (!v) throw new Error(`Missing env: ${name}. Set PRIVATE_KEY, WORKER_ADDRESS, WORKER_PRIVATE_KEY.`);
  return v;
}

async function connectAndAuth(
  ws: WebSocket,
  privateKey: `0x${string}`,
  authRequestMsg: string,
  walletClient: ReturnType<typeof createWalletClient>,
  authParams: { session_key: string; allowances: { asset: string; amount: string }[]; expires_at: bigint; scope: string }
): Promise<void> {
  return new Promise((resolve, reject) => {
    const account = privateKeyToAccount(privateKey);
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
          const verifyMsg = await createAuthVerifyMessageFromChallenge(signer, challenge);
          ws.send(verifyMsg);
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

async function clientCreateSession(
  clientAddress: `0x${string}`,
  workerAddress: `0x${string}`,
  sessionSigner: ReturnType<typeof createECDSAMessageSigner>,
  ws: WebSocket
): Promise<{ appSessionId: `0x${string}`; version: number }> {
  return new Promise((resolve, reject) => {
    const definition = {
      application: APPLICATION_NAME,
      protocol: RPCProtocolVersion.NitroRPC_0_4,
      participants: [clientAddress, workerAddress] as `0x${string}`[],
      weights: [1, 1],
      quorum: 2,
      challenge: 3600,
      nonce: Math.floor(Date.now() / 1000),
    };
    const allocations = [
      { asset: "ytest.usd", amount: "0", participant: clientAddress },
      { asset: "ytest.usd", amount: "0", participant: workerAddress },
    ];
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
        if (method === "create_app_session" && payload) {
          ws.off("message", handler);
          const appSessionId = (payload.app_session_id ?? payload.appSessionId) as `0x${string}`;
          const version = (payload.version as number) ?? 1;
          resolve({ appSessionId, version });
        }
      } catch (e) {
        ws.off("message", handler);
        reject(e as Error);
      }
    };
    ws.on("message", handler);
    createAppSessionMessage(sessionSigner, { definition, allocations }).then((msg) => ws.send(msg)).catch(reject);
  });
}

async function getSessionForWorker(
  workerAddress: `0x${string}`,
  sessionSigner: ReturnType<typeof createECDSAMessageSigner>,
  ws: WebSocket,
  wantQuorum2: boolean
): Promise<{ appSessionId: `0x${string}`; version: number }> {
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
        if (method === "get_app_sessions" && payload) {
          ws.off("message", handler);
          const sessions = (payload.appSessions ?? payload.app_sessions) as Record<string, unknown>[] | undefined;
          const open = sessions?.filter((s) => (s.status as string) === "open") ?? [];
          const session = wantQuorum2 ? open.find((s) => (s.quorum as number) === 2) : open[0];
          if (!session) {
            reject(new Error("No app session found for worker (need quorum 2 session from step5d client)"));
            return;
          }
          const appSessionId = (session.appSessionId ?? session.app_session_id) as `0x${string}`;
          const version = (session.version as number) ?? 1;
          resolve({ appSessionId, version });
        }
      } catch (e) {
        ws.off("message", handler);
        reject(e as Error);
      }
    };
    ws.on("message", handler);
    createGetAppSessionsMessage(sessionSigner, workerAddress).then((msg) => ws.send(msg)).catch(reject);
  });
}

function submitAppStateAndWait(
  ws: WebSocket,
  sessionSigner: ReturnType<typeof createECDSAMessageSigner>,
  appSessionId: `0x${string}`,
  version: number,
  clientAddress: `0x${string}`,
  workerAddress: `0x${string}`,
  label: string
): { promise: Promise<void>; resolveNow: () => void } {
  let resolveRef: () => void;
  let timeoutRef: ReturnType<typeof setTimeout>;
  let handlerRef: (data: WebSocket.Data) => void;
  const promise = new Promise<void>((resolve, reject) => {
    resolveRef = resolve;
    const nextVersion = version + 1;
    const allocations = [
      { asset: "ytest.usd", amount: "0", participant: clientAddress },
      { asset: "ytest.usd", amount: "0", participant: workerAddress },
    ];
    timeoutRef = setTimeout(() => {
      ws.off("message", handlerRef);
      reject(new Error("Timeout (20s) waiting for submit_app_state or asu response"));
    }, 20000);
    const done = (msg: string) => {
      clearTimeout(timeoutRef);
      ws.off("message", handlerRef);
      console.log(`[action] ${label} ${msg}`);
      resolve();
    };
    const getMethodAndPayload = (parsed: unknown): { method?: string; payload?: Record<string, unknown> } => {
      if (parsed && typeof parsed === "object" && "res" in parsed) {
        const res = (parsed as { res?: unknown[] }).res;
        if (Array.isArray(res) && res.length >= 2)
          return { method: String(res[1]), payload: res[2] as Record<string, unknown> };
      }
      if (parsed && typeof parsed === "object" && "req" in parsed) {
        const req = (parsed as { req?: unknown[] }).req;
        if (Array.isArray(req) && req.length >= 2)
          return { method: String(req[1]), payload: req[2] as Record<string, unknown> };
      }
      if (Array.isArray(parsed) && parsed.length >= 2)
        return { method: String(parsed[1]), payload: parsed[2] as Record<string, unknown> };
      return {};
    };
    handlerRef = (data: WebSocket.Data) => {
      const raw = data.toString();
      try {
        const parsed = JSON.parse(raw) as unknown;
        const err = parsed && typeof parsed === "object" && "error" in parsed ? (parsed as { error?: { message?: string } }).error : undefined;
        const errMsg = err ? String((err as { message?: string }).message ?? err) : "";
        if (err) {
          if (errMsg.includes("quorum not reached")) {
            done("signed (quorum not reached yet, waiting for other party).");
            return;
          }
          clearTimeout(timeoutRef);
          ws.off("message", handlerRef);
          reject(new Error(errMsg));
          return;
        }
        const { method, payload } = getMethodAndPayload(parsed);
        if (method === "submit_app_state" && payload) {
          done("submit_app_state accepted. version: " + (payload.version ?? "") + " status: " + (payload.status ?? ""));
          return;
        }
        if (method === "asu") {
          done("app session updated (asu).");
          return;
        }
        // Server can send error as res: [ id, "error", { error: "..." } ] instead of top-level parsed.error
        if (method === "error" && payload) {
          const msg = String(payload.error ?? payload.message ?? payload ?? "");
          if (msg.includes("quorum not reached")) {
            done("signed (quorum not reached yet, waiting for other party).");
            return;
          }
          clearTimeout(timeoutRef);
          ws.off("message", handlerRef);
          reject(new Error(msg));
          return;
        }
        if (method && method !== "assets" && method !== "channels" && method !== "bu") {
          console.log(`[step5d] ${label} unhandled method: ${method} (raw ${raw.length} chars)`);
        }
      } catch {
        // ignore parse errors
      }
    };
    ws.on("message", handlerRef);
    createSubmitAppStateMessage(sessionSigner, {
      app_session_id: appSessionId,
      intent: RPCAppStateIntent.Operate,
      version: nextVersion,
      allocations,
    }).then((msg) => ws.send(msg)).catch((err) => {
      clearTimeout(timeoutRef);
      ws.off("message", handlerRef);
      reject(err);
    });
  });
  const resolveNow = () => {
    clearTimeout(timeoutRef);
    ws.off("message", handlerRef);
    console.log(`[action] ${label} resolved by other party.`);
    resolveRef();
  };
  return { promise, resolveNow };
}

async function main() {
  const clientKeyRaw = getEnv("PRIVATE_KEY");
  const clientKey = clientKeyRaw.startsWith("0x") ? (clientKeyRaw as `0x${string}`) : (`0x${clientKeyRaw}` as `0x${string}`);
  const workerKeyRaw = getEnv("WORKER_PRIVATE_KEY");
  const workerKey = workerKeyRaw.startsWith("0x") ? (workerKeyRaw as `0x${string}`) : (`0x${workerKeyRaw}` as `0x${string}`);
  const workerAddressRaw = getEnv("WORKER_ADDRESS");
  const workerAddress = workerAddressRaw.startsWith("0x") ? (workerAddressRaw as `0x${string}`) : (`0x${workerAddressRaw}` as `0x${string}`);

  const clientAccount = privateKeyToAccount(clientKey);
  const workerAccount = privateKeyToAccount(workerKey);
  if (workerAccount.address.toLowerCase() !== workerAddress.toLowerCase()) {
    throw new Error("WORKER_ADDRESS must match the address of WORKER_PRIVATE_KEY");
  }

  const rpcUrl = process.env.ALCHEMY_RPC_URL ?? process.env.SEPOLIA_RPC_URL ?? "https://1rpc.io/sepolia";
  const clientWallet = createWalletClient({ chain: sepolia, transport: http(rpcUrl), account: clientAccount });
  const workerWallet = createWalletClient({ chain: sepolia, transport: http(rpcUrl), account: workerAccount });
  if (!clientWallet || !workerWallet) throw new Error("Wallet client failed");

  const clientSessionKey = generatePrivateKey();
  const clientSessionAccount = privateKeyToAccount(clientSessionKey);
  const clientSessionSigner = createECDSAMessageSigner(clientSessionKey);
  const clientAuthParams = {
    session_key: clientSessionAccount.address,
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
    session_key: workerSessionAccount.address,
    allowances: [{ asset: "ytest.usd", amount: "1000000000" }],
    expires_at: BigInt(Math.floor(Date.now() / 1000) + 3600),
    scope: "agentpay.steps",
  };
  const workerAuthMsg = await createAuthRequestMessage({
    address: workerAccount.address,
    application: APPLICATION_NAME,
    ...workerAuthParams,
  });

  console.log("Step 5d: Two parties — client creates session (quorum 2), both sign same state\n");
  console.log("Client:", clientAccount.address);
  console.log("Worker:", workerAccount.address);
  console.log("");

  const wsClient = new WebSocket(SANDBOX_WS);
  await new Promise<void>((resolve, reject) => {
    wsClient.on("open", () => { wsClient.send(clientAuthMsg); resolve(); });
    wsClient.on("error", reject);
  });
  await connectAndAuth(wsClient, clientKey, clientAuthMsg, clientWallet, clientAuthParams);
  console.log("[client] Authenticated.\n");

  const { appSessionId, version } = await clientCreateSession(
    clientAccount.address as `0x${string}`,
    workerAddress,
    clientSessionSigner,
    wsClient
  );
  console.log("[client] App session created (quorum 2):", appSessionId, "version:", version, "\n");

  const wsWorker = new WebSocket(SANDBOX_WS);
  await new Promise<void>((resolve, reject) => {
    wsWorker.on("open", () => { wsWorker.send(workerAuthMsg); resolve(); });
    wsWorker.on("error", reject);
  });
  await connectAndAuth(wsWorker, workerKey, workerAuthMsg, workerWallet, workerAuthParams);
  console.log("[worker] Authenticated.\n");

  const workerSession = await getSessionForWorker(workerAddress, workerSessionSigner, wsWorker, true);
  if (workerSession.appSessionId !== appSessionId) {
    throw new Error("Worker did not see the same session; sessionId mismatch");
  }
  console.log("[worker] Found same session.\n");

  const nextVersion = version + 1;
  const allocations = [
    { asset: "ytest.usd", amount: "0", participant: clientAccount.address as `0x${string}` },
    { asset: "ytest.usd", amount: "0", participant: workerAddress },
  ];

  console.log("[action] Client and worker each submitting same state (version " + nextVersion + ")...\n");
  const clientResult = submitAppStateAndWait(
    wsClient,
    clientSessionSigner,
    appSessionId,
    version,
    clientAccount.address as `0x${string}`,
    workerAddress,
    "Client"
  );
  const workerResult = submitAppStateAndWait(
    wsWorker,
    workerSessionSigner,
    appSessionId,
    version,
    clientAccount.address as `0x${string}`,
    workerAddress,
    "Worker"
  );
  // When one party gets a response, resolve the other so we don't rely on both getting a message
  clientResult.promise.then(() => workerResult.resolveNow()).catch(() => {});
  workerResult.promise.then(() => clientResult.resolveNow()).catch(() => {});

  await Promise.all([clientResult.promise, workerResult.promise]);
  console.log("\n[action] Bilateral state update done (both parties signed).\n");
  wsClient.close(1000);
  wsWorker.close(1000);
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
