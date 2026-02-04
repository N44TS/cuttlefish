/**
 * Python ↔ TypeScript Bridge for Yellow/Nitrolite operations.
 * 
 * Reads JSON from stdin, executes Yellow operations, writes JSON to stdout.
 * 
 * Usage from Python:
 *   result = subprocess.run(['tsx', 'bridge.ts'], input=json.dumps({...}), capture_output=True, text=True)
 *   response = json.loads(result.stdout)
 * 
 * Commands:
 *   - test: Simple ping/pong to verify bridge works
 *   - create_session: Create app session (client + worker)
 *   - submit_state: Submit escrow state update (client pays worker)
 *   - close_session: Close app session
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
  createCloseAppSessionMessage,
  createECDSAMessageSigner,
  RPCProtocolVersion,
  RPCAppStateIntent,
} from "@erc7824/nitrolite";

const SANDBOX_WS = "wss://clearnet-sandbox.yellow.com/ws";
const APPLICATION_NAME = "agentpay.steps.escrow";

interface BridgeRequest {
  command: string;
  [key: string]: unknown;
}

interface BridgeResponse {
  success: boolean;
  data?: unknown;
  error?: string;
}

/**
 * Simple test command to verify bridge works.
 */
function handleTest(): BridgeResponse {
  return {
    success: true,
    data: { message: "Bridge is working!" },
  };
}

/**
 * Helper: Connect and authenticate with Yellow sandbox.
 */
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

/**
 * Create an app session (client + worker).
 * Request: { command: "create_session", client_private_key: "0x...", worker_address: "0x...", quorum?: 1|2 }
 * Response: { success: true, data: { app_session_id: "0x...", version: 1 } }
 */
async function handleCreateSession(request: BridgeRequest): Promise<BridgeResponse> {
  const clientPrivateKeyRaw = request.client_private_key as string;
  const workerAddressRaw = request.worker_address as string;
  const quorum = (request.quorum as number) ?? 1; // Default to 1 for single-party operations

  if (!clientPrivateKeyRaw || !workerAddressRaw) {
    return {
      success: false,
      error: "Missing required fields: client_private_key, worker_address",
    };
  }

  const clientPrivateKey = clientPrivateKeyRaw.startsWith("0x") 
    ? (clientPrivateKeyRaw as `0x${string}`) 
    : (`0x${clientPrivateKeyRaw}` as `0x${string}`);
  const workerAddress = workerAddressRaw.startsWith("0x")
    ? (workerAddressRaw as `0x${string}`)
    : (`0x${workerAddressRaw}` as `0x${string}`);

  const account = privateKeyToAccount(clientPrivateKey);
  const sessionPrivateKey = generatePrivateKey();
  const sessionAccount = privateKeyToAccount(sessionPrivateKey);
  const sessionSigner = createECDSAMessageSigner(sessionPrivateKey);

  const rpcUrl = process.env.ALCHEMY_RPC_URL ?? process.env.SEPOLIA_RPC_URL ?? "https://1rpc.io/sepolia";
  const walletClient = createWalletClient({
    chain: sepolia,
    transport: http(rpcUrl),
    account,
  });
  if (!walletClient) {
    return {
      success: false,
      error: "Failed to create wallet client",
    };
  }

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

  const definition = {
    application: APPLICATION_NAME,
    protocol: RPCProtocolVersion.NitroRPC_0_4,
    participants: [account.address, workerAddress] as `0x${string}`[],
    weights: [1, 1],
    quorum: quorum,
    challenge: 3600,
    nonce: Math.floor(Date.now() / 1000),
  };

  const allocations = [
    { asset: "ytest.usd", amount: "0", participant: account.address as `0x${string}` },
    { asset: "ytest.usd", amount: "0", participant: workerAddress },
  ];

  return new Promise((resolve) => {
    const ws = new WebSocket(SANDBOX_WS);
    let resolved = false;

    const cleanup = () => {
      if (!resolved) {
        resolved = true;
        ws.removeAllListeners();
        ws.close(1000);
      }
    };

    const timeout = setTimeout(() => {
      cleanup();
      resolve({
        success: false,
        error: "Timeout waiting for session creation",
      });
    }, 30000);

    ws.on("open", () => {
      ws.send(authRequestMsg);
    });

    ws.on("error", (err) => {
      cleanup();
      clearTimeout(timeout);
      resolve({
        success: false,
        error: `WebSocket error: ${err.message}`,
      });
    });

    ws.on("message", async (data: WebSocket.Data) => {
      const raw = data.toString();
      try {
        const parsed = JSON.parse(raw) as { res?: unknown[]; error?: { message?: string } };
        if (parsed.error) {
          cleanup();
          clearTimeout(timeout);
          resolve({
            success: false,
            error: String(parsed.error.message ?? parsed.error),
          });
          return;
        }
        const res = parsed.res as unknown[] | undefined;
        const method = res?.[1] as string | undefined;
        const payload = res?.[2] as Record<string, unknown> | undefined;

        if (method === "auth_challenge") {
          const challenge = (payload?.challenge_message as string) ?? "";
          const signer = createEIP712AuthMessageSigner(walletClient, authParams, {
            name: APPLICATION_NAME,
          });
          ws.send(await createAuthVerifyMessageFromChallenge(signer, challenge));
          return;
        }

        if (method === "auth_verify") {
          const createAppMsg = await createAppSessionMessage(sessionSigner, {
            definition,
            allocations,
          });
          ws.send(createAppMsg);
          return;
        }

        if (method === "create_app_session" && payload) {
          cleanup();
          clearTimeout(timeout);
          const appSessionId = (payload.app_session_id ?? payload.appSessionId) as string;
          const version = (payload.version as number) ?? 1;
          resolve({
            success: true,
            data: {
              app_session_id: appSessionId,
              version: version,
            },
          });
          return;
        }
      } catch (e) {
        // Ignore parse errors, continue waiting
      }
    });
  });
}

/**
 * Get an existing app session by ID or find first open session.
 */
async function getAppSession(
  ws: WebSocket,
  sessionSigner: ReturnType<typeof createECDSAMessageSigner>,
  participantAddress: `0x${string}`,
  appSessionId?: string
): Promise<{ appSessionId: `0x${string}`; version: number; quorum: number }> {
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
          let session;
          if (appSessionId) {
            session = open.find(
              (s) =>
                ((s.appSessionId ?? s.app_session_id) as string).toLowerCase() === appSessionId.toLowerCase()
            );
          } else {
            session = open[0];
          }
          if (!session) {
            reject(new Error(`No open app session found${appSessionId ? ` with ID ${appSessionId}` : ""}`));
            return;
          }
          resolve({
            appSessionId: (session.appSessionId ?? session.app_session_id) as `0x${string}`,
            version: (session.version as number) ?? 1,
            quorum: (session.quorum as number) ?? 1,
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

/**
 * Submit app state update (escrow payment).
 * Request: { command: "submit_state", app_session_id: "0x...", client_private_key: "0x...", worker_address: "0x...", amount: "1000000", worker_private_key?: "0x..." }
 * Response: { success: true, data: { version: 2, state_proof: "..." } }
 * 
 * For quorum-1 sessions: only client needs to sign
 * For quorum-2 sessions: both client and worker must sign (requires worker_private_key)
 */
async function handleSubmitState(request: BridgeRequest): Promise<BridgeResponse> {
  const appSessionIdRaw = request.app_session_id as string;
  const clientPrivateKeyRaw = request.client_private_key as string;
  const workerAddressRaw = request.worker_address as string;
  const amountRaw = request.amount as string;
  const workerPrivateKeyRaw = request.worker_private_key as string | undefined;

  if (!appSessionIdRaw || !clientPrivateKeyRaw || !workerAddressRaw || !amountRaw) {
    return {
      success: false,
      error: "Missing required fields: app_session_id, client_private_key, worker_address, amount",
    };
  }

  const clientPrivateKey = clientPrivateKeyRaw.startsWith("0x")
    ? (clientPrivateKeyRaw as `0x${string}`)
    : (`0x${clientPrivateKeyRaw}` as `0x${string}`);
  const workerAddress = workerAddressRaw.startsWith("0x")
    ? (workerAddressRaw as `0x${string}`)
    : (`0x${workerAddressRaw}` as `0x${string}`);
  const appSessionId = appSessionIdRaw.startsWith("0x")
    ? (appSessionIdRaw as `0x${string}`)
    : (`0x${appSessionIdRaw}` as `0x${string}`);
  const payAmount = String(amountRaw); // Amount in ytest.usd units (6 decimals)

  const account = privateKeyToAccount(clientPrivateKey);
  const sessionPrivateKey = generatePrivateKey();
  const sessionAccount = privateKeyToAccount(sessionPrivateKey);
  const sessionSigner = createECDSAMessageSigner(sessionPrivateKey);

  const rpcUrl = process.env.ALCHEMY_RPC_URL ?? process.env.SEPOLIA_RPC_URL ?? "https://1rpc.io/sepolia";
  const walletClient = createWalletClient({
    chain: sepolia,
    transport: http(rpcUrl),
    account,
  });
  if (!walletClient) {
    return {
      success: false,
      error: "Failed to create wallet client",
    };
  }

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

  return new Promise((resolve) => {
    const ws = new WebSocket(SANDBOX_WS);
    let resolved = false;

    const cleanup = () => {
      if (!resolved) {
        resolved = true;
        ws.removeAllListeners();
        ws.close(1000);
      }
    };

    const timeout = setTimeout(() => {
      cleanup();
      resolve({
        success: false,
        error: "Timeout waiting for state submission",
      });
    }, 30000);

    ws.on("open", () => {
      ws.send(authRequestMsg);
    });

    ws.on("error", (err) => {
      cleanup();
      clearTimeout(timeout);
      resolve({
        success: false,
        error: `WebSocket error: ${err.message}`,
      });
    });

    let authenticated = false;
    let sessionInfo: { appSessionId: `0x${string}`; version: number; quorum: number } | null = null;
    let gotSessions = false;

    ws.on("message", async (data: WebSocket.Data) => {
      const raw = data.toString();
      try {
        const parsed = JSON.parse(raw) as { res?: unknown[]; error?: { message?: string } };
        if (parsed.error) {
          cleanup();
          clearTimeout(timeout);
          resolve({
            success: false,
            error: String(parsed.error.message ?? parsed.error),
          });
          return;
        }
        const res = parsed.res as unknown[] | undefined;
        const method = res?.[1] as string | undefined;
        const payload = res?.[2] as Record<string, unknown> | undefined;

        if (method === "auth_challenge") {
          const challenge = (payload?.challenge_message as string) ?? "";
          const signer = createEIP712AuthMessageSigner(walletClient, authParams, {
            name: APPLICATION_NAME,
          });
          ws.send(await createAuthVerifyMessageFromChallenge(signer, challenge));
          return;
        }

        if (method === "auth_verify") {
          authenticated = true;
          // Request sessions list
          const getSessionsMsg = await createGetAppSessionsMessage(sessionSigner, account.address as `0x${string}`);
          ws.send(getSessionsMsg);
          return;
        }

        if (method === "get_app_sessions" && payload && !gotSessions) {
          gotSessions = true;
          const sessions = (payload.appSessions ?? payload.app_sessions) as Record<string, unknown>[] | undefined;
          const open = sessions?.filter((s) => (s.status as string) === "open") ?? [];
          let session;
          if (appSessionId) {
            session = open.find(
              (s) =>
                ((s.appSessionId ?? s.app_session_id) as string).toLowerCase() === appSessionId.toLowerCase()
            );
          } else {
            session = open[0];
          }
          if (!session) {
            cleanup();
            clearTimeout(timeout);
            resolve({
              success: false,
              error: `No open app session found${appSessionId ? ` with ID ${appSessionId}` : ""}`,
            });
            return;
          }
          sessionInfo = {
            appSessionId: (session.appSessionId ?? session.app_session_id) as `0x${string}`,
            version: (session.version as number) ?? 1,
            quorum: (session.quorum as number) ?? 1,
          };
          // Now submit the state
          try {
            const allocations = [
              { asset: "ytest.usd", amount: "0", participant: account.address as `0x${string}` },
              { asset: "ytest.usd", amount: payAmount, participant: workerAddress },
            ];
            // Match step5c exactly: pass undefined for optional params
            const submitMsg = await createSubmitAppStateMessage(
              sessionSigner,
              {
                app_session_id: sessionInfo.appSessionId,
                intent: RPCAppStateIntent.Operate,
                version: sessionInfo.version + 1,
                allocations,
              },
              undefined,
              undefined
            );
            ws.send(submitMsg);
          } catch (e) {
            cleanup();
            clearTimeout(timeout);
            resolve({
              success: false,
              error: `Failed to create submit message: ${e instanceof Error ? e.message : String(e)}`,
            });
          }
          return;
        }

        if (method === "submit_app_state" && payload && sessionInfo) {
          cleanup();
          clearTimeout(timeout);
          const version = (payload.version as number) ?? sessionInfo.version + 1;
          resolve({
            success: true,
            data: {
              version: version,
              state_proof: `session:${sessionInfo.appSessionId}:version:${version}`,
            },
          });
          return;
        }

        if (method === "asu" && sessionInfo) {
          // App session update - also indicates success
          cleanup();
          clearTimeout(timeout);
          const version = sessionInfo.version + 1;
          resolve({
            success: true,
            data: {
              version: version,
              state_proof: `session:${sessionInfo.appSessionId}:version:${version}`,
            },
          });
          return;
        }

        // Handle "quorum not reached" for quorum-2 sessions (expected, means waiting for other party)
        if (method === "error" && payload && sessionInfo) {
          const msg = String(payload.error ?? payload.message ?? payload ?? "");
          if (msg.includes("quorum not reached")) {
            // For quorum-1, this shouldn't happen
            if (sessionInfo.quorum === 1) {
              cleanup();
              clearTimeout(timeout);
              resolve({
                success: false,
                error: `Unexpected quorum error for quorum-1 session: ${msg}`,
              });
            }
            // For quorum-2, continue waiting (worker should sign)
            return;
          }
        }
      } catch (e) {
        // Ignore parse errors, continue waiting
      }
    });
  });
}

/**
 * Close an app session.
 * Request: { command: "close_session", app_session_id: "0x...", client_private_key: "0x...", worker_address: "0x..." }
 * Response: { success: true, data: { closed: true } }
 * 
 * Currently supports quorum-1 sessions only (single-party close).
 */
async function handleCloseSession(request: BridgeRequest): Promise<BridgeResponse> {
  const appSessionIdRaw = request.app_session_id as string;
  const clientPrivateKeyRaw = request.client_private_key as string;
  const workerAddressRaw = request.worker_address as string;

  if (!appSessionIdRaw || !clientPrivateKeyRaw || !workerAddressRaw) {
    return {
      success: false,
      error: "Missing required fields: app_session_id, client_private_key, worker_address",
    };
  }

  const clientPrivateKey = clientPrivateKeyRaw.startsWith("0x")
    ? (clientPrivateKeyRaw as `0x${string}`)
    : (`0x${clientPrivateKeyRaw}` as `0x${string}`);
  const workerAddress = workerAddressRaw.startsWith("0x")
    ? (workerAddressRaw as `0x${string}`)
    : (`0x${workerAddressRaw}` as `0x${string}`);
  const appSessionId = appSessionIdRaw.startsWith("0x")
    ? (appSessionIdRaw as `0x${string}`)
    : (`0x${appSessionIdRaw}` as `0x${string}`);

  const account = privateKeyToAccount(clientPrivateKey);
  const sessionPrivateKey = generatePrivateKey();
  const sessionAccount = privateKeyToAccount(sessionPrivateKey);
  const sessionSigner = createECDSAMessageSigner(sessionPrivateKey);

  const rpcUrl = process.env.ALCHEMY_RPC_URL ?? process.env.SEPOLIA_RPC_URL ?? "https://1rpc.io/sepolia";
  const walletClient = createWalletClient({
    chain: sepolia,
    transport: http(rpcUrl),
    account,
  });
  if (!walletClient) {
    return {
      success: false,
      error: "Failed to create wallet client",
    };
  }

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

  return new Promise((resolve) => {
    const ws = new WebSocket(SANDBOX_WS);
    let resolved = false;

    const cleanup = () => {
      if (!resolved) {
        resolved = true;
        ws.removeAllListeners();
        ws.close(1000);
      }
    };

    const timeout = setTimeout(() => {
      cleanup();
      resolve({
        success: false,
        error: "Timeout waiting for session closure",
      });
    }, 30000);

    ws.on("open", () => {
      ws.send(authRequestMsg);
    });

    ws.on("error", (err) => {
      cleanup();
      clearTimeout(timeout);
      resolve({
        success: false,
        error: `WebSocket error: ${err.message}`,
      });
    });

    let authenticated = false;
    let gotSessions = false;

    ws.on("message", async (data: WebSocket.Data) => {
      const raw = data.toString();
      try {
        const parsed = JSON.parse(raw) as { res?: unknown[]; error?: { message?: string } };
        if (parsed.error) {
          cleanup();
          clearTimeout(timeout);
          resolve({
            success: false,
            error: String(parsed.error.message ?? parsed.error),
          });
          return;
        }
        const res = parsed.res as unknown[] | undefined;
        const method = res?.[1] as string | undefined;
        const payload = res?.[2] as Record<string, unknown> | undefined;

        if (method === "auth_challenge") {
          const challenge = (payload?.challenge_message as string) ?? "";
          const signer = createEIP712AuthMessageSigner(walletClient, authParams, {
            name: APPLICATION_NAME,
          });
          ws.send(await createAuthVerifyMessageFromChallenge(signer, challenge));
          return;
        }

        if (method === "auth_verify") {
          authenticated = true;
          // Request sessions list
          const getSessionsMsg = await createGetAppSessionsMessage(sessionSigner, account.address as `0x${string}`);
          ws.send(getSessionsMsg);
          return;
        }

        if (method === "get_app_sessions" && payload && !gotSessions) {
          gotSessions = true;
          const sessions = (payload.appSessions ?? payload.app_sessions) as Record<string, unknown>[] | undefined;
          const open = sessions?.filter((s) => (s.status as string) === "open") ?? [];
          const session = open.find(
            (s) =>
              ((s.appSessionId ?? s.app_session_id) as string).toLowerCase() === appSessionId.toLowerCase()
          );
          if (!session) {
            cleanup();
            clearTimeout(timeout);
            resolve({
              success: false,
              error: `No open app session found with ID ${appSessionId}`,
            });
            return;
          }
          const quorum = (session.quorum as number) ?? 1;
          if (quorum !== 1) {
            cleanup();
            clearTimeout(timeout);
            resolve({
              success: false,
              error: `Session has quorum ${quorum}; only quorum-1 sessions supported for single-party close`,
            });
            return;
          }
          // Close the session
          try {
            const closeMsg = await createCloseAppSessionMessage(
              sessionSigner,
              {
                app_session_id: appSessionId,
                allocations: [
                  { asset: "ytest.usd", amount: "0", participant: account.address as `0x${string}` },
                  { asset: "ytest.usd", amount: "0", participant: workerAddress },
                ],
              },
              undefined,
              undefined
            );
            ws.send(closeMsg);
          } catch (e) {
            cleanup();
            clearTimeout(timeout);
            resolve({
              success: false,
              error: `Failed to create close message: ${e instanceof Error ? e.message : String(e)}`,
            });
          }
          return;
        }

        if (method === "close_app_session" || method === "asu") {
          cleanup();
          clearTimeout(timeout);
          resolve({
            success: true,
            data: {
              closed: true,
            },
          });
          return;
        }
      } catch (e) {
        // Ignore parse errors, continue waiting
      }
    });
  });
}

/**
 * Main entry point: read JSON from stdin, execute command, write JSON to stdout.
 */
async function main() {
  try {
    // Read JSON from stdin
    let input = "";
    for await (const chunk of process.stdin) {
      input += chunk.toString();
    }

    if (!input.trim()) {
      const response: BridgeResponse = {
        success: false,
        error: "No input provided",
      };
      console.log(JSON.stringify(response));
      process.exit(1);
    }

    const request: BridgeRequest = JSON.parse(input);

    let response: BridgeResponse;

    switch (request.command) {
      case "test":
        response = handleTest();
        break;
      case "create_session":
        response = await handleCreateSession(request);
        break;
      case "submit_state":
        response = await handleSubmitState(request);
        break;
      case "close_session":
        response = await handleCloseSession(request);
        break;
      default:
        response = {
          success: false,
          error: `Unknown command: ${request.command}`,
        };
    }

    // Write JSON response to stdout
    console.log(JSON.stringify(response));
  } catch (error) {
    const response: BridgeResponse = {
      success: false,
      error: error instanceof Error ? error.message : String(error),
    };
    console.log(JSON.stringify(response));
    process.exit(1);
  }
}

main().catch((error) => {
  const response: BridgeResponse = {
    success: false,
    error: error instanceof Error ? error.message : String(error),
  };
  console.log(JSON.stringify(response));
  process.exit(1);
});
