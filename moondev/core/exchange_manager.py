"""
ExchangeManager — Facade que unifica Solana y HyperLiquid.

Uso:
    em = ExchangeManager()          # usa EXCHANGE de config
    em.market_buy("SOL", usd=25)
    pos = em.get_position("SOL")    # normalizado
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Optional
import moondev.config as cfg
from moondev.data.hyperliquid_data import get_account_state as _hl_account_state


@dataclass
class Position:
    symbol: str
    has_position: bool
    size: float = 0.0
    entry_price: float = 0.0
    current_price: float = 0.0
    pnl_pct: float = 0.0
    is_long: bool = True
    usd_value: float = 0.0


class HyperLiquidBackend:
    """Wrapper mínimo para HyperLiquid — ampliar según necesidad."""

    def __init__(self):
        self._account = None
        self._exchange = None
        self._address: str | None = None
        try:
            import eth_account
            if cfg.HYPERLIQUID_KEY:
                self._account = eth_account.Account.from_key(cfg.HYPERLIQUID_KEY)
                self._address = self._account.address
                try:
                    from hyperliquid.exchange import Exchange
                    self._exchange = Exchange(self._account, skip_ws=True)
                except ImportError:
                    pass
        except ImportError:
            print("[ExchangeManager] eth_account no instalado. Modo simulado.")

    def market_buy(self, symbol: str, usd: float) -> dict:
        if not self._exchange:
            print(f"[SIMULADO] BUY {symbol} ${usd}")
            return {"status": "simulated"}
        raise NotImplementedError("Implementar con hyperliquid.Exchange")

    def market_sell(self, symbol: str, usd: Optional[float] = None,
                    percent: float = 100.0) -> dict:
        if not self._exchange:
            print(f"[SIMULADO] SELL {symbol} {percent}%")
            return {"status": "simulated"}
        raise NotImplementedError("Implementar con hyperliquid.Exchange")

    def get_position(self, symbol: str) -> Position:
        if not self._address:
            return Position(symbol=symbol, has_position=False)
        try:
            state = _hl_account_state(self._address)
            for pos in state.get("positions", []):
                if pos["coin"] == symbol:
                    szi = pos["szi"]
                    entry = pos["entry_px"]
                    if szi == 0:
                        return Position(symbol=symbol, has_position=False)
                    return Position(
                        symbol=symbol,
                        has_position=True,
                        size=szi,
                        entry_price=entry,
                        is_long=pos["side"] == "LONG",
                        usd_value=szi * entry,
                    )
        except Exception as e:
            print(f"[HyperLiquid] Error get_position {symbol}: {e}")
        return Position(symbol=symbol, has_position=False)

    def get_account_value(self) -> float:
        if not self._address:
            return 0.0
        try:
            state = _hl_account_state(self._address)
            return state.get("account_value", 0.0)
        except Exception:
            return 0.0


class SolanaBackend:
    """Wrapper mínimo para Solana — ampliar con nice_funcs.py de moon-dev."""

    def market_buy(self, token: str, usd: float) -> dict:
        print(f"[SIMULADO Solana] BUY {token} ${usd}")
        return {"status": "simulated"}

    def market_sell(self, token: str, usd: Optional[float] = None,
                    percent: float = 100.0) -> dict:
        print(f"[SIMULADO Solana] SELL {token} {percent}%")
        return {"status": "simulated"}

    def get_position(self, token: str) -> Position:
        return Position(symbol=token, has_position=False)

    def get_account_value(self) -> float:
        return 0.0


class ExchangeManager:
    """
    Facade unificado. Lee EXCHANGE de config.py.
    Misma interfaz para Solana y HyperLiquid.
    """

    def __init__(self, exchange: Optional[str] = None):
        ex = exchange or cfg.EXCHANGE
        if ex == "hyperliquid":
            self._backend = HyperLiquidBackend()
        elif ex == "solana":
            self._backend = SolanaBackend()
        else:
            raise ValueError(f"Exchange desconocido: {ex}. Usa 'solana' o 'hyperliquid'")
        self.exchange = ex

    def market_buy(self, symbol: str, usd: float) -> dict:
        return self._backend.market_buy(symbol, usd)

    def market_sell(self, symbol: str, usd: Optional[float] = None,
                    percent: float = 100.0) -> dict:
        return self._backend.market_sell(symbol, usd=usd, percent=percent)

    def get_position(self, symbol: str) -> Position:
        return self._backend.get_position(symbol)

    def get_account_value(self) -> float:
        return self._backend.get_account_value()

    def close_position(self, symbol: str) -> dict:
        return self.market_sell(symbol, percent=100.0)
