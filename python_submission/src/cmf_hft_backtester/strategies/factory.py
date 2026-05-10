from __future__ import annotations

from .as_ewma_vol import AvellanedaStoikovEWMAVolatilityStrategy
from .as_microprice import AvellanedaStoikovMicropriceStrategy
from .as_obi_hybrid import AvellanedaStoikovOBIHybridStrategy
from .avellaneda_stoikov_mid import AvellanedaStoikovStrategy
from .base import BaseStrategy
from .fixed_spread import FixedSpreadMarketMaker


def build_strategy(config: dict, market_config: dict, risk_config: dict) -> BaseStrategy:
    name = config.get("name", "fixed_spread")
    if name == "fixed_spread":
        return FixedSpreadMarketMaker(config, market_config, risk_config)
    if name == "avellaneda_stoikov_mid":
        return AvellanedaStoikovStrategy(config, market_config, risk_config)
    if name == "avellaneda_stoikov_microprice":
        return AvellanedaStoikovMicropriceStrategy(config, market_config, risk_config)
    if name == "as_obi_hybrid":
        return AvellanedaStoikovOBIHybridStrategy(config, market_config, risk_config)
    if name == "as_ewma_vol":
        return AvellanedaStoikovEWMAVolatilityStrategy(config, market_config, risk_config)
    raise ValueError(f"Unknown strategy: {name}")
