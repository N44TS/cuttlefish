/**
 * Step 5f: Close an app session (settle final state).
 * After auth we get_app_sessions, pick the first open session, close it.
 * - Quorum-1 sessions: single-party close (client only)
 * - Quorum-2 sessions: two-party close (client + worker both sign)
 *
 * Run: npm run step5f
 * Prereq: .env with PRIVATE_KEY and WORKER_ADDRESS. For quorum-2 sessions, also WORKER_PRIVATE_KEY.
 * At least one open app session (e.g. from step5a or 5d).
 *
 * Note: For quorum-2 sessions, if sandbox doesn't send success response after both parties
 * send close, we use a workaround: treat "both sent" as success after 2s wait.
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

function getEnv(name: string, required = true): string | undefined {
  const v = process.env[name];
  if (required && !v) throw new Error(`Missing env: ${name}. Set PRIVATE_KEY and WORKER_ADDRESS.`);
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

async function getOpenSession(
  ws: WebSocket,
  sessionSigner: ReturnType<typeof createECDSAMessageSigner>,
  participantAddress: `0x${string}`
): Promise<{ appSessionId: `0x${string}`; quorum: number; version: number }> {
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
          const session = open[0];
          if (!session) {
            reject(new Error("No open app session. Run step5a or 5d first."));
            return;
          }
          resolve({
            appSessionId: (session.appSessionId ?? session.app_session_id) as `0x${string}`,
            quorum: (session.quorum as number) ?? 1,
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

function closeSessionSingleParty(
  ws: WebSocket,
  sessionSigner: ReturnType<typeof createECDSAMessageSigner>,
  appSessionId: `0x${string}`,
  clientAddress: `0x${string}`,
  workerAddress: `0x${string}`
): Promise<void> {
  return new Promise((resolve, reject) => {
    const timeout = setTimeout(() => {
      ws.off("message", handler);
      reject(new Error("Timeout waiting for close_app_session"));
    }, 20000);
    const handler = (data: WebSocket.Data) => {
      const raw = data.toString();
      try {
        const parsed = JSON.parse(raw) as { res?: unknown[]; error?: { message?: string } };
        if (parsed.error) {
          const msg = String(parsed.error.message ?? parsed.error);
          clearTimeout(timeout);
          ws.off("message", handler);
          reject(new Error(msg));
          return;
        }
        const res = parsed.res as unknown[] | undefined;
        const method = res?.[1] as string | undefined;
        const payload = res?.[2] as Record<string, unknown> | undefined;
        if (method === "close_app_session" || method === "asu") {
          clearTimeout(timeout);
          ws.off("message", handler);
          resolve();
          return;
        }
      } catch {
        // ignore
      }
    };
    ws.on("message", handler);
    createCloseAppSessionMessage(
      sessionSigner,
      {
        app_session_id: appSessionId,
        allocations: [
          { asset: "ytest.usd", amount: "0", participant: clientAddress },
          { asset: "ytest.usd", amount: "0", participant: workerAddress },
        ],
      },
      undefined,
      undefined
    )
      .then((msg) => ws.send(msg))
      .catch((err) => {
        clearTimeout(timeout);
        ws.off("message", handler);
        reject(err);
      });
  });
}

async function verifySessionClosed(
  ws: WebSocket,
  sessionSigner: ReturnType<typeof createECDSAMessageSigner>,
  participantAddress: `0x${string}`,
  appSessionId: `0x${string}`
): Promise<boolean> {
  return new Promise((resolve) => {
    const timeout = setTimeout(() => {
      ws.off("message", handler);
      resolve(false);
    }, 5000);
    const handler = (data: WebSocket.Data) => {
      const raw = data.toString();
      try {
        const parsed = JSON.parse(raw) as { res?: unknown[]; error?: { message?: string } };
        if (parsed.error) {
          clearTimeout(timeout);
          ws.off("message", handler);
          resolve(false);
          return;
        }
        const res = parsed.res as unknown[] | undefined;
        const method = res?.[1] as string | undefined;
        const payload = res?.[2] as Record<string, unknown> | undefined;
        if (method === "get_app_sessions" && payload) {
          clearTimeout(timeout);
          ws.off("message", handler);
          const sessions = (payload.appSessions ?? payload.app_sessions) as Record<string, unknown>[] | undefined;
          const session = sessions?.find(
            (s) => ((s.appSessionId ?? s.app_session_id) as string).toLowerCase() === appSessionId.toLowerCase()
          );
          const isClosed = session ? (session.status as string) === "closed" : false;
          resolve(isClosed);
        }
      } catch {
        // ignore
      }
    };
    ws.on("message", handler);
    createGetAppSessionsMessage(sessionSigner, participantAddress).then((msg) => ws.send(msg)).catch(() => {
      clearTimeout(timeout);
      ws.off("message", handler);
      resolve(false);
    });
  });
}

function closeSessionTwoParty(
  wsClient: WebSocket,
  wsWorker: WebSocket,
  clientSigner: ReturnType<typeof createECDSAMessageSigner>,
  workerSigner: ReturnType<typeof createECDSAMessageSigner>,
  appSessionId: `0x${string}`,
  clientAddress: `0x${string}`,
  workerAddress: `0x${string}`
): Promise<boolean> {
  let clientSent = false;
  let workerSent = false;
  let clientResolved = false;
  let workerResolved = false;
  let serverConfirmed = false;

  const resolveClient = () => {
    if (!clientResolved) {
      clientResolved = true;
      wsClient.off("message", handlerClient);
    }
  };
  const resolveWorker = () => {
    if (!workerResolved) {
      workerResolved = true;
      wsWorker.off("message", handlerWorker);
    }
  };

  const handlerClient = (data: WebSocket.Data) => {
    const raw = data.toString();
    try {
      const parsed = JSON.parse(raw) as unknown;
      const res = parsed && typeof parsed === "object" && "res" in parsed ? (parsed as { res?: unknown[] }).res : undefined;
      const method = Array.isArray(res) && res.length >= 2 ? String(res[1]) : "";
      const payload = Array.isArray(res) && res.length >= 3 ? res[2] : undefined;
      if (method === "close_app_session" || method === "asu") {
        serverConfirmed = true;
        resolveClient();
        resolveWorker();
        return;
      }
      if (method === "error" && payload && typeof payload === "object") {
        const msg = String((payload as { error?: string }).error ?? (payload as { message?: string }).message ?? payload);
        if (msg.includes("quorum not reached")) {
          // Expected when only one party has sent so far
          return;
        }
      }
    } catch {
      // ignore
    }
  };

  const handlerWorker = (data: WebSocket.Data) => {
    const raw = data.toString();
    try {
      const parsed = JSON.parse(raw) as unknown;
      const res = parsed && typeof parsed === "object" && "res" in parsed ? (parsed as { res?: unknown[] }).res : undefined;
      const method = Array.isArray(res) && res.length >= 2 ? String(res[1]) : "";
      const payload = Array.isArray(res) && res.length >= 3 ? res[2] : undefined;
      if (method === "close_app_session" || method === "asu") {
        serverConfirmed = true;
        resolveClient();
        resolveWorker();
        return;
      }
      if (method === "error" && payload && typeof payload === "object") {
        const msg = String((payload as { error?: string }).error ?? (payload as { message?: string }).message ?? payload);
        if (msg.includes("quorum not reached")) {
          // Expected when only one party has sent so far
          return;
        }
      }
    } catch {
      // ignore
    }
  };

  wsClient.on("message", handlerClient);
  wsWorker.on("message", handlerWorker);

  const allocations = [
    { asset: "ytest.usd", amount: "0", participant: clientAddress },
    { asset: "ytest.usd", amount: "0", participant: workerAddress },
  ];
  const closePayload = { app_session_id: appSessionId, allocations };

  return Promise.all([
    createCloseAppSessionMessage(clientSigner, closePayload, undefined, undefined).then((msg) => {
      wsClient.send(msg);
      clientSent = true;
    }),
    createCloseAppSessionMessage(workerSigner, closePayload, undefined, undefined).then((msg) => {
      wsWorker.send(msg);
      workerSent = true;
    }),
  ])
    .then(() => {
      // Wait for server response or timeout, then verify
      return new Promise<boolean>((resolve) => {
        let resolved = false;
        const doResolve = (value: boolean) => {
          if (!resolved) {
            resolved = true;
            resolveClient();
            resolveWorker();
            resolve(value);
          }
        };

        // Check periodically if server confirmed
        const checkInterval = setInterval(() => {
          if (serverConfirmed) {
            clearInterval(checkInterval);
            doResolve(true);
          }
        }, 100);

        // After 5 seconds, if no server response, verify session status
        setTimeout(async () => {
          clearInterval(checkInterval);
          if (!resolved) {
            if (clientSent && workerSent && !serverConfirmed) {
              console.log("[info] Both parties sent close; waiting 3s then verifying session status...");
              await new Promise((r) => setTimeout(r, 3000));
              const isClosed = await verifySessionClosed(wsClient, clientSigner, clientAddress, appSessionId);
              if (isClosed) {
                console.log("[success] Session verified as closed.");
                doResolve(true);
              } else {
                console.log("[warning] Session still shows as open. Sandbox may not support two-party close confirmation.");
                console.log("[warning] Both parties sent close, but session status unchanged. This may be a sandbox limitation.");
                doResolve(false);
              }
            } else {
              doResolve(serverConfirmed);
            }
          }
        }, 5000);
      });
    })
    .finally(() => {
      resolveClient();
      resolveWorker();
    });
}

async function main() {
  const rawKey = getEnv("PRIVATE_KEY")!;
  const privateKey = rawKey.startsWith("0x") ? (rawKey as `0x${string}`) : (`0x${rawKey}` as `0x${string}`);
  const workerAddressRaw = getEnv("WORKER_ADDRESS")!;
  const workerAddress = workerAddressRaw.startsWith("0x") ? (workerAddressRaw as `0x${string}`) : (`0x${workerAddressRaw}` as `0x${string}`);
  const workerKeyRaw = getEnv("WORKER_PRIVATE_KEY", false);

  const account = privateKeyToAccount(privateKey);
  const rpcUrl = process.env.ALCHEMY_RPC_URL ?? process.env.SEPOLIA_RPC_URL ?? "https://1rpc.io/sepolia";
  const walletClient = createWalletClient({
    chain: sepolia,
    transport: http(rpcUrl),
    account,
  });
  if (!walletClient) throw new Error("Wallet client failed");

  const sessionPrivateKey = generatePrivateKey();
  const sessionAccount = privateKeyToAccount(sessionPrivateKey);
  const sessionSigner = createECDSAMessageSigner(sessionPrivateKey);

  const authParams = {
    session_key: sessionAccount.address,
    allowances: [{ asset: "ytest.usd", amount: "1000000000" }],
    expires_at: BigInt(Math.floor(Date.now() / 1000) + 3600),
    scope: "agentpay.steps",
  };

  const authRequestMsg = await createAuthRequestMessage({
    address: account.address,
    application: APPLICATION_NAME,
    ...authParams,
  });

  console.log("Step 5f: Close app session\n");
  console.log("Endpoint:", SANDBOX_WS);
  console.log("Client:", account.address);
  console.log("Worker:", workerAddress);
  console.log("");

  const ws = new WebSocket(SANDBOX_WS);
  await new Promise<void>((resolve, reject) => {
    ws.on("open", () => {
      ws.send(authRequestMsg);
      resolve();
    });
    ws.on("error", reject);
  });

  await connectAndAuth(ws, privateKey, authRequestMsg, walletClient, authParams);
  console.log("[client] Authenticated.\n");

  const session = await getOpenSession(ws, sessionSigner, account.address as `0x${string}`);
  console.log("[action] Found open session:", session.appSessionId.slice(0, 18) + "...");
  console.log("[action] Quorum:", session.quorum, "Version:", session.version, "\n");

  if (session.quorum === 1) {
    console.log("[action] Quorum-1 session: closing single-party...\n");
    await closeSessionSingleParty(ws, sessionSigner, session.appSessionId, account.address as `0x${string}`, workerAddress);
    console.log("[action] App session closed.\n");
    ws.close(1000);
  } else if (session.quorum === 2) {
    if (!workerKeyRaw) {
      throw new Error("Quorum-2 session requires WORKER_PRIVATE_KEY in .env");
    }
    console.log("[action] Quorum-2 session: closing two-party (client + worker)...\n");

    const workerKey = workerKeyRaw.startsWith("0x") ? (workerKeyRaw as `0x${string}`) : (`0x${workerKeyRaw}` as `0x${string}`);
    const workerAccount = privateKeyToAccount(workerKey);
    if (workerAccount.address.toLowerCase() !== workerAddress.toLowerCase()) {
      throw new Error("WORKER_ADDRESS must match WORKER_PRIVATE_KEY");
    }

    const workerWallet = createWalletClient({ chain: sepolia, transport: http(rpcUrl), account: workerAccount });
    if (!workerWallet) throw new Error("Worker wallet client failed");

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

    const wsWorker = new WebSocket(SANDBOX_WS);
    await new Promise<void>((resolve, reject) => {
      wsWorker.on("open", () => {
        wsWorker.send(workerAuthMsg);
        resolve();
      });
      wsWorker.on("error", reject);
    });

    await connectAndAuth(wsWorker, workerKey, workerAuthMsg, workerWallet, workerAuthParams);
    console.log("[worker] Authenticated.\n");

    const closed = await closeSessionTwoParty(
      ws,
      wsWorker,
      sessionSigner,
      workerSessionSigner,
      session.appSessionId,
      account.address as `0x${string}`,
      workerAddress
    );
    if (closed) {
      console.log("[action] App session closed (both parties signed and verified).\n");
    } else {
      console.log("[action] Both parties sent close, but session may still be open.\n");
      console.log("[note] This appears to be a sandbox limitation. Run 'npm run step5b' to check session status.\n");
    }
    ws.close(1000);
    wsWorker.close(1000);
  } else {
    throw new Error(`Unsupported quorum: ${session.quorum}`);
  }
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
