"""
btquantr/execution/hl_connector.py — Conector Python ↔ HyperLiquid.

Usa el SDK oficial hyperliquid-python-sdk con agent wallets.
Interfaz idéntica a MT5Connector para uso intercambiable en ExecutionRouter.
"""
from __future__ import annotations

import logging
import os
from typing import Optional

log = logging.getLogger("BTQUANTRhl")

# URLs de HyperLiquid
_MAINNET_URL = "https://api.hyperliquid.xyz"
_TESTNET_URL = "https://api.hyperliquid-testnet.xyz"


class HLConnector:
    """Conector directo con HyperLiquid vía la librería hyperliquid-python-sdk.

    Uso:
        conn = HLConnector()                    # mainnet
        conn = HLConnector(testnet=True)        # testnet
        conn.connect("0xTU_PRIVATE_KEY")
        positions = conn.get_positions()
        conn.send_order("BTC", "BUY", size=0.1)
        conn.close_position("BTC")
        conn.disconnect()
    """

    def __init__(
        self,
        base_url: Optional[str] = None,
        order_signer=None,
        testnet: bool = False,
    ) -> None:
        # Determinar URL: argumento explícito > testnet param > HL_TESTNET env var > mainnet
        if base_url is not None:
            self.base_url = base_url
        elif testnet or os.environ.get("HL_TESTNET", "").lower() == "true":
            self.base_url = _TESTNET_URL
        else:
            self.base_url = _MAINNET_URL
        self.is_connected: bool = False
        self._exchange = None
        self._info = None
        self._address: Optional[str] = None
        self.order_signer = order_signer

    # ── Ciclo de vida ──────────────────────────────────────────────────────

    def connect(self, private_key: str) -> bool:
        """Inicializa la conexión con HyperLiquid usando una clave privada.

        Returns:
            True si la conexión fue exitosa, False en caso contrario.
        """
        try:
            from eth_account import Account
            from hyperliquid.exchange import Exchange
            from hyperliquid.info import Info

            account = Account.from_key(private_key)
            self._address = account.address
            self._exchange = Exchange(account, self.base_url)
            self._info = Info(self.base_url)
            self.is_connected = True
            return True
        except Exception as exc:
            log.error("HLConnector.connect error: %s", exc)
            self.is_connected = False
            return False

    def connect_from_vault_or_env(
        self,
        master_password: Optional[str] = None,
        key_name: str = "HL_PRIVATE_KEY",
    ) -> bool:
        """Conecta usando la clave privada del vault (si existe) o .env.

        Args:
            master_password: contraseña maestra del CredentialVault (puede ser None).
            key_name: nombre de la clave en vault/.env (default "HL_PRIVATE_KEY").

        Returns:
            True si la conexión fue exitosa, False si no se encontró la clave.
        """
        from btquantr.security.credential_vault import vault_or_env
        private_key = vault_or_env(key_name, master_password=master_password)
        if not private_key:
            log.error("HLConnector: no se encontró '%s' en vault ni en .env", key_name)
            return False
        return self.connect(private_key)

    def disconnect(self) -> None:
        """Cierra la conexión."""
        self._exchange = None
        self._info = None
        self._address = None
        self.is_connected = False

    # ── Balance ───────────────────────────────────────────────────────────

    def get_balance(self) -> float:
        """Retorna el valor total de la cuenta (crossMarginSummary.accountValue).

        Returns:
            float — balance en USD, o 0.0 si no está conectado.
        """
        if not self._info or not self._address:
            return 0.0
        try:
            state = self._info.user_state(self._address)
            margin = state.get("crossMarginSummary", {})
            return float(margin.get("accountValue", 0.0))
        except Exception as exc:
            log.error("HLConnector.get_balance error: %s", exc)
            return 0.0

    # ── Posiciones ────────────────────────────────────────────────────────

    def get_positions(self) -> list[dict]:
        """Retorna posiciones abiertas del wallet conectado."""
        if not self._info or not self._address:
            return []

        try:
            state = self._info.user_state(self._address)
            asset_positions = state.get("assetPositions", [])
            result = []
            for ap in asset_positions:
                pos = ap.get("position", {})
                szi = float(pos.get("szi", 0))
                if szi == 0:
                    continue
                result.append({
                    "symbol":          pos.get("coin", ""),
                    "direction":       "BUY" if szi > 0 else "SELL",
                    "size":            abs(szi),
                    "entry_price":     float(pos.get("entryPx", 0)),
                    "unrealized_pnl":  float(pos.get("unrealizedPnl", 0)),
                    "liq_price":       float(pos.get("liquidationPx") or 0),
                })
            return result
        except Exception as exc:
            log.error("HLConnector.get_positions error: %s", exc)
            return []

    # ── Envío de órdenes ──────────────────────────────────────────────────

    def send_order(
        self,
        symbol: str,
        direction: str,
        size: float,
        sl: Optional[float] = None,
        tp: Optional[float] = None,
    ) -> dict:
        """Envía una orden de mercado a HyperLiquid.

        Args:
            symbol:    Coin name (ej. "BTC", "ETH")
            direction: "BUY" o "SELL"
            size:      Tamaño en la unidad del activo
            sl:        Stop Loss (ignorado por HL market orders, reservado)
            tp:        Take Profit (ignorado por HL market orders, reservado)

        Returns:
            {"success": bool, "order_id": int | None, "error": str | None}
        """
        if not self._exchange:
            return {"success": False, "error": "not connected"}

        # ── Firma HMAC-SHA256 (si hay signer configurado) ─────────────────
        signed_order: Optional[dict] = None
        signature_hash: Optional[str] = None
        if self.order_signer is not None:
            signed_order = self.order_signer.sign_order(symbol, direction, size)
            signature_hash = signed_order["signature"]
            log.debug(
                "HLConnector order signed: %s %s %.6f | hash=%s…",
                symbol, direction, size, signature_hash[:16],
            )

        try:
            is_buy = direction.upper() == "BUY"
            response = self._exchange.market_open(name=symbol, is_buy=is_buy, sz=size)

            if response.get("status") != "ok":
                return {"success": False, "order_id": None,
                        "error": str(response.get("response", "unknown error"))}

            # Extraer order ID de la respuesta del SDK
            try:
                statuses = response["response"]["data"]["statuses"]
                filled = statuses[0].get("filled", {})
                order_id = filled.get("oid")
            except (KeyError, IndexError, TypeError):
                order_id = None

            result: dict = {"success": True, "order_id": order_id}
            if signed_order is not None:
                result["signed"] = True
                result["signature_hash"] = signature_hash
                result["signed_order"] = signed_order
            return result
        except Exception as exc:
            log.error("HLConnector.send_order error: %s", exc)
            return {"success": False, "order_id": None, "error": str(exc)}

    # ── Cerrar posición ───────────────────────────────────────────────────

    def close_position(self, symbol: str) -> dict:
        """Cierra completamente la posición de un símbolo.

        Returns:
            {"success": bool, "order_id": int | None, "error": str | None}
        """
        if not self._exchange:
            return {"success": False, "error": "not connected"}

        try:
            response = self._exchange.market_close(coin=symbol)

            if response.get("status") != "ok":
                return {"success": False, "order_id": None,
                        "error": str(response.get("response", "unknown error"))}

            try:
                statuses = response["response"]["data"]["statuses"]
                filled = statuses[0].get("filled", {})
                order_id = filled.get("oid")
            except (KeyError, IndexError, TypeError):
                order_id = None

            return {"success": True, "order_id": order_id}
        except Exception as exc:
            log.error("HLConnector.close_position error: %s", exc)
            return {"success": False, "order_id": None, "error": str(exc)}
