import pytest

from kol_sniper.config import Settings


def test_live_mode_cannot_be_enabled_by_boolean_typo() -> None:
    with pytest.raises(ValueError, match="invalid boolean"):
        Settings.from_env({"DRY_RUN": "flase"})


def test_execution_fees_have_a_hard_configured_budget() -> None:
    settings = Settings(priority_fee_sol=0.02, sender_tip_sol=0.01, max_execution_fee_sol=0.01)
    assert any("MAX_EXECUTION_FEE_SOL" in error for error in settings.errors(live=False))


def test_legacy_environment_names_remain_compatible() -> None:
    settings = Settings.from_env(
        {
            "TG_API_ID": "123",
            "TG_API_HASH": "hash",
            "TG_CHANNELS": "@calls",
            "SOL_PRIVATE_KEY": "secret",
            "BUY_SOL": "0.5",
            "SLIPPAGE": "15",
            "PRIORITY_FEE": "0.001",
            "HELIUS_API_KEY": "rpc-key",
        }
    )
    assert settings.telegram_api_id == 123
    assert settings.buy_amount_sol == 0.5
    assert settings.slippage_bps == 1_500
    assert settings.rpc_url.startswith("https://mainnet.helius-rpc.com/")
    assert settings.errors(live=False) == []
