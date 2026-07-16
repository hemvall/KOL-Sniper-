#!/usr/bin/env node
import readline from "node:readline";
import { createRequire } from "node:module";
import { pathToFileURL } from "node:url";
import BN from "bn.js";
import {
  ComputeBudgetProgram,
  Connection,
  PublicKey,
  SystemProgram,
  TransactionMessage,
  VersionedTransaction,
} from "@solana/web3.js";

// The SDK's ESM dependency tree is incompatible with Node 24's stricter CJS
// named-export handling. Its official CommonJS export works on Node 20–24.
const require = createRequire(import.meta.url);
const {
  OnlinePumpSdk,
  PUMP_SDK,
  getBuyTokenAmountFromSolAmount,
  getSellSolAmountFromTokenAmount,
} = require("@pump-fun/pump-sdk");
const { OnlinePumpAmmSdk, PUMP_AMM_SDK, canonicalPumpPoolPda } =
  require("@pump-fun/pump-swap-sdk");

const rpcUrl = process.env.RPC_URL || "https://api.mainnet-beta.solana.com";
const connection = new Connection(rpcUrl, "processed");
const onlineSdk = new OnlinePumpSdk(connection);
const onlineAmmSdk = new OnlinePumpAmmSdk(connection);
const COMPUTE_UNIT_LIMIT = 300_000;
let globalCache = null;
let feeConfigCache = null;
let globalFetchedAt = 0;
let blockhashCache = null;
let blockhashFetchedAt = 0;

export function safeBuilderError(error) {
  return String(error?.message || error || "builder failed")
    .replace(/https?:\/\/[^\s'\"]+/g, "<redacted-url>")
    .replace(/(api[_-]?key|token|authorization)=([^&\s]+)/gi, "$1=<redacted>")
    .slice(0, 240);
}

async function globalState() {
  const now = Date.now();
  if (!globalCache || now - globalFetchedAt > 30_000) {
    [globalCache, feeConfigCache] = await Promise.all([
      onlineSdk.fetchGlobal(),
      onlineSdk.fetchFeeConfig(),
    ]);
    globalFetchedAt = now;
  }
  return globalCache;
}

async function latestBlockhash(force = false) {
  const now = Date.now();
  if (force || !blockhashCache || now - blockhashFetchedAt > 12_000) {
    blockhashCache = await connection.getLatestBlockhash("processed");
    blockhashFetchedAt = now;
  }
  return blockhashCache;
}

function positiveNumber(value, name) {
  const number = Number(value);
  if (!Number.isFinite(number) || number <= 0) {
    throw new Error(`${name} must be a positive finite number`);
  }
  return number;
}

export async function build(request) {
  if (request.action === "warmup") {
    await Promise.all([globalState(), latestBlockhash(true)]);
    return { ok: true, warmed: true };
  }
  const mint = new PublicKey(request.mint);
  const user = new PublicKey(request.wallet);
  const slippage = Number(request.slippageBps) / 100;
  if (!Number.isFinite(slippage) || slippage <= 0 || slippage > 50) {
    throw new Error("slippageBps must be between 1 and 5000");
  }
  const global = await globalState();
  const feeConfig = feeConfigCache;
  const [mintAccountInfo, tokenSupply] = await Promise.all([
    connection.getAccountInfo(mint, "processed"),
    connection.getTokenSupply(mint, "processed"),
  ]);
  if (!mintAccountInfo) {
    throw new Error("mint account does not exist");
  }
  const tokenProgram = mintAccountInfo.owner;
  if (tokenSupply.value.decimals !== 6) {
    throw new Error("only six-decimal Pump mints are supported");
  }
  const mintSupply = new BN(tokenSupply.value.amount);
  let tradeInstructions;
  let pool = "bonding-curve";

  if (request.action === "buy") {
    if (request.amountInTokens) {
      throw new Error("bonding-curve buys must be denominated in SOL");
    }
    const sol = positiveNumber(request.amount, "amount");
    const solAmount = new BN(Math.round(sol * 1e9));
    let bondingState = null;
    try {
      bondingState = await onlineSdk.fetchBuyState(mint, user, tokenProgram);
    } catch {
      // Graduated tokens no longer have a usable bonding-curve state.
    }
    if (bondingState && !bondingState.bondingCurve.complete) {
      const { bondingCurveAccountInfo, bondingCurve, associatedUserAccountInfo } = bondingState;
      tradeInstructions = await PUMP_SDK.buyInstructions({
        global,
        bondingCurveAccountInfo,
        bondingCurve,
        associatedUserAccountInfo,
        mint,
        user,
        solAmount,
        amount: getBuyTokenAmountFromSolAmount({
          global,
          feeConfig,
          mintSupply,
          bondingCurve,
          amount: solAmount,
          quoteMint: bondingCurve.quoteMint,
        }),
        slippage,
        tokenProgram,
      });
    } else {
      const swapState = await onlineAmmSdk.swapSolanaState(canonicalPumpPoolPda(mint), user);
      tradeInstructions = await PUMP_AMM_SDK.buyQuoteInput(swapState, solAmount, slippage);
      pool = "pump-amm";
    }
  } else if (request.action === "sell") {
    if (!request.amountInTokens) {
      throw new Error("bonding-curve sells must be denominated in tokens");
    }
    const tokens = positiveNumber(request.amount, "amount");
    const tokenAmount = new BN(Math.round(tokens * 1e6));
    let bondingState = null;
    try {
      bondingState = await onlineSdk.fetchSellState(mint, user, tokenProgram);
    } catch {
      // Graduated tokens no longer have a usable bonding-curve state.
    }
    if (bondingState && !bondingState.bondingCurve.complete) {
      const { bondingCurveAccountInfo, bondingCurve } = bondingState;
      tradeInstructions = await PUMP_SDK.sellInstructions({
        global,
        bondingCurveAccountInfo,
        bondingCurve,
        mint,
        user,
        amount: tokenAmount,
        solAmount: getSellSolAmountFromTokenAmount({
          global,
          feeConfig,
          mintSupply,
          bondingCurve,
          amount: tokenAmount,
        }),
        slippage,
        tokenProgram,
        mayhemMode: bondingCurve.isMayhemMode,
        cashback: bondingCurve.isCashbackCoin,
      });
    } else {
      const swapState = await onlineAmmSdk.swapSolanaState(canonicalPumpPoolPda(mint), user);
      tradeInstructions = await PUMP_AMM_SDK.sellBaseInput(swapState, tokenAmount, slippage);
      pool = "pump-amm";
    }
  } else {
    throw new Error("action must be buy or sell");
  }

  const priorityFeeSol = Math.max(0, Number(request.priorityFeeSol || 0));
  const microLamports = Math.max(1, Math.round((priorityFeeSol * 1e15) / COMPUTE_UNIT_LIMIT));
  const instructions = [
    ComputeBudgetProgram.setComputeUnitLimit({ units: COMPUTE_UNIT_LIMIT }),
    ComputeBudgetProgram.setComputeUnitPrice({ microLamports }),
    ...tradeInstructions,
  ];
  const tipSol = Math.max(0, Number(request.tipSol || 0));
  if (tipSol > 0) {
    if (!request.tipAccount) {
      throw new Error("tipAccount is required when tipSol is positive");
    }
    instructions.push(
      SystemProgram.transfer({
        fromPubkey: user,
        toPubkey: new PublicKey(request.tipAccount),
        lamports: Math.round(tipSol * 1e9),
      }),
    );
  }

  const { blockhash, lastValidBlockHeight } = await latestBlockhash();
  const message = new TransactionMessage({
    payerKey: user,
    recentBlockhash: blockhash,
    instructions,
  }).compileToV0Message();
  const transaction = new VersionedTransaction(message);
  return {
    ok: true,
    transaction: Buffer.from(transaction.serialize()).toString("base64"),
    includesPriorityFee: priorityFeeSol > 0,
    includesSenderTip: tipSol > 0,
    lastValidBlockHeight,
    pool,
  };
}

// Keep immutable global config and a recent blockhash hot between Telegram
// signals. Failures are ignored here and retried synchronously on demand.
setInterval(() => {
  Promise.all([globalState(), latestBlockhash(true)]).catch(() => {});
}, 10_000).unref();

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  const lines = readline.createInterface({ input: process.stdin, crlfDelay: Infinity });
  for await (const line of lines) {
    if (!line.trim()) continue;
    try {
      const result = await build(JSON.parse(line));
      process.stdout.write(`${JSON.stringify(result)}\n`);
    } catch (error) {
      process.stdout.write(
        `${JSON.stringify({ ok: false, error: safeBuilderError(error) })}\n`,
      );
    }
  }
}
