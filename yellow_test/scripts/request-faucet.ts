/**
 * Request test tokens (ytest.usd) from Yellow sandbox faucet.
 * Usage: npm run faucet
 * Set FAUCET_ADDRESS in .env or pass as first arg (default: address from PRIVATE_KEY).
 */

import "dotenv/config";
import { privateKeyToAccount } from "viem/accounts";

function getEnv(name: string): string {
  const v = process.env[name];
  if (!v) throw new Error(`Missing env: ${name}`);
  return v;
}

async function main() {
  const pk = process.env.PRIVATE_KEY;
  const address = process.env.FAUCET_ADDRESS ?? (pk ? privateKeyToAccount((pk.startsWith("0x") ? pk : `0x${pk}`) as `0x${string}`).address : null);
  if (!address) {
    console.error("Set PRIVATE_KEY in .env, or FAUCET_ADDRESS=0x...");
    process.exit(1);
  }
  const url = "https://clearnet-sandbox.yellow.com/faucet/requestTokens";
  const res = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ userAddress: address }),
  });
  const text = await res.text();
  if (!res.ok) {
    console.error("Faucet error:", res.status, text);
    process.exit(1);
  }
  console.log("Faucet response:", text || "OK");
  console.log("Requested tokens for:", address);
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
