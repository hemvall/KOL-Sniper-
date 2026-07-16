from kol_sniper.parser import extract_mint, is_solana_address

from .conftest import MINT


def test_extracts_contextual_mint_before_generic_addresses() -> None:
    text = f"wallet 9xQeWvG816bUx9EPfEZ7vVfNqK3mVZp8dNhkZ8sKZ5xV pump.fun/coin/{MINT}"
    assert extract_mint(text) == MINT


def test_rejects_embedded_and_program_addresses() -> None:
    assert extract_mint("x" + MINT + "y") is None
    assert extract_mint("11111111111111111111111111111111") is None


def test_address_requires_exactly_32_decoded_bytes() -> None:
    assert is_solana_address(MINT)
    assert not is_solana_address("not-a-mint")
