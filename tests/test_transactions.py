from dataclasses import dataclass

import pytest

from kol_sniper.domain import Side
from kol_sniper.validation import (
    COMPUTE_BUDGET_PROGRAM,
    PUMP_PROGRAM,
    SYSTEM_PROGRAM,
    TOKEN_PROGRAM,
    TradeIntent,
    TransactionRejected,
    TransactionValidator,
)

from .conftest import MINT, WALLET


@dataclass
class Header:
    num_required_signatures: int = 1


@dataclass
class Instruction:
    program_id_index: int
    data: bytes
    accounts: bytes = b""


class Message:
    def __init__(self, keys, instructions, signers=1):
        self.account_keys = keys
        self.instructions = instructions
        self.header = Header(signers)


class Transaction:
    def __init__(self, message):
        self.message = message


def intent(
    *,
    wallet: str = WALLET,
    mint: str = MINT,
    side: Side = Side.BUY,
    amount: float = 0.001,
) -> TradeIntent:
    return TradeIntent(wallet, mint, side, amount, 1_500, 0.0001)


def valid_transaction(extra=()):
    keys = [WALLET, COMPUTE_BUDGET_PROGRAM, PUMP_PROGRAM, MINT, SYSTEM_PROGRAM]
    discriminator = bytes([102, 6, 61, 18, 1, 218, 235, 234])
    trade = discriminator + (1_000_000).to_bytes(8, "little") + (1_150_000).to_bytes(8, "little")
    compute_limit = b"\x02" + (300_000).to_bytes(4, "little")
    compute_price = b"\x03" + (333_333).to_bytes(8, "little")
    instructions = [
        Instruction(1, compute_limit),
        Instruction(1, compute_price),
        Instruction(2, trade, bytes([0, 0, 3, 0, 0, 0, 0])),
        *extra,
    ]
    return Transaction(Message(keys, instructions))


def test_accepts_exact_bounded_buy() -> None:
    result = TransactionValidator(0.5).validate(valid_transaction(), intent())
    assert result.trade_amount_raw == 1_150_000
    assert result.priority_fee_lamports == 100_000


def test_rejects_wrong_payer_side_or_mint() -> None:
    validator = TransactionValidator(0.5)
    with pytest.raises(TransactionRejected, match="payer"):
        validator.validate(valid_transaction(), intent(wallet=SYSTEM_PROGRAM))
    with pytest.raises(TransactionRejected, match="action"):
        validator.validate(valid_transaction(), intent(side=Side.SELL))
    with pytest.raises(TransactionRejected, match="mint"):
        validator.validate(valid_transaction(), intent(mint="HHi9GXkuBchA2LugrZvTLNhzoChAZFkvQNjeDagcpump"))


def test_rejects_any_unexpected_system_transfer() -> None:
    transfer = (2).to_bytes(4, "little") + (1).to_bytes(8, "little")
    with pytest.raises(TransactionRejected, match="unexpected System"):
        TransactionValidator(0.5).validate(
            valid_transaction([Instruction(4, transfer, bytes([0, 3]))]), intent()
        )


def test_accepts_only_the_exact_configured_tip() -> None:
    transaction = valid_transaction()
    tip_account = "Vote111111111111111111111111111111111111111"
    transaction.message.account_keys.append(tip_account)
    transfer = (2).to_bytes(4, "little") + (200_000).to_bytes(8, "little")
    transaction.message.instructions.append(Instruction(4, transfer, bytes([0, 5])))
    TransactionValidator(0.5).validate(
        transaction,
        TradeIntent(WALLET, MINT, Side.BUY, 0.001, 1_500, 0.0001, 0.0002, tip_account),
    )
    with pytest.raises(TransactionRejected, match="unexpected System"):
        TransactionValidator(0.5).validate(
            transaction,
            TradeIntent(WALLET, MINT, Side.BUY, 0.001, 1_500, 0.0001, 0.0003, tip_account),
        )


def test_rejects_excessive_trade_or_priority_fee() -> None:
    transaction = valid_transaction()
    transaction.message.instructions[2].data = (
        bytes([102, 6, 61, 18, 1, 218, 235, 234])
        + (1).to_bytes(8, "little")
        + (1_150_003).to_bytes(8, "little")
    )
    with pytest.raises(TransactionRejected, match="spend"):
        TransactionValidator(0.5).validate(transaction, intent())

    transaction = valid_transaction()
    transaction.message.instructions[1].data = b"\x03" + (400_000).to_bytes(8, "little")
    with pytest.raises(TransactionRejected, match="priority fee"):
        TransactionValidator(0.5).validate(transaction, intent())


def test_rejects_multiple_trades_unknown_program_or_extra_signer() -> None:
    transaction = valid_transaction()
    transaction.message.instructions.append(transaction.message.instructions[2])
    with pytest.raises(TransactionRejected, match="exactly one"):
        TransactionValidator(0.5).validate(transaction, intent())

    transaction = valid_transaction()
    transaction.message.account_keys.append("Bad111111111111111111111111111111111111111")
    transaction.message.instructions.append(Instruction(5, b""))
    with pytest.raises(TransactionRejected, match="allowlisted"):
        TransactionValidator(0.5).validate(transaction, intent())

    transaction = valid_transaction()
    transaction.message.account_keys.append(TOKEN_PROGRAM)
    transaction.message.instructions.append(Instruction(5, b"\x03", bytes([0, 3])))
    with pytest.raises(TransactionRejected, match="token instruction"):
        TransactionValidator(0.5).validate(transaction, intent())

    transaction = valid_transaction()
    transaction.message.header.num_required_signatures = 2
    with pytest.raises(TransactionRejected, match="one signer"):
        TransactionValidator(0.5).validate(transaction, intent())
