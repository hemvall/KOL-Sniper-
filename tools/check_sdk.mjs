import { createRequire } from "node:module";

const require = createRequire(import.meta.url);
const pump = require("@pump-fun/pump-sdk");
const amm = require("@pump-fun/pump-swap-sdk");

for (const [name, value] of Object.entries({
  OnlinePumpSdk: pump.OnlinePumpSdk,
  PUMP_SDK: pump.PUMP_SDK,
  OnlinePumpAmmSdk: amm.OnlinePumpAmmSdk,
  PUMP_AMM_SDK: amm.PUMP_AMM_SDK,
  canonicalPumpPoolPda: amm.canonicalPumpPoolPda,
})) {
  if (!value) throw new Error(`missing required SDK export: ${name}`);
}
