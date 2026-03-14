"""
btquantr/security/credential_vault.py — CredentialVault.

Almacén cifrado de API keys y secretos.
  - AES-256-GCM con PBKDF2HMAC-SHA256 (600 000 iteraciones).
  - Formato en disco: [16-byte salt][12-byte nonce][ciphertext]
  - Nunca loguea valores.

Env var BTQUANTR_VAULT_PATH sobreescribe la ruta por defecto (data/vault.enc).
"""
from __future__ import annotations

import json
import logging
import os
import pathlib
from typing import Optional

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

log = logging.getLogger("btquantr.security.credential_vault")

_SALT_LEN = 16
_NONCE_LEN = 12
_KDF_ITERATIONS = 600_000
_DEFAULT_VAULT_PATH = "data/vault.enc"


class VaultError(Exception):
    """Error de operación en el vault."""


class CredentialVault:
    """Almacén de credenciales cifrado con AES-256-GCM.

    Uso típico:
        vault = CredentialVault()          # lee ruta de BTQUANTR_VAULT_PATH o data/vault.enc
        vault.init("mi_master_password")   # crea vault vacío
        vault.store("HL_KEY", "0xabc", "mi_master_password")
        key = vault.get("HL_KEY", "mi_master_password")
    """

    def __init__(self, vault_path: Optional[str] = None) -> None:
        if vault_path is None:
            vault_path = os.environ.get("BTQUANTR_VAULT_PATH", _DEFAULT_VAULT_PATH)
        self._path = pathlib.Path(vault_path)

    # ── API pública ───────────────────────────────────────────────────────────

    def exists(self) -> bool:
        """True si el vault ya fue inicializado."""
        return self._path.exists()

    def init(self, master_password: str) -> None:
        """Crea el vault vacío.

        Raises:
            VaultError: si el vault ya existe.
        """
        if self._path.exists():
            raise VaultError("El vault ya existe. Usa store() para añadir claves.")
        self._path.parent.mkdir(parents=True, exist_ok=True)
        salt = os.urandom(_SALT_LEN)
        self._write({}, salt, master_password)
        log.debug("Vault creado en %s", self._path)

    def store(self, name: str, value: str, master_password: str) -> None:
        """Guarda o actualiza una credencial cifrada.

        Args:
            name: nombre de la clave (p. ej. "HL_PRIVATE_KEY").
            value: valor secreto.
            master_password: contraseña maestra.

        Raises:
            VaultError: si la contraseña es incorrecta o el vault no existe.
        """
        data = self._read(master_password)
        data[name] = value
        salt = self._path.read_bytes()[:_SALT_LEN]
        self._write(data, salt, master_password)
        log.debug("Clave '%s' guardada en vault", name)

    def get(self, name: str, master_password: str) -> Optional[str]:
        """Obtiene el valor de una credencial.

        Returns:
            El valor si existe, None si la clave no está en el vault.

        Raises:
            VaultError: si la contraseña es incorrecta o el vault no existe.
        """
        data = self._read(master_password)
        value = data.get(name)
        log.debug("Clave '%s' %s", name, "encontrada" if value is not None else "no encontrada")
        return value

    def delete(self, name: str, master_password: str) -> None:
        """Elimina una credencial del vault.

        Raises:
            VaultError: si la clave no existe, contraseña incorrecta, o vault no existe.
        """
        data = self._read(master_password)
        if name not in data:
            raise VaultError(f"Clave '{name}' no encontrada en el vault")
        del data[name]
        salt = self._path.read_bytes()[:_SALT_LEN]
        self._write(data, salt, master_password)
        log.debug("Clave '%s' eliminada del vault", name)

    def list_names(self, master_password: str) -> list[str]:
        """Devuelve los nombres de todas las claves almacenadas.

        Raises:
            VaultError: si la contraseña es incorrecta o el vault no existe.
        """
        data = self._read(master_password)
        return list(data.keys())

    # ── Internals ─────────────────────────────────────────────────────────────

    def _derive_key(self, salt: bytes, master_password: str) -> bytes:
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=salt,
            iterations=_KDF_ITERATIONS,
        )
        return kdf.derive(master_password.encode("utf-8"))

    def _write(self, data: dict, salt: bytes, master_password: str) -> None:
        key = self._derive_key(salt, master_password)
        nonce = os.urandom(_NONCE_LEN)
        aesgcm = AESGCM(key)
        plaintext = json.dumps(data).encode("utf-8")
        ciphertext = aesgcm.encrypt(nonce, plaintext, None)
        self._path.write_bytes(salt + nonce + ciphertext)

    def _read(self, master_password: str) -> dict:
        if not self._path.exists():
            raise VaultError(
                "Vault no existe. Ejecuta 'btquantr vault init' primero."
            )
        raw = self._path.read_bytes()
        salt = raw[:_SALT_LEN]
        nonce = raw[_SALT_LEN:_SALT_LEN + _NONCE_LEN]
        ciphertext = raw[_SALT_LEN + _NONCE_LEN:]
        key = self._derive_key(salt, master_password)
        aesgcm = AESGCM(key)
        try:
            plaintext = aesgcm.decrypt(nonce, ciphertext, None)
        except (InvalidTag, Exception) as exc:
            raise VaultError(
                f"Contraseña incorrecta o vault corrupto: {exc}"
            ) from exc
        return json.loads(plaintext)


# ── Helper de integración ─────────────────────────────────────────────────────

def vault_or_env(name: str, master_password: Optional[str] = None) -> Optional[str]:
    """Lee una credencial del vault si existe; si no, de os.environ.

    Args:
        name: nombre de la clave (p. ej. "HL_PRIVATE_KEY").
        master_password: contraseña maestra del vault (puede ser None).

    Returns:
        El valor del vault, o el valor de la variable de entorno, o None.
    """
    vault_path = os.environ.get("BTQUANTR_VAULT_PATH", _DEFAULT_VAULT_PATH)
    v = CredentialVault(vault_path=vault_path)
    if v.exists() and master_password is not None:
        try:
            val = v.get(name, master_password)
            if val is not None:
                return val
        except VaultError:
            pass
    return os.environ.get(name)
