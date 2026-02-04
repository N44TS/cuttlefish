/**
 * Step 5e: One bilateral state with non-zero allocations (client pays worker).
 * Same two-party flow as 5d but we use an existing quorum-2 session and submit
 * one state with client: 0, worker: 1 ytest.usd. Both must sign (quorum 2).
 *
 * Run: npm run step5e
 * Prereq: .env with PRIVATE_KEY, WORKER_ADDRESS, WORKER_PRIVATE_KEY. Run step5d first to have a quorum-2 session.
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
  RPCAppStateIntent,
} from "@erc7824/nitrolite";

const SANDBOX_WS = "wss://clearnet-sandbox.yellow.com/ws";
const APPLICATION_NAME = "agentpay.steps.escrow";
// 1 ytest.usd (6 decimals)
const PAY_AMOUNT = "1000000";

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

async function getQuorum2Session(
  ws: WebSocket,
  sessionSigner: ReturnType<typeof createECDSAMessageSigner>,
  participantAddress: `0x${string}`
): Promise<{ appSessionId: `0x${string}`; version: number }> {
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
          const session = open.find((s) => (s.quorum as number) === 2) ?? open[0];
          if (!session) {
            reject(new Error("No open app session (run step5d first to create a quorum-2 session)."));
            return;
          }
          resolve({
            appSessionId: (session.appSessionId ?? session.app_session_id) as `0x${string}`,
            version: (session.version as number) ?? 1,
          });
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

function submitAppStateAndWait(
  ws: WebSocket,
  sessionSigner: ReturnType<typeof createECDSAMessageSigner>,
  appSessionId: `0x${string}`,
  version: number,
  clientAddress: `0x${string}`,
  workerAddress: `0x${string}`,
  payAmount: string,
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
      { asset: "ytest.usd", amount: payAmount, participant: workerAddress },
    ];
    timeoutRef = setTimeout(() => {
      ws.off("message", handlerRef);
      reject(new Error("Timeout (20s) waiting for submit_app_state or asu"));
    }, 20000);
    const done = (msg: string) => {
      clearTimeout(timeoutRef);
      ws.off("message", handlerRef);
      console.log("[action] " + label + " " + msg);
      resolve();
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
        const res = parsed && typeof parsed === "object" && "res" in parsed ? (parsed as { res?: unknown[] }).res : undefined;
        const req = parsed && typeof parsed === "object" && "req" in parsed ? (parsed as { req?: unknown[] }).req : undefined;
        const method = (Array.isArray(res) && res.length >= 2 ? String(res[1]) : Array.isArray(req) && req.length >= 2 ? String(req[1]) : "") as string;
        const payload = (Array.isArray(res) && res.length >= 3 ? res[2] : Array.isArray(req) && req.length >= 3 ? req[2] : undefined) as Record<string, unknown> | undefined;
        if (method === "submit_app_state" && payload) {
          done("submit_app_state accepted. version: " + (payload.version ?? "") + " (client paid worker " + payAmount + " units).");
          return;
        }
        if (method === "asu") {
          done("app session updated (asu).");
          return;
        }
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
          console.log("[step5e] " + label + " unhandled method: " + method);
        }
      } catch {
        // ignore
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
    console.log("[action] " + label + " resolved by other party.");
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
    throw new Error("WORKER_ADDRESS must match WORKER_PRIVATE_KEY");
  }

  const rpcUrl = process.env.ALCHEMY_RPC_URL ?? process.env.SEPOLIA_RPC_URL ?? "https://1rpc.io/sepolia";
  const clientWallet = createWalletClient({ chain: sepolia, transport: http(rpcUrl), account: clientAccount });
  const workerWallet = createWalletClient({ chain: sepolia, transport: http(rpcUrl), account: workerAccount });
  if (!clientWallet || !workerWallet) throw new Error("Wallet client failed");

  const payAmount = process.env.PAY_AMOUNT ?? PAY_AMOUNT;

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

  console.log("Step 5e: Escrow state — client pays worker (both sign same state)\n");
  console.log("Client:", clientAccount.address);
  console.log("Worker:", workerAccount.address);
  console.log("Amount to worker:", payAmount, "ytest.usd (6 decimals)\n");

  const wsClient = new WebSocket(SANDBOX_WS);
  await new Promise<void>((resolve, reject) => {
    wsClient.on("open", () => { wsClient.send(clientAuthMsg); resolve(); });
    wsClient.on("error", reject);
  });
  await connectAndAuth(wsClient, clientKey, clientAuthMsg, clientWallet, clientAuthParams);
  console.log("[client] Authenticated.\n");

  const clientSession = await getQuorum2Session(wsClient, clientSessionSigner, clientAccount.address as `0x${string}`);
  console.log("[client] Found quorum-2 session:", clientSession.appSessionId, "version:", clientSession.version, "\n");

  const wsWorker = new WebSocket(SANDBOX_WS);
  await new Promise<void>((resolve, reject) => {
    wsWorker.on("open", () => { wsWorker.send(workerAuthMsg); resolve(); });
    wsWorker.on("error", reject);
  });
  await connectAndAuth(wsWorker, workerKey, workerAuthMsg, workerWallet, workerAuthParams);
  console.log("[worker] Authenticated.\n");

  const workerSession = await getQuorum2Session(wsWorker, workerSessionSigner, workerAddress);
  if (workerSession.appSessionId !== clientSession.appSessionId) {
    throw new Error("Worker did not see the same session");
  }
  console.log("[worker] Found same session.\n");

  console.log("[action] Client and worker each submitting same state (client pays worker " + payAmount + ")...\n");
  const clientResult = submitAppStateAndWait(
    wsClient,
    clientSessionSigner,
    clientSession.appSessionId,
    clientSession.version,
    clientAccount.address as `0x${string}`,
    workerAddress,
    payAmount,
    "Client"
  );
  const workerResult = submitAppStateAndWait(
    wsWorker,
    workerSessionSigner,
    workerSession.appSessionId,
    workerSession.version,
    clientAccount.address as `0x${string}`,
    workerAddress,
    payAmount,
    "Worker"
  );
  // When one party gets a response, resolve the other (same as step5d)
  clientResult.promise.then(() => workerResult.resolveNow()).catch(() => {});
  workerResult.promise.then(() => clientResult.resolveNow()).catch(() => {});

  await Promise.all([clientResult.promise, workerResult.promise]);
  console.log("\n[action] Escrow state done (client paid worker; both signed).\n");
  wsClient.close(1000);
  wsWorker.close(1000);
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
