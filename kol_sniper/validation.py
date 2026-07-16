from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .domain import Side

SYSTEM_PROGRAM = "11111111111111111111111111111111"
COMPUTE_BUDGET_PROGRAM = "ComputeBudget111111111111111111111111111111"
TOKEN_PROGRAM = "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"
TOKEN_2022_PROGRAM = "TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb"
ASSOCIATED_TOKEN_PROGRAM = "ATokenGPvbdGVxr1b2hvZbsiqW5xWH25efTNsLJA8knL"
WRAPPED_SOL_MINT = "So11111111111111111111111111111111111111112"
PUMP_PROGRAM = "6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P"
PUMP_AMM_PROGRAM = "pAMMBay6oceH9fJKBRHGP5D4bD4sWpmSwMn52FMfXEA"
ALLOWED_PROGRAMS = {
    SYSTEM_PROGRAM,
    PUMP_PROGRAM,
    PUMP_AMM_PROGRAM,
    COMPUTE_BUDGET_PROGRAM,
    TOKEN_PROGRAM,
    TOKEN_2022_PROGRAM,
    ASSOCIATED_TOKEN_PROGRAM,
}


@dataclass(frozen=True)
class InstructionLayout:
    side: Side
    mint_position: int
    user_position: int
    amount_argument: int
    quote_mint_position: int | None = None


INSTRUCTION_LAYOUTS = {
    (PUMP_PROGRAM, bytes([102, 6, 61, 18, 1, 218, 235, 234])): InstructionLayout(Side.BUY, 2, 6, 1),
    (PUMP_PROGRAM, bytes([194, 171, 28, 70, 104, 77, 91, 47])): InstructionLayout(Side.BUY, 1, 13, 0, 2),
    (PUMP_PROGRAM, bytes([56, 252, 116, 8, 158, 223, 205, 95])): InstructionLayout(Side.BUY, 2, 6, 0),
    (PUMP_PROGRAM, bytes([184, 23, 238, 97, 103, 197, 211, 61])): InstructionLayout(Side.BUY, 1, 13, 1, 2),
    (PUMP_PROGRAM, bytes([51, 230, 133, 164, 1, 127, 131, 173])): InstructionLayout(Side.SELL, 2, 6, 0),
    (PUMP_PROGRAM, bytes([93, 246, 130, 60, 231, 233, 64, 178])): InstructionLayout(Side.SELL, 1, 13, 0, 2),
    (PUMP_AMM_PROGRAM, bytes([102, 6, 61, 18, 1, 218, 235, 234])): InstructionLayout(Side.BUY, 3, 1, 1, 4),
    (PUMP_AMM_PROGRAM, bytes([198, 46, 21, 82, 180, 217, 232, 112])): InstructionLayout(Side.BUY, 3, 1, 0, 4),
    (PUMP_AMM_PROGRAM, bytes([51, 230, 133, 164, 1, 127, 131, 173])): InstructionLayout(
        Side.SELL, 3, 1, 0, 4
    ),
}


@dataclass(frozen=True)
class TradeIntent:
    wallet: str
    mint: str
    side: Side
    amount: float
    slippage_bps: int
    priority_fee_sol: float
    tip_sol: float = 0.0
    tip_account: str | None = None


@dataclass(frozen=True)
class ValidatedTransaction:
    transaction: Any
    trade_amount_raw: int
    priority_fee_lamports: int


class TransactionRejected(ValueError):
    pass


class TransactionValidator:
    """Fail-closed semantic validation for untrusted serialized transactions."""

    def __init__(self, max_system_transfer_sol: float):
        self.max_lamports = int(max_system_transfer_sol * 1_000_000_000)

    @staticmethod
    def _key(accounts: list[int], position: int, keys: list[str]) -> str:
        if len(accounts) <= position or accounts[position] >= len(keys):
            raise TransactionRejected("instruction references an unresolved account")
        return keys[accounts[position]]

    def validate(self, transaction: Any, intent: TradeIntent) -> ValidatedTransaction:
        message = transaction.message
        keys = [str(key) for key in message.account_keys]
        required_signers = int(message.header.num_required_signatures)
        if required_signers != 1:
            raise TransactionRejected(f"expected exactly one signer, received {required_signers}")
        if not keys or keys[0] != intent.wallet:
            raise TransactionRejected("transaction payer does not match configured wallet")

        trade_amounts: list[int] = []
        compute_limit: int | None = None
        compute_price: int | None = None
        ata_accounts: dict[str, str] = {}
        system_transfers: list[tuple[str, int]] = []
        token_instructions: list[tuple[bytes, list[int]]] = []
        for instruction in message.instructions:
            program_index = int(instruction.program_id_index)
            if program_index >= len(keys):
                raise TransactionRejected("program loaded through an unresolved address lookup table")
            program = keys[program_index]
            if program not in ALLOWED_PROGRAMS:
                raise TransactionRejected(f"program is not allowlisted: {program}")
            data = bytes(instruction.data)
            accounts = [int(index) for index in instruction.accounts]
            if program == COMPUTE_BUDGET_PROGRAM:
                if len(data) == 5 and data[0] == 2 and compute_limit is None:
                    compute_limit = int.from_bytes(data[1:5], "little")
                elif len(data) == 9 and data[0] == 3 and compute_price is None:
                    compute_price = int.from_bytes(data[1:9], "little")
                else:
                    raise TransactionRejected("unexpected or duplicate ComputeBudget instruction")
                continue
            if program in {PUMP_PROGRAM, PUMP_AMM_PROGRAM}:
                layout = INSTRUCTION_LAYOUTS.get((program, data[:8]))
                if layout is None or layout.side is not intent.side:
                    raise TransactionRejected("Pump instruction does not match requested action")
                if self._key(accounts, layout.mint_position, keys) != intent.mint:
                    raise TransactionRejected("transaction mint does not match the requested mint")
                if self._key(accounts, layout.user_position, keys) != intent.wallet:
                    raise TransactionRejected("Pump trade user does not match the configured wallet")
                if (
                    layout.quote_mint_position is not None
                    and self._key(accounts, layout.quote_mint_position, keys) != WRAPPED_SOL_MINT
                ):
                    raise TransactionRejected("only wrapped-SOL quote pools are supported")
                argument_start = 8 + layout.amount_argument * 8
                if len(data) < argument_start + 8:
                    raise TransactionRejected("Pump instruction data is truncated")
                trade_amounts.append(int.from_bytes(data[argument_start : argument_start + 8], "little"))
                continue
            if program == ASSOCIATED_TOKEN_PROGRAM:
                if data not in {b"", b"\x01"} or len(accounts) < 6:
                    raise TransactionRejected("unexpected associated-token instruction")
                if (
                    self._key(accounts, 0, keys) != intent.wallet
                    or self._key(accounts, 2, keys) != intent.wallet
                ):
                    raise TransactionRejected("associated-token payer/owner does not match wallet")
                ata_mint = self._key(accounts, 3, keys)
                if ata_mint not in {intent.mint, WRAPPED_SOL_MINT}:
                    raise TransactionRejected("associated-token mint is not part of the trade")
                ata_accounts[self._key(accounts, 1, keys)] = ata_mint
                if len(ata_accounts) > 2:
                    raise TransactionRejected("too many associated-token account creations")
                continue
            if program == SYSTEM_PROGRAM:
                if len(data) != 12 or int.from_bytes(data[:4], "little") != 2 or len(accounts) < 2:
                    raise TransactionRejected("only exact System transfer instructions are allowed")
                if self._key(accounts, 0, keys) != intent.wallet:
                    raise TransactionRejected("System transfer source does not match wallet")
                system_transfers.append((self._key(accounts, 1, keys), int.from_bytes(data[4:12], "little")))
                continue
            if program in {TOKEN_PROGRAM, TOKEN_2022_PROGRAM}:
                token_instructions.append((data, accounts))

        if len(trade_amounts) != 1:
            raise TransactionRejected("transaction must contain exactly one Pump trade instruction")
        trade_amount = trade_amounts[0]
        if trade_amount <= 0:
            raise TransactionRejected("Pump trade amount must be positive")
        if intent.side is Side.BUY:
            requested_cap = int(intent.amount * 1_000_000_000 * (1 + intent.slippage_bps / 10_000)) + 2
            if trade_amount > min(self.max_lamports, requested_cap):
                raise TransactionRejected("Pump buy spend exceeds the configured intent")
        elif trade_amount > round(intent.amount * 1_000_000):
            raise TransactionRejected("Pump sell amount exceeds the configured intent")

        if compute_limit is None or compute_price is None or not (1 <= compute_limit <= 1_400_000):
            raise TransactionRejected("transaction must contain bounded compute limit and price")
        priority_lamports = (compute_limit * compute_price + 999_999) // 1_000_000
        priority_cap = round(intent.priority_fee_sol * 1_000_000_000) + 2
        if priority_lamports > priority_cap:
            raise TransactionRejected("priority fee exceeds the configured intent")

        expected_tip = round(intent.tip_sol * 1_000_000_000)
        saw_tip = False
        saw_wsol_funding = False
        for recipient, lamports in system_transfers:
            if (
                intent.side is Side.BUY
                and ata_accounts.get(recipient) == WRAPPED_SOL_MINT
                and lamports == trade_amount
                and not saw_wsol_funding
            ):
                saw_wsol_funding = True
            elif (
                intent.tip_account
                and recipient == intent.tip_account
                and abs(lamports - expected_tip) <= 1
                and not saw_tip
            ):
                saw_tip = True
            else:
                raise TransactionRejected("unexpected System transfer recipient or amount")
        if expected_tip > 0 and not saw_tip:
            raise TransactionRejected("configured Sender tip is missing from transaction bytes")
        if expected_tip == 0 and saw_tip:
            raise TransactionRejected("unexpected Sender tip")

        wsol_accounts = {account for account, mint in ata_accounts.items() if mint == WRAPPED_SOL_MINT}
        sync_count = close_count = 0
        for data, accounts in token_instructions:
            if data == b"\x11" and intent.side is Side.BUY and self._key(accounts, 0, keys) in wsol_accounts:
                sync_count += 1
            elif (
                data == b"\x09"
                and self._key(accounts, 0, keys) in wsol_accounts
                and self._key(accounts, 1, keys) == intent.wallet
                and self._key(accounts, 2, keys) == intent.wallet
            ):
                close_count += 1
            else:
                raise TransactionRejected("unexpected top-level token instruction")
        if sync_count > 1 or close_count > 1:
            raise TransactionRejected("duplicate wrapped-SOL token instruction")
        return ValidatedTransaction(transaction, trade_amount, priority_lamports)
