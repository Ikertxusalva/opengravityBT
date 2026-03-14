"""
btquantr/security/order_signer.py — OrderSigner.

Firma HMAC-SHA256 cada orden antes de enviarla al exchange.

  - Payload canónico: symbol={S}:direction={D}:size={sz:.6f}:timestamp={ts}:nonce={n}
  - Clave de firma: cargada desde CredentialVault o env ORDER_SIGNING_KEY.
  - Nunca loguea la clave; solo registra el hexdigest (seguro para auditoría).

Uso:
    signer = OrderSigner("mi_clave_secreta")
    signed = signer.sign_order("BTC", "BUY", 0.1)
    ok = signer.verify_order(signed)   # True

    # Desde vault / .env (factory):
    signer = OrderSigner.from_vault_or_env(master_password="mi_pass")
"""
from __future__ import annotations

import hashlib
import hmac
import logging
import os
import secrets
import time
from typing import Optional

log = logging.getLogger("BTQUANTROrderSigner")

_DEFAULT_KEY_NAME = "ORDER_SIGNING_KEY"


class OrderSigner:
    """Firma y verifica órdenes de trading con HMAC-SHA256.

    La clave de firma se guarda en memoria como bytes; nunca se serializa
    ni se incluye en __repr__ / __str__ para evitar filtraciones en logs.
    """

    def __init__(self, signing_key: str) -> None:
        if not signing_key:
            raise ValueError("signing_key no puede ser vacía")
        # Almacenar como bytes internamente
        self._key: bytes = signing_key.encode("utf-8")

    # ── Representación segura ─────────────────────────────────────────────────

    def __repr__(self) -> str:
        return "OrderSigner(<key redacted>)"

    def __str__(self) -> str:
        return "OrderSigner(<key redacted>)"

    # ── API pública ───────────────────────────────────────────────────────────

    def sign_order(
        self,
        symbol: str,
        direction: str,
        size: float,
        timestamp: Optional[int] = None,
        nonce: Optional[str] = None,
    ) -> dict:
        """Firma una orden y retorna el payload firmado.

        Args:
            symbol:    Símbolo del activo (ej. "BTC").
            direction: "BUY" o "SELL".
            size:      Tamaño de la orden.
            timestamp: Unix timestamp (int). Si None, usa tiempo actual.
            nonce:     Cadena aleatoria única. Si None, genera automáticamente.

        Returns:
            {
                "payload":   str,  # cadena canónica firmada
                "signature": str,  # HMAC-SHA256 hexdigest (64 chars)
                "timestamp": int,
                "nonce":     str,
            }
        """
        ts    = timestamp if timestamp is not None else int(time.time())
        nc    = nonce if nonce is not None else secrets.token_hex(16)
        payload = (
            f"symbol={symbol}"
            f":direction={direction}"
            f":size={size:.6f}"
            f":timestamp={ts}"
            f":nonce={nc}"
        )
        sig = self._compute_hmac(payload)

        log.debug(
            "Order signed: %s %s %.6f | ts=%d | hash=%s…",
            symbol, direction, size, ts, sig[:16],
        )

        return {
            "payload":   payload,
            "signature": sig,
            "timestamp": ts,
            "nonce":     nc,
        }

    def verify_signature(self, payload: str, signature: str) -> bool:
        """Verifica que la firma corresponde al payload con la clave almacenada.

        Args:
            payload:   Cadena canónica original.
            signature: HMAC-SHA256 hexdigest a verificar.

        Returns:
            True si la firma es válida, False en cualquier otro caso.
        """
        if not payload or not signature:
            return False
        try:
            expected = self._compute_hmac(payload)
            return hmac.compare_digest(expected, signature)
        except Exception:
            return False

    def verify_order(self, signed_order: dict) -> bool:
        """Verifica un dict devuelto por sign_order().

        Returns:
            True si el dict es íntegro y la firma es válida.
        """
        payload   = signed_order.get("payload")
        signature = signed_order.get("signature")
        if not payload or not signature:
            return False
        return self.verify_signature(payload, signature)

    # ── Factory desde vault / env ─────────────────────────────────────────────

    @classmethod
    def from_vault_or_env(
        cls,
        master_password: Optional[str] = None,
        key_name: str = _DEFAULT_KEY_NAME,
    ) -> Optional["OrderSigner"]:
        """Crea un OrderSigner cargando la clave desde CredentialVault o .env.

        Prioridad: CredentialVault → variable de entorno → None.

        Args:
            master_password: Contraseña maestra del vault (puede ser None).
            key_name:        Nombre de la clave (default "ORDER_SIGNING_KEY").

        Returns:
            OrderSigner si se encontró la clave, None si no.
        """
        from btquantr.security.credential_vault import vault_or_env
        key = vault_or_env(key_name, master_password=master_password)
        if not key:
            log.warning(
                "OrderSigner: no se encontró '%s' en vault ni .env", key_name
            )
            return None
        return cls(key)

    # ── Interno ───────────────────────────────────────────────────────────────

    def _compute_hmac(self, payload: str) -> str:
        mac = hmac.new(self._key, payload.encode("utf-8"), hashlib.sha256)
        return mac.hexdigest()
