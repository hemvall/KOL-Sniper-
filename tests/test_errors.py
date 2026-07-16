from kol_sniper.errors import safe_error


def test_error_redaction_removes_urls_and_tokens() -> None:
    error = RuntimeError("POST https://rpc.example/?api-key=secret token=also-secret failed")
    sanitized = safe_error(error)
    assert "secret" not in sanitized
    assert "rpc.example" not in sanitized
