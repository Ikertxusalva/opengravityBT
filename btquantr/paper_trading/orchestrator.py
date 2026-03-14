"""PaperOrchestrator — Orchestrator extendido con paper trading y 3 modos."""
from __future__ import annotations
import asyncio, json, logging, time
from concurrent.futures import ThreadPoolExecutor
from typing import Optional

from btquantr.agents.orchestrator import Orchestrator
from btquantr.security.hard_limits import HardLimits
from btquantr.paper_trading.portfolio import PaperPortfolio
from btquantr.config_manager import ConfigManager
from btquantr.engine.strategy_store_factory import get_strategy_store

log = logging.getLogger("BTQUANTRPaperOrch")

DECISIONS_TO_TRADE = ("APPROVE", "APPROVE_REDUCED")


class PaperOrchestrator(Orchestrator):
    """
    Extiende Orchestrator: después de RiskManager, calcula position size
    y ejecuta en PaperPortfolio en vez de exchange real.

    Soporta 3 modos via ConfigManager.get("trading_mode"):
      - "autonomous" : SignalEngine local, $0 operativo
      - "claude"     : debate multi-agente completo (comportamiento original)
      - "hybrid"     : autonomous si confidence >= 60, sino Claude
    """

    def __init__(self, r, circuit_breakers=None, router=None):
        super().__init__(r)
        self.portfolio = PaperPortfolio(r)
        self.config = ConfigManager(r)
        self.circuit_breakers = circuit_breakers
        self.router = router  # ExecutionRouter para STOP_ALL

    def _calc_position_size(self, risk: dict, regime: str) -> dict:
        """
        Half-Kelly inline: size_pct = kelly_fraction × (confidence / 100).
        Cap por régimen desde ConfigManager, con HardLimits como techo absoluto.
        """
        kelly = self.config.get("sizing_kelly_fraction", 0.5)
        confidence = max(0, risk.get("confidence", 50)) / 100  # clamp >= 0
        size_pct = kelly * confidence

        # Cap por régimen (más conservador en BEAR/SIDEWAYS)
        regime_caps = {
            "BULL": self.config.get("regime_bull_max_size", 25.0) / 100,
            "BEAR": self.config.get("regime_bear_max_size", 10.0) / 100,
            "SIDEWAYS": self.config.get("regime_sideways_max_size", 15.0) / 100,
        }
        regime_cap = regime_caps.get(regime, HardLimits.MAX_POSITION_SIZE_PCT / 100)
        absolute_cap = HardLimits.MAX_POSITION_SIZE_PCT / 100  # 0.25 — nunca superar

        return {"size_pct": min(size_pct, regime_cap, absolute_cap), "leverage": 1.0}

    def _maybe_trigger_engineer(self, symbol: str) -> None:
        """Auto-trigger BacktestEngineer si se alcanzó un múltiplo del threshold."""
        try:
            trigger_n = int(self.config.get("backtest_engineer_trigger_trades", 25))
            min_t = int(self.config.get("backtest_engineer_min_trades", 10))
            total = self.portfolio.get_metrics().get("total_trades", 0)
            if total < min_t or total % trigger_n != 0:
                return
            # Evitar doble disparo para el mismo recuento
            last_key = f"backtest_engineer:last_trigger:{symbol}"
            last_count = int(self.r.get(last_key) or 0)
            if last_count == total:
                return
            self.r.set(last_key, total, ex=3600)
            asyncio.create_task(self._run_engineer(symbol))
        except Exception as e:
            log.warning(f"[{symbol}] _maybe_trigger_engineer error: {e}")

    async def _run_engineer(self, symbol: str) -> None:
        """Ejecuta BacktestEngineer en background (no bloquea el ciclo paper)."""
        try:
            from btquantr.agents.backtest_engineer import BacktestEngineer
            eng = BacktestEngineer(self.r)
            loop = asyncio.get_running_loop()
            result = await loop.run_in_executor(None, eng.analyze, symbol)
            if result:
                log.info(
                    f"[{symbol}] BacktestEngineer auto: {result.get('verdict','?')} "
                    f"| {result.get('total_trades', 0)} trades"
                )
        except Exception as e:
            log.error(f"[{symbol}] _run_engineer error: {e}")

    # ─────────────────────────────────────────────────────────────────────────
    # Métodos de señal autónoma
    # ─────────────────────────────────────────────────────────────────────────

    def _get_ohlcv_for_signal(self, symbol: str):
        """Lee OHLCV reciente de Redis (si DataService está corriendo) o None."""
        try:
            import pandas as pd
            raw = self.r.get(f"ohlcv:{symbol}:1h")
            if raw:
                import json as _json
                data = _json.loads(raw)
                return pd.DataFrame(data)
        except Exception:
            pass
        return None

    def _get_autonomous_signal(self, symbol: str, regime: str, ohlcv) -> dict:
        """Genera señal autónoma usando SignalEngine."""
        try:
            from btquantr.engine.signal_engine import SignalEngine
            return SignalEngine().get_signal(symbol, regime, ohlcv)
        except Exception as e:
            log.warning(f"[{symbol}] SignalEngine error: {e}")
            return {
                "action": "HOLD",
                "confidence": 0.0,
                "reason": str(e),
                "strategy_name": None,
                "source": "autonomous",
            }

    def _detect_regime_change(self, symbol: str) -> tuple[bool, str]:
        """Detecta si el régimen HMM cambió desde el último ciclo.

        Lee `regime:{symbol}` (HMM raw), compara con `paper:last_regime:{symbol}`.
        Si cambió, actualiza Redis y retorna (True, nuevo_regime).
        Si no cambió, retorna (False, regime_actual).
        """
        raw = self.r.get(f"regime:{symbol}")
        current_regime = "BULL"
        if raw:
            try:
                current_regime = json.loads(raw).get("regime", "BULL")
            except Exception:
                pass

        last_key = f"paper:last_regime:{symbol}"
        last_regime = self.r.get(last_key)

        if last_regime == current_regime:
            return False, current_regime

        self.r.set(last_key, current_regime)
        return True, current_regime

    def _get_best_strategy(self, symbol: str, regime: str) -> dict | None:
        """Busca la mejor estrategia para symbol×regime en StrategyStore."""
        try:
            store = get_strategy_store()
            return store.get_best(symbol, regime)
        except Exception as e:
            log.warning(f"[{symbol}] _get_best_strategy error: {e}")
            return None

    def _signal_to_risk(self, signal: dict) -> dict:
        """Convierte señal autónoma al formato dict de RiskManager."""
        action_map = {"BUY": "APPROVE", "SELL": "APPROVE", "HOLD": "REJECT"}
        return {
            "decision": action_map.get(signal["action"], "REJECT"),
            "confidence": signal["confidence"],
            "direction": signal["action"],  # BUY|SELL|HOLD
            "reason": signal["reason"],
            "source": "autonomous",
        }

    # ─────────────────────────────────────────────────────────────────────────
    # Debate Claude (flujo original refactorizado como método privado)
    # ─────────────────────────────────────────────────────────────────────────

    async def _run_claude_debate(self, symbol: str, regime: str) -> Optional[dict]:
        """Ejecuta el debate Claude completo (flujo original refactorizado).

        Returns:
            dict con risk + "_technical" key, o dict con "paper_action"="NO_TRADE" si VETO,
            o None si hay error irrecuperable.
        """
        loop = asyncio.get_running_loop()
        executor = ThreadPoolExecutor(max_workers=2)

        # Análisis en paralelo
        technical, sentiment = await asyncio.gather(
            loop.run_in_executor(executor, self.technical.run, symbol),
            loop.run_in_executor(executor, self.sentiment.run, symbol),
        )

        # Debate ciego en paralelo
        bull, bear = await asyncio.gather(
            loop.run_in_executor(executor, self.bull.run, symbol),
            loop.run_in_executor(executor, self.bear.run, symbol),
        )

        # Risk Manager (secuencial — necesita outputs de ambos)
        risk = self.risk_manager.run(symbol)
        decision = risk.get("decision", "VETO")
        log.info(f"[{symbol}] Risk: {decision} — {str(risk.get('reasoning',''))[:60]}")

        if decision not in DECISIONS_TO_TRADE:
            # VETO: cerrar posición abierta si existe
            if symbol in self.portfolio.get_state():
                price = float(self.r.get(f"market:{symbol}:price") or 0)
                if price > 0:
                    self.portfolio.close_position(symbol, price, reason="VETO")
            return {**risk, "paper_action": "NO_TRADE", "size": None, "_veto": True}

        # Adjuntar la señal técnica al dict para que trading_cycle la procese
        return {**risk, "_technical": technical}

    # ─────────────────────────────────────────────────────────────────────────
    # Ciclo principal
    # ─────────────────────────────────────────────────────────────────────────

    async def trading_cycle(self, symbol: str) -> Optional[dict]:
        """
        Ciclo completo: Gates → Señal (según modo) → Risk → Paper Trade.
        Retorna el dict de Risk Manager enriquecido con paper_action y size,
        o None si un Gate bloquea o si la señal es HOLD en modo autonomous.
        """
        # Heartbeat: el dashboard lo usa para saber si el paper loop está vivo
        self.r.set("paper:last_cycle_ts", time.time())

        # Circuit Breakers — verificar antes de cualquier operación
        if self.circuit_breakers is not None:
            metrics = self.portfolio.get_metrics()
            portfolio_for_cb = {
                "total_dd_pct": abs(float(metrics.get("max_dd_pct", 0.0))),
                "daily_loss_pct": float(metrics.get("daily_loss_pct", 0.0)),
                "weekly_loss_pct": float(metrics.get("weekly_loss_pct", 0.0)),
            }
            n_open = len(self.portfolio.get_state())
            cb_result = self.circuit_breakers.check_all(portfolio_for_cb, n_open)
            if not cb_result["allowed"]:
                log.warning(
                    "[%s] trading_cycle BLOCKED by circuit breaker: %s",
                    symbol, cb_result["tripped_by"],
                )
                # STOP_ALL si MaxDrawdown se activó y hay router con conectores reales
                if "MaxDrawdownLimit" in cb_result["tripped_by"] and self.router is not None:
                    log.warning("[%s] MaxDrawdown tripped — ejecutando STOP_ALL", symbol)
                    self.router.stop_all()
                return {"paper_action": "CB_BLOCKED", "tripped_by": cb_result["tripped_by"]}

        # Gates
        if not self._gate1_data_quality(symbol):
            return None
        if not self._gate2_regime(symbol):
            return None

        # Leer régimen para position sizing posterior
        raw_regime = self.r.get(f"regime:{symbol}:interpreted")
        regime_data = json.loads(raw_regime) if raw_regime else {}
        regime = regime_data.get("regime", "BULL")

        # Filtro de calidad: solo BULL/BEAR con estabilidad > 0.6
        raw_hmm = self.r.get(f"regime:{symbol}")
        hmm_data = json.loads(raw_hmm) if raw_hmm else {}
        stability = float(hmm_data.get("stability", 1.0))

        if regime not in ("BULL", "BEAR") or stability <= 0.6:
            log.info(f"[{symbol}] Skipped: {regime} stab={stability:.2f}")
            return None

        # ── Seleccionar modo ──────────────────────────────────────────────────
        mode = self.config.get("trading_mode", "autonomous")

        risk: dict
        side_from_signal: str

        if mode == "autonomous":
            # Gate: sólo actuar si el régimen HMM cambió desde el último ciclo
            regime_changed, current_regime = self._detect_regime_change(symbol)
            if not regime_changed:
                log.debug(f"[{symbol}] Régimen sin cambios ({current_regime}) — skip")
                return None
            regime = current_regime  # usar el regime detectado

            ohlcv = self._get_ohlcv_for_signal(symbol)
            signal = self._get_autonomous_signal(symbol, regime, ohlcv)
            if signal["action"] == "HOLD":
                return None
            risk = self._signal_to_risk(signal)
            # Mapeo: BUY→LONG, SELL→SHORT
            side_from_signal = "LONG" if signal["action"] == "BUY" else "SHORT"

        elif mode == "claude":
            result = await self._run_claude_debate(symbol, regime)
            if result is None:
                return None
            # Si _run_claude_debate retornó VETO path (ya tiene paper_action)
            if result.get("_veto"):
                result.pop("_veto", None)
                return result
            technical = result.pop("_technical", {})
            risk = result
            signal_str = technical.get("signal", "NEUTRAL") if isinstance(technical, dict) else "NEUTRAL"
            if signal_str == "NEUTRAL":
                size = self._calc_position_size(risk, regime)
                return {**risk, "paper_action": "NEUTRAL_SIGNAL", "size": size}
            side_from_signal = "LONG" if signal_str == "LONG" else "SHORT"

        else:  # hybrid
            ohlcv = self._get_ohlcv_for_signal(symbol)
            signal = self._get_autonomous_signal(symbol, regime, ohlcv)
            if signal["confidence"] >= 60:
                if signal["action"] == "HOLD":
                    return None
                risk = self._signal_to_risk(signal)
                side_from_signal = "LONG" if signal["action"] == "BUY" else "SHORT"
            else:
                result = await self._run_claude_debate(symbol, regime)
                if result is None:
                    return None
                if result.get("_veto"):
                    result.pop("_veto", None)
                    return result
                technical = result.pop("_technical", {})
                risk = result
                signal_str = technical.get("signal", "NEUTRAL") if isinstance(technical, dict) else "NEUTRAL"
                if signal_str == "NEUTRAL":
                    size = self._calc_position_size(risk, regime)
                    return {**risk, "paper_action": "NEUTRAL_SIGNAL", "size": size}
                side_from_signal = "LONG" if signal_str == "LONG" else "SHORT"

        # ── Position sizing ───────────────────────────────────────────────────
        size = self._calc_position_size(risk, regime)
        side = side_from_signal

        price = float(self.r.get(f"market:{symbol}:price") or 0)
        if price <= 0:
            log.warning(f"[{symbol}] Sin precio en Redis — skip paper trade")
            return {**risk, "paper_action": "NO_PRICE", "size": size}

        # ── ExecutionRouter (dry_run=True para paper trading) ─────────────────
        router_order: dict | None = None
        if self.router is not None:
            router_order = self.router.send_order(
                symbol=symbol,
                direction=side,
                size=size["size_pct"],
            )
            log.debug(f"[{symbol}] Router: {router_order}")

        # Cerrar posición opuesta si existe
        state = self.portfolio.get_state()
        if symbol in state and state[symbol]["side"] != side:
            self.portfolio.close_position(symbol, price, reason="SIGNAL_REVERSAL")

        # Abrir nueva posición si no hay una del mismo lado
        state = self.portfolio.get_state()
        paper_action = "EXISTING_POSITION"
        if symbol not in state:
            pos = self.portfolio.open_position(
                symbol=symbol,
                side=side,
                size_pct=size["size_pct"],
                leverage=size["leverage"],
                entry_price=price,
                regime=regime,
            )
            paper_action = "OPENED" if pos else "BLOCKED"
            log.info(f"[{symbol}] Paper {side} @ ${price:,.0f} | size: {size['size_pct']*100:.1f}%")

        self._maybe_trigger_engineer(symbol)
        return {**risk, "paper_action": paper_action, "size": size, "router_order": router_order}
