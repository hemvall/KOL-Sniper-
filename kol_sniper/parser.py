from __future__ import annotations

import re
from collections.abc import Iterable

_BASE58_ALPHABET = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
_BASE58_INDEX = {char: index for index, char in enumerate(_BASE58_ALPHABET)}
_URL_PATTERNS = (
    re.compile(r"(?:pump\.fun/(?:coin/)?|dexscreener\.com/solana/)([1-9A-HJ-NP-Za-km-z]{32,44})", re.I),
    re.compile(r"(?:mint|ca|contract)\s*[:=]\s*([1-9A-HJ-NP-Za-km-z]{32,44})", re.I),
)
_GENERIC = re.compile(r"(?<![1-9A-HJ-NP-Za-km-z])([1-9A-HJ-NP-Za-km-z]{32,44})(?![1-9A-HJ-NP-Za-km-z])")
_NON_MINTS = {
    "11111111111111111111111111111111",
    "ComputeBudget111111111111111111111111111111",
    "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA",
    "TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb",
    "So11111111111111111111111111111111111111112",
    "6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P",
    "pAMMBay6oceH9fJKBRHGP5D4bD4sWpmSwMn52FMfXEA",
}


def base58_decode(value: str) -> bytes:
    number = 0
    for char in value:
        if char not in _BASE58_INDEX:
            raise ValueError("invalid base58 character")
        number = number * 58 + _BASE58_INDEX[char]
    payload = number.to_bytes((number.bit_length() + 7) // 8, "big") if number else b""
    padding = len(value) - len(value.lstrip("1"))
    return b"\x00" * padding + payload


def is_solana_address(value: str) -> bool:
    try:
        return len(base58_decode(value)) == 32
    except ValueError:
        return False


def extract_mint(text: str, excluded: Iterable[str] = ()) -> str | None:
    denied = _NON_MINTS | set(excluded)
    candidates: list[str] = []
    for pattern in _URL_PATTERNS:
        candidates.extend(match.group(1) for match in pattern.finditer(text))
    candidates.extend(match.group(1) for match in _GENERIC.finditer(text))
    seen: set[str] = set()
    for candidate in candidates:
        if candidate in seen or candidate in denied:
            continue
        seen.add(candidate)
        if is_solana_address(candidate):
            return candidate
    return None
