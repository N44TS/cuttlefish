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
 *   - create_session: Create app session (client + worker). Use quorum: 2 for two-party escrow.
 *   - submit_state, sign_state_worker, close_session: App session escrow (steps 5a–5f).
 *   - pay_via_channel: Channel path (4a+4c+4d) — create channel if needed, transfer to worker, close channel. Returns close_tx_hash (on-chain, Sepolia Etherscan).
 */

import "dotenv/config";
import WebSocket from "ws";
import { createWalletClient, createPublicClient, http } from "viem";
import { sepolia } from "viem/chains";
import { privateKeyToAccount, generatePrivateKey } from "viem/accounts";
import { getAddress } from "viem";
import {
  createAuthRequestMessage,
  createAuthVerifyMessageFromChallenge,
  createEIP712AuthMessageSigner,
  createAppSessionMessage,
  createGetAppSessionsMessage,
  createGetLedgerBalancesMessage,
  createSubmitAppStateMessage,
  createCloseAppSessionMessage,
  createECDSAMessageSigner,
  createCreateChannelMessage,
  createTransferMessage,
  createCloseChannelMessage,
  NitroliteClient,
  WalletStateSigner,
  RPCProtocolVersion,
  RPCAppStateIntent,
} from "@erc7824/nitrolite";

const SANDBOX_WS = "wss://clearnet-sandbox.yellow.com/ws";
const APPLICATION_NAME = "agentpay.steps.escrow";
// Channel path uses same app/scope as steps/ (step4a–4d)
const CHANNEL_APP = "AgentPay steps";
const CUSTODY = "0x019B65A265EB3363822f2752141b3dF16131b262" as const;
const ADJUDICATOR = "0x7c7ccbc98469190849BCC6c926307794fDfB11F2" as const;
const SEPOLIA_CHAIN_ID = 11155111;
const DEFAULT_TOKEN = "0xDB9F293e3898c9E5536A3be1b0C56c89d2b32DEb" as `0x${string}`;

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
 * Steps 1–3: Connect → Auth → Get ledger balances.
 * Request: { command: "steps_1_to_3", client_private_key: "0x..." }
 * Response: { success: true, data: { ledger_balances: [ { asset, amount }, ... ] } }
 */
async function handleSteps1To3(request: BridgeRequest): Promise<BridgeResponse> {
  const clientPrivateKeyRaw = request.client_private_key as string;
  if (!clientPrivateKeyRaw) {
    return { success: false, error: "Missing client_private_key" };
  }
  const clientPrivateKey = clientPrivateKeyRaw.startsWith("0x")
    ? (clientPrivateKeyRaw as `0x${string}`)
    : (`0x${clientPrivateKeyRaw}` as `0x${string}`);
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
    return { success: false, error: "Failed to create wallet client" };
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
      resolve({ success: false, error: "Timeout waiting for ledger balances" });
    }, 20000);

    ws.on("open", () => ws.send(authRequestMsg));
    ws.on("error", (err) => {
      cleanup();
      clearTimeout(timeout);
      resolve({ success: false, error: `WebSocket error: ${err.message}` });
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
          const ledgerMsg = await createGetLedgerBalancesMessage(
            sessionSigner,
            account.address as `0x${string}`,
            undefined,
            Date.now()
          );
          ws.send(ledgerMsg);
          return;
        }
        if (method === "get_ledger_balances" && payload) {
          cleanup();
          clearTimeout(timeout);
          const balances = (payload.ledger_balances ?? payload.ledgerBalances) as { asset: string; amount: string }[] ?? [];
          resolve({
            success: true,
            data: { ledger_balances: balances },
          });
        }
      } catch {
        // ignore parse errors
      }
    });
  });
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
 *   quorum: 2 = two-party escrow (both must sign state); 1 = single-party (client only). Default 1.
 * Response: { success: true, data: { app_session_id: "0x...", version: 1 } }
 */
async function handleCreateSession(request: BridgeRequest): Promise<BridgeResponse> {
  const clientPrivateKeyRaw = request.client_private_key as string;
  const workerAddressRaw = request.worker_address as string;
  const quorum = (request.quorum as number) ?? 1; // 1 = single-party (tests), 2 = two-party escrow

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

        // Handle "quorum not reached" for quorum-2 sessions
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
              return;
            }
            // For quorum-2: client has signed. Return success so caller can ask worker to sign_state_worker with this version.
            const nextVersion = sessionInfo.version + 1;
            cleanup();
            clearTimeout(timeout);
            resolve({
              success: true,
              data: {
                version: nextVersion,
                state_proof: `session:${sessionInfo.appSessionId}:version:${nextVersion}:client_signed`,
              },
            });
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
 * Worker signs the same state as the client (second signature for quorum-2).
 * Call after client has called submit_state. Same app_session_id, version, and allocations.
 *
 * Request: {
 *   command: "sign_state_worker",
 *   app_session_id: "0x...",
 *   worker_private_key: "0x...",
 *   client_address: "0x...",
 *   worker_address: "0x...",
 *   amount: "1000000",   // ytest.usd units (6 decimals)
 *   version: 2           // state version to sign (next version, same as client submitted)
 * }
 * Response: { success: true, data: { version, state_proof } }
 */
async function handleSignStateWorker(request: BridgeRequest): Promise<BridgeResponse> {
  const appSessionIdRaw = request.app_session_id as string;
  const workerPrivateKeyRaw = request.worker_private_key as string;
  const clientAddressRaw = request.client_address as string;
  const workerAddressRaw = request.worker_address as string;
  const amountRaw = request.amount as string;
  const versionReq = request.version as number;

  if (!appSessionIdRaw || !workerPrivateKeyRaw || !clientAddressRaw || !workerAddressRaw || amountRaw === undefined || versionReq == null) {
    return {
      success: false,
      error: "Missing required fields: app_session_id, worker_private_key, client_address, worker_address, amount, version",
    };
  }

  const workerPrivateKey = workerPrivateKeyRaw.startsWith("0x")
    ? (workerPrivateKeyRaw as `0x${string}`)
    : (`0x${workerPrivateKeyRaw}` as `0x${string}`);
  const clientAddress = clientAddressRaw.startsWith("0x")
    ? (clientAddressRaw as `0x${string}`)
    : (`0x${clientAddressRaw}` as `0x${string}`);
  const workerAddress = workerAddressRaw.startsWith("0x")
    ? (workerAddressRaw as `0x${string}`)
    : (`0x${workerAddressRaw}` as `0x${string}`);
  const appSessionId = appSessionIdRaw.startsWith("0x")
    ? (appSessionIdRaw as `0x${string}`)
    : (`0x${appSessionIdRaw}` as `0x${string}`);
  const payAmount = String(amountRaw);

  const workerAccount = privateKeyToAccount(workerPrivateKey);
  if (workerAccount.address.toLowerCase() !== workerAddress.toLowerCase()) {
    return { success: false, error: "worker_address must match worker_private_key" };
  }

  const sessionPrivateKey = generatePrivateKey();
  const sessionAccount = privateKeyToAccount(sessionPrivateKey);
  const sessionSigner = createECDSAMessageSigner(sessionPrivateKey);

  const rpcUrl = process.env.ALCHEMY_RPC_URL ?? process.env.SEPOLIA_RPC_URL ?? "https://1rpc.io/sepolia";
  const walletClient = createWalletClient({
    chain: sepolia,
    transport: http(rpcUrl),
    account: workerAccount,
  });
  if (!walletClient) {
    return { success: false, error: "Failed to create wallet client" };
  }

  const authParams = {
    session_key: sessionAccount.address,
    allowances: [{ asset: "ytest.usd", amount: "1000000000" }],
    expires_at: BigInt(Math.floor(Date.now() / 1000) + 3600),
    scope: "agentpay.steps",
  };

  const authRequestMsg = await createAuthRequestMessage({
    address: workerAccount.address,
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
        error: "Timeout waiting for worker state signature",
      });
    }, 25000);

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
    const nextVersion = versionReq;
    const allocations = [
      { asset: "ytest.usd", amount: "0", participant: clientAddress },
      { asset: "ytest.usd", amount: payAmount, participant: workerAddress },
    ];

    ws.on("message", async (data: WebSocket.Data) => {
      const raw = data.toString();
      try {
        const parsed = JSON.parse(raw) as { res?: unknown[]; req?: unknown[]; error?: { message?: string } };
        if (parsed.error) {
          const errMsg = String((parsed.error as { message?: string }).message ?? parsed.error);
          if (errMsg.includes("quorum not reached")) {
            // Worker signed; other party (client) already signed, so state may still apply
            cleanup();
            clearTimeout(timeout);
            resolve({
              success: true,
              data: {
                version: nextVersion,
                state_proof: `session:${appSessionId}:version:${nextVersion}`,
              },
            });
            return;
          }
          cleanup();
          clearTimeout(timeout);
          resolve({ success: false, error: errMsg });
          return;
        }
        const res = parsed.res as unknown[] | undefined;
        const req = parsed.req as unknown[] | undefined;
        const method = (res?.[1] ?? req?.[1]) as string | undefined;
        const payload = (res?.[2] ?? req?.[2]) as Record<string, unknown> | undefined;

        if (method === "auth_challenge") {
          const challenge = (payload?.challenge_message as string) ?? "";
          const signer = createEIP712AuthMessageSigner(walletClient, authParams, { name: APPLICATION_NAME });
          ws.send(await createAuthVerifyMessageFromChallenge(signer, challenge));
          return;
        }

        if (method === "auth_verify") {
          authenticated = true;
          const submitMsg = await createSubmitAppStateMessage(
            sessionSigner,
            {
              app_session_id: appSessionId,
              intent: RPCAppStateIntent.Operate,
              version: nextVersion,
              allocations,
            },
            undefined,
            undefined
          );
          ws.send(submitMsg);
          return;
        }

        if (method === "submit_app_state" && payload) {
          cleanup();
          clearTimeout(timeout);
          resolve({
            success: true,
            data: {
              version: (payload.version as number) ?? nextVersion,
              state_proof: `session:${appSessionId}:version:${nextVersion}`,
            },
          });
          return;
        }

        if (method === "asu") {
          cleanup();
          clearTimeout(timeout);
          resolve({
            success: true,
            data: {
              version: nextVersion,
              state_proof: `session:${appSessionId}:version:${nextVersion}`,
            },
          });
          return;
        }

        if (method === "error" && payload) {
          const msg = String(payload.error ?? payload.message ?? payload ?? "");
          if (msg.includes("quorum not reached")) {
            cleanup();
            clearTimeout(timeout);
            resolve({
              success: true,
              data: {
                version: nextVersion,
                state_proof: `session:${appSessionId}:version:${nextVersion}`,
              },
            });
            return;
          }
        }
      } catch (e) {
        // Ignore parse errors
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
 * Step 4a: Create channel only (on-chain). No resize, no transfer.
 * Request: { command: "create_channel", client_private_key: "0x..." }
 * Response: { success: true, data: { channel_id: "0x...", tx_hash: "0x..." } } or if channel already open: { channel_id, tx_hash: null }
 */
async function handleCreateChannel(request: BridgeRequest): Promise<BridgeResponse> {
  const clientPrivateKeyRaw = request.client_private_key as string;
  if (!clientPrivateKeyRaw) {
    return { success: false, error: "Missing client_private_key" };
  }
  const clientPrivateKey = clientPrivateKeyRaw.startsWith("0x")
    ? (clientPrivateKeyRaw as `0x${string}`)
    : (`0x${clientPrivateKeyRaw}` as `0x${string}`);
  const account = privateKeyToAccount(clientPrivateKey);
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
  if (!walletClient) return { success: false, error: "Failed to create wallet client" };
  const nitroliteClient = new NitroliteClient({
    publicClient,
    walletClient,
    stateSigner: new WalletStateSigner(walletClient),
    addresses: { custody: CUSTODY, adjudicator: ADJUDICATOR },
    chainId: sepolia.id,
    challengeDuration: 3600n,
  });
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
    application: CHANNEL_APP,
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
      resolve({ success: false, error: "Timeout waiting for channel creation" });
    }, 60000);

    ws.on("open", () => ws.send(authRequestMsg));
    ws.on("error", (err) => {
      cleanup();
      clearTimeout(timeout);
      resolve({ success: false, error: `WebSocket error: ${err.message}` });
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
          const signer = createEIP712AuthMessageSigner(walletClient, authParams, { name: CHANNEL_APP });
          ws.send(await createAuthVerifyMessageFromChallenge(signer, challenge));
          return;
        }
        if (method === "auth_verify") return;

        if (method === "channels") {
          const channels = (payload?.channels as { status?: string; channel_id?: string }[]) ?? [];
          const open = channels.find((c) => c.status === "open");
          if (open?.channel_id) {
            cleanup();
            clearTimeout(timeout);
            resolve({
              success: true,
              data: { channel_id: open.channel_id, tx_hash: null },
            });
            return;
          }
          const createMsg = await createCreateChannelMessage(sessionSigner, {
            chain_id: SEPOLIA_CHAIN_ID,
            token: DEFAULT_TOKEN,
          });
          ws.send(createMsg);
          return;
        }

        if (method === "create_channel" && payload) {
          const { channel_id, channel, state, server_signature } = payload as {
            channel_id: string;
            channel: unknown;
            state: { intent: unknown; version: unknown; state_data?: unknown; data?: unknown; allocations: { destination: string; token: string; amount: string }[] };
            server_signature: unknown;
          };
          const unsignedInitialState = {
            intent: state.intent,
            version: BigInt(state.version as number),
            data: (state.state_data ?? (state as { data?: unknown }).data ?? "0x") as `0x${string}`,
            allocations: state.allocations.map((a) => ({
              destination: a.destination,
              token: a.token,
              amount: BigInt(a.amount),
            })),
          };
          nitroliteClient
            .createChannel({
              channel: channel as Parameters<NitroliteClient["createChannel"]>[0]["channel"],
              unsignedInitialState: unsignedInitialState as Parameters<NitroliteClient["createChannel"]>[0]["unsignedInitialState"],
              serverSignature: server_signature as `0x${string}`,
            })
            .then(async (createResult) => {
              const txHash = typeof createResult === "string" ? createResult : (createResult as { txHash: string }).txHash;
              await publicClient.waitForTransactionReceipt({ hash: txHash as `0x${string}` });
              cleanup();
              clearTimeout(timeout);
              resolve({
                success: true,
                data: { channel_id, tx_hash: txHash ?? null },
              });
            })
            .catch((err) => {
              cleanup();
              clearTimeout(timeout);
              resolve({
                success: false,
                error: err instanceof Error ? err.message : String(err),
              });
            });
        }
      } catch {
        // ignore parse errors
      }
    });
  });
}

/**
 * Step 4c: One off-chain transfer to worker (from unified balance).
 * Prereq: channel exists (run create_channel first). Do NOT run 4b — in 0.5.x transfer is blocked if any channel has non-zero balance.
 * Request: { command: "channel_transfer", client_private_key: "0x...", worker_address: "0x...", amount: "1000000" }  // amount in ytest.usd units (6 decimals)
 * Response: { success: true, data: { transferred: true } }
 */
async function handleChannelTransfer(request: BridgeRequest): Promise<BridgeResponse> {
  const clientPrivateKeyRaw = request.client_private_key as string;
  const workerAddressRaw = request.worker_address as string;
  const amountRaw = request.amount as string;
  if (!clientPrivateKeyRaw || !workerAddressRaw || amountRaw === undefined) {
    return { success: false, error: "Missing client_private_key, worker_address, or amount" };
  }
  const clientPrivateKey = clientPrivateKeyRaw.startsWith("0x")
    ? (clientPrivateKeyRaw as `0x${string}`)
    : (`0x${clientPrivateKeyRaw}` as `0x${string}`);
  const workerAddress = workerAddressRaw.startsWith("0x")
    ? (workerAddressRaw as `0x${string}`)
    : (`0x${workerAddressRaw}` as `0x${string}`);
  const amount = String(amountRaw);
  const account = privateKeyToAccount(clientPrivateKey);
  const rpcUrl = process.env.ALCHEMY_RPC_URL ?? process.env.SEPOLIA_RPC_URL ?? "https://1rpc.io/sepolia";
  const walletClient = createWalletClient({
    chain: sepolia,
    transport: http(rpcUrl),
    account,
  });
  if (!walletClient) return { success: false, error: "Failed to create wallet client" };
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
    application: CHANNEL_APP,
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
      resolve({ success: false, error: "Timeout waiting for transfer" });
    }, 30000);

    ws.on("open", () => ws.send(authRequestMsg));
    ws.on("error", (err) => {
      cleanup();
      clearTimeout(timeout);
      resolve({ success: false, error: `WebSocket error: ${err.message}` });
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
          const signer = createEIP712AuthMessageSigner(walletClient, authParams, { name: CHANNEL_APP });
          ws.send(await createAuthVerifyMessageFromChallenge(signer, challenge));
          return;
        }
        if (method === "auth_verify") return;

        if (method === "channels") {
          const channels = (payload?.channels as { status?: string; channel_id?: string }[]) ?? [];
          const open = channels.find((c) => c.status === "open");
          if (!open?.channel_id) {
            cleanup();
            clearTimeout(timeout);
            resolve({
              success: false,
              error: "No open channel. Run create_channel (step 4a) first. Do not run 4b (resize) — 0.5.x blocks transfer if channel has non-zero balance.",
            });
            return;
          }
          const transferMsg = await createTransferMessage(
            sessionSigner,
            { destination: workerAddress, allocations: [{ asset: "ytest.usd", amount }] },
            Date.now()
          );
          ws.send(transferMsg);
          return;
        }

        if (method === "transfer") {
          cleanup();
          clearTimeout(timeout);
          resolve({ success: true, data: { transferred: true } });
        }
      } catch {
        // ignore parse errors
      }
    });
  });
}

/**
 * Step 4d: Close channel — on-chain settlement.
 * Request: { command: "close_channel", client_private_key: "0x..." }
 * Response: { success: true, data: { tx_hash: "0x..." } }
 */
async function handleCloseChannel(request: BridgeRequest): Promise<BridgeResponse> {
  const clientPrivateKeyRaw = request.client_private_key as string;
  if (!clientPrivateKeyRaw) {
    return { success: false, error: "Missing client_private_key" };
  }
  const clientPrivateKey = clientPrivateKeyRaw.startsWith("0x")
    ? (clientPrivateKeyRaw as `0x${string}`)
    : (`0x${clientPrivateKeyRaw}` as `0x${string}`);
  const account = privateKeyToAccount(clientPrivateKey);
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
  if (!walletClient) return { success: false, error: "Failed to create wallet client" };
  const nitroliteClient = new NitroliteClient({
    publicClient,
    walletClient,
    stateSigner: new WalletStateSigner(walletClient),
    addresses: { custody: CUSTODY, adjudicator: ADJUDICATOR },
    chainId: sepolia.id,
    challengeDuration: 3600n,
  });
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
    application: CHANNEL_APP,
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
      resolve({ success: false, error: "Timeout waiting for channel close" });
    }, 60000);

    ws.on("open", () => ws.send(authRequestMsg));
    ws.on("error", (err) => {
      cleanup();
      clearTimeout(timeout);
      resolve({ success: false, error: `WebSocket error: ${err.message}` });
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
          const signer = createEIP712AuthMessageSigner(walletClient, authParams, { name: CHANNEL_APP });
          ws.send(await createAuthVerifyMessageFromChallenge(signer, challenge));
          return;
        }
        if (method === "auth_verify") return;

        if (method === "channels") {
          const channels = (payload?.channels as { status?: string; channel_id?: string }[]) ?? [];
          const open = channels.find((c) => c.status === "open");
          if (!open?.channel_id) {
            cleanup();
            clearTimeout(timeout);
            resolve({
              success: false,
              error: "No open channel. Run create_channel (4a) first; optionally run channel_transfer (4c) then close.",
            });
            return;
          }
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
          const rawData = state.state_data ?? (state as { data?: unknown }).data ?? "0x";
          const dataHex = (typeof rawData === "string" ? (rawData.startsWith("0x") ? rawData : "0x" + rawData) : "0x") as `0x${string}`;
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
          nitroliteClient
            .closeChannel({ finalState, stateData: dataHex })
            .then(async (txHash) => {
              const h = typeof txHash === "string" ? txHash : (txHash as { txHash?: string }).txHash;
              if (h) await publicClient.waitForTransactionReceipt({ hash: h as `0x${string}` });
              cleanup();
              clearTimeout(timeout);
              resolve({
                success: true,
                data: { tx_hash: h ?? null },
              });
            })
            .catch((err) => {
              cleanup();
              clearTimeout(timeout);
              resolve({
                success: false,
                error: err instanceof Error ? err.message : String(err),
              });
            });
        }
      } catch {
        // ignore parse errors
      }
    });
  });
}

/**
 * Channel path (steps 4a, 4c, 4d): create channel if needed, transfer to worker, close channel.
 * Returns close_tx_hash so the worker can verify on Sepolia Etherscan.
 * Request: { command: "pay_via_channel", client_private_key: "0x...", worker_address: "0x...", amount: "50000" }  // amount in ytest.usd units (6 decimals)
 * Response: { success: true, data: { close_tx_hash: "0x..." } } or { success: false, error: "..." }
 */
async function handlePayViaChannel(request: BridgeRequest): Promise<BridgeResponse> {
  const clientPrivateKeyRaw = request.client_private_key as string;
  const workerAddressRaw = request.worker_address as string;
  const amountRaw = request.amount as string;
  if (!clientPrivateKeyRaw || !workerAddressRaw || amountRaw === undefined) {
    return { success: false, error: "Missing client_private_key, worker_address, or amount" };
  }
  const clientPrivateKey = clientPrivateKeyRaw.startsWith("0x")
    ? (clientPrivateKeyRaw as `0x${string}`)
    : (`0x${clientPrivateKeyRaw}` as `0x${string}`);
  const workerAddress = workerAddressRaw.startsWith("0x")
    ? (workerAddressRaw as `0x${string}`)
    : (`0x${workerAddressRaw}` as `0x${string}`);
  const amount = String(amountRaw);
  const account = privateKeyToAccount(clientPrivateKey);
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
  if (!walletClient) return { success: false, error: "Failed to create wallet client" };
  const nitroliteClient = new NitroliteClient({
    publicClient,
    walletClient,
    stateSigner: new WalletStateSigner(walletClient),
    addresses: { custody: CUSTODY, adjudicator: ADJUDICATOR },
    chainId: sepolia.id,
    challengeDuration: 3600n,
  });
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
    application: CHANNEL_APP,
    ...authParams,
  });

  const ensureChannel = (): Promise<void> =>
    new Promise((resolve, reject) => {
      const ws = new WebSocket(SANDBOX_WS);
      const timeout = setTimeout(() => {
        ws.removeAllListeners();
        ws.close(1000);
        reject(new Error("Timeout ensuring channel"));
      }, 45000);
      ws.on("open", () => ws.send(authRequestMsg));
      ws.on("error", (err) => {
        clearTimeout(timeout);
        reject(err);
      });
      ws.on("message", async (data: WebSocket.Data) => {
        const raw = data.toString();
        try {
          const parsed = JSON.parse(raw) as { res?: unknown[]; error?: { message?: string } };
          if (parsed.error) {
            clearTimeout(timeout);
            reject(new Error(String(parsed.error.message ?? parsed.error)));
            return;
          }
          const res = parsed.res as unknown[] | undefined;
          const method = res?.[1] as string | undefined;
          const payload = res?.[2] as Record<string, unknown> | undefined;
          if (method === "auth_challenge") {
            const challenge = (payload?.challenge_message as string) ?? "";
            const signer = createEIP712AuthMessageSigner(walletClient, authParams, { name: CHANNEL_APP });
            ws.send(await createAuthVerifyMessageFromChallenge(signer, challenge));
            return;
          }
          if (method === "auth_verify") return;
          if (method === "channels") {
            const channels = (payload?.channels as { status?: string; channel_id?: string }[]) ?? [];
            const open = channels.find((c) => c.status === "open");
            if (open?.channel_id) {
              clearTimeout(timeout);
              ws.removeAllListeners();
              ws.close(1000);
              resolve();
              return;
            }
            const createMsg = await createCreateChannelMessage(sessionSigner, {
              chain_id: SEPOLIA_CHAIN_ID,
              token: DEFAULT_TOKEN,
            });
            ws.send(createMsg);
            return;
          }
          if (method === "create_channel" && payload) {
            const { channel_id, channel, state, server_signature } = payload as {
              channel_id: string;
              channel: unknown;
              state: { intent: unknown; version: unknown; state_data?: unknown; data?: unknown; allocations: { destination: string; token: string; amount: string }[] };
              server_signature: unknown;
            };
            const unsignedInitialState = {
              intent: state.intent,
              version: BigInt(state.version as number),
              data: (state.state_data ?? (state as { data?: unknown }).data ?? "0x") as `0x${string}`,
              allocations: state.allocations.map((a) => ({
                destination: a.destination,
                token: a.token,
                amount: BigInt(a.amount),
              })),
            };
            try {
              const createResult = await nitroliteClient.createChannel({
                channel: channel as Parameters<NitroliteClient["createChannel"]>[0]["channel"],
                unsignedInitialState: unsignedInitialState as Parameters<NitroliteClient["createChannel"]>[0]["unsignedInitialState"],
                serverSignature: server_signature as `0x${string}`,
              });
              const txHash = typeof createResult === "string" ? createResult : (createResult as { txHash: string }).txHash;
              await publicClient.waitForTransactionReceipt({ hash: txHash as `0x${string}` });
            } catch (e) {
              clearTimeout(timeout);
              reject(e as Error);
              return;
            }
            clearTimeout(timeout);
            ws.removeAllListeners();
            ws.close(1000);
            resolve();
          }
        } catch (e) {
          // ignore parse errors
        }
      });
    });

  let openChannelId: string | undefined;
  const transferAndClose = (): Promise<string> =>
    new Promise((resolve, reject) => {
      const ws = new WebSocket(SANDBOX_WS);
      const timeout = setTimeout(() => {
        ws.removeAllListeners();
        ws.close(1000);
        reject(new Error("Timeout transfer+close"));
      }, 60000);
      ws.on("open", () => ws.send(authRequestMsg));
      ws.on("error", (err) => {
        clearTimeout(timeout);
        reject(err);
      });
      ws.on("message", async (data: WebSocket.Data) => {
        const raw = data.toString();
        try {
          const parsed = JSON.parse(raw) as { res?: unknown[]; error?: { message?: string } };
          if (parsed.error) {
            clearTimeout(timeout);
            reject(new Error(String(parsed.error.message ?? parsed.error)));
            return;
          }
          const res = parsed.res as unknown[] | undefined;
          const method = res?.[1] as string | undefined;
          const payload = res?.[2] as Record<string, unknown> | undefined;
          if (method === "auth_challenge") {
            const challenge = (payload?.challenge_message as string) ?? "";
            const signer = createEIP712AuthMessageSigner(walletClient, authParams, { name: CHANNEL_APP });
            ws.send(await createAuthVerifyMessageFromChallenge(signer, challenge));
            return;
          }
          if (method === "auth_verify") return;
          if (method === "channels") {
            const channels = (payload?.channels as { status?: string; channel_id?: string }[]) ?? [];
            const open = channels.find((c) => c.status === "open");
            if (!open?.channel_id) {
              clearTimeout(timeout);
              reject(new Error("No open channel; run ensureChannel first"));
              return;
            }
            openChannelId = open.channel_id;
            const transferMsg = await createTransferMessage(
              sessionSigner,
              { destination: workerAddress, allocations: [{ asset: "ytest.usd", amount }] },
              Date.now()
            );
            ws.send(transferMsg);
            return;
          }
          if (method === "transfer") {
            if (!openChannelId) {
              clearTimeout(timeout);
              reject(new Error("No channel_id for close"));
              return;
            }
            const closeMsg = await createCloseChannelMessage(sessionSigner, openChannelId as `0x${string}`, account.address);
            ws.send(closeMsg);
            return;
          }
          if (method === "close_channel" && payload) {
            const { channel_id, state, server_signature } = payload as {
              channel_id: string;
              state: { intent: unknown; version: unknown; state_data?: unknown; data?: unknown; allocations: { destination: string; token: string; amount: string }[] };
              server_signature: unknown;
            };
            const rawData = state.state_data ?? (state as { data?: unknown }).data ?? "0x";
            const dataHex = (typeof rawData === "string" ? (rawData.startsWith("0x") ? rawData : "0x" + rawData) : "0x") as `0x${string}`;
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
            nitroliteClient
              .closeChannel({ finalState, stateData: dataHex })
              .then((txHash) => {
                const h = typeof txHash === "string" ? txHash : (txHash as { txHash?: string }).txHash;
                clearTimeout(timeout);
                ws.removeAllListeners();
                ws.close(1000);
                resolve(h ?? "");
              })
              .catch((err) => {
                clearTimeout(timeout);
                reject(err);
              });
          }
        } catch (e) {
          // ignore
        }
      });
    });

  try {
    await ensureChannel();
    const closeTxHash = await transferAndClose();
    return { success: true, data: { close_tx_hash: closeTxHash } };
  } catch (e) {
    return {
      success: false,
      error: e instanceof Error ? e.message : String(e),
    };
  }
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
      case "steps_1_to_3":
        response = await handleSteps1To3(request);
        break;
      case "create_channel":
        response = await handleCreateChannel(request);
        break;
      case "channel_transfer":
        response = await handleChannelTransfer(request);
        break;
      case "close_channel":
        response = await handleCloseChannel(request);
        break;
      case "create_session":
        response = await handleCreateSession(request);
        break;
      case "submit_state":
        response = await handleSubmitState(request);
        break;
      case "sign_state_worker":
        response = await handleSignStateWorker(request);
        break;
      case "close_session":
        response = await handleCloseSession(request);
        break;
      case "pay_via_channel":
        response = await handlePayViaChannel(request);
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
