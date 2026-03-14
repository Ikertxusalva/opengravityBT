"""BTQUANTR Security — Defensa en Profundidad (Capas 1-3 + 6)."""
from btquantr.security.anti_injection import TextSanitizer, NumericSanitizer, ContextSanitizer
from btquantr.security.output_validation import ValidationRule, AgentOutputValidator
from btquantr.security.hard_limits import HardLimits, TradeEnforcer, SecurityMonitor
from btquantr.security.rate_limiter import ClaudeRateLimiter
from btquantr.security.credential_vault import CredentialVault, VaultError, vault_or_env
from btquantr.security.order_signer import OrderSigner
from btquantr.security.circuit_breakers import (
    DailyLossLimit, WeeklyLossLimit, MaxDrawdownLimit, MaxPositions,
    CircuitBreakerManager,
)

__all__ = [
    "TextSanitizer", "NumericSanitizer", "ContextSanitizer",
    "ValidationRule", "AgentOutputValidator",
    "HardLimits", "TradeEnforcer", "SecurityMonitor",
    "ClaudeRateLimiter",
    "CredentialVault", "VaultError", "vault_or_env",
    "OrderSigner",
    "DailyLossLimit", "WeeklyLossLimit", "MaxDrawdownLimit", "MaxPositions",
    "CircuitBreakerManager",
]
