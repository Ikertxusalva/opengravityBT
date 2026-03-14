"""PositionSnapshotCollector — posiciones near-liquidation de HyperLiquid en SQLite.

Cada 60 segundos obtiene todas las posiciones de los top N traders en HL,
filtra las que están dentro del 15% de liquidación con valor > $10K y
persiste en SQLite para análisis posterior.
"""
from __future__ import annotations

import logging
import sqlite3
import time
from pathlib import Path
from typing import Optional

log = logging.getLogger("PositionSnapshotCollector")

_CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS position_snapshots (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    ts                  REAL    NOT NULL,
    coin                TEXT    NOT NULL,
    address             TEXT    NOT NULL,
    szi                 REAL    NOT NULL,
    entry_px            REAL    NOT NULL,
    liq_px              REAL    NOT NULL,
    mark_px             REAL    NOT NULL,
    notional            REAL    NOT NULL,
    distance_to_liq_pct REAL    NOT NULL,
    side                TEXT    NOT NULL
)
"""

_INSERT_SQL = """
INSERT INTO position_snapshots
    (ts, coin, address, szi, entry_px, liq_px, mark_px, notional, distance_to_liq_pct, side)
VALUES
    (:ts, :coin, :address, :szi, :entry_px, :liq_px, :mark_px, :notional, :distance_to_liq_pct, :side)
"""


class PositionSnapshotCollector:
    """Colecta y persiste snapshots de posiciones near-liquidation de HyperLiquid.

    Tabla SQLite: position_snapshots
    Columnas: id, ts, coin, address, szi, entry_px, liq_px, mark_px,
              notional, distance_to_liq_pct, side
    """

    DEFAULT_DB = Path("data/position_snapshots.db")

    def __init__(
        self,
        db_path: Optional[Path] = None,
        r=None,
        _hl_source=None,
        distance_threshold_pct: float = 15.0,
        min_notional_usd: float = 10_000,
    ):
        self.db_path = Path(db_path) if db_path is not None else self.DEFAULT_DB
        self.r = r
        self._hl = _hl_source
        self.distance_threshold_pct = distance_threshold_pct
        self.min_notional_usd = min_notional_usd
        self._init_db()

    # ─────────────────────────────────────────────────────────
    # Internas
    # ─────────────────────────────────────────────────────────

    def _hl_or_default(self):
        if self._hl is not None:
            return self._hl
        from btquantr.data.sources.hyperliquid import HyperLiquidSource
        return HyperLiquidSource()

    def _init_db(self) -> None:
        """Crea la tabla si no existe."""
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        con = sqlite3.connect(self.db_path)
        try:
            con.execute(_CREATE_TABLE_SQL)
            con.commit()
        finally:
            con.close()

    # ─────────────────────────────────────────────────────────
    # Pública API
    # ─────────────────────────────────────────────────────────

    def collect_snapshots(self, top_n: int = 100) -> list[dict]:
        """Obtiene posiciones de top_n traders filtradas por threshold.

        Filtra: distance_to_liq_pct <= distance_threshold_pct AND
                notional >= min_notional_usd.

        Retorna lista de dicts con todos los campos de la tabla.
        """
        hl = self._hl_or_default()
        traders = hl.get_leaderboard(top_n=top_n)
        if not traders:
            return []

        now = time.time()
        result: list[dict] = []

        for trader in traders:
            addr = trader.get("address", "")
            if not addr:
                continue

            try:
                state = hl._post({"type": "clearinghouseState", "user": addr})
            except Exception as exc:
                log.warning("clearinghouseState error para %s: %s", addr, exc)
                continue

            if not isinstance(state, dict):
                continue

            for ap in state.get("assetPositions", []):
                pos = ap.get("position", {})
                coin = pos.get("coin", "")
                if not coin:
                    continue

                szi_raw = pos.get("szi", "0")
                szi = float(szi_raw)
                if szi == 0:
                    continue

                liq_px_raw = pos.get("liquidationPx")
                if liq_px_raw is None:
                    continue
                liq_px = float(liq_px_raw)
                if liq_px <= 0:
                    continue

                entry_px = float(pos.get("entryPx", 0) or 0)

                # Obtener mark price por coin
                try:
                    mark_px = hl.get_mark_price(coin)
                except Exception:
                    mark_px = None

                if mark_px is None or mark_px <= 0:
                    continue

                notional = abs(szi) * mark_px
                distance_to_liq_pct = abs(mark_px - liq_px) / mark_px * 100

                # Aplicar filtros
                if distance_to_liq_pct > self.distance_threshold_pct:
                    continue
                if notional < self.min_notional_usd:
                    continue

                result.append({
                    "ts":                  now,
                    "coin":                coin,
                    "address":             addr,
                    "szi":                 szi,
                    "entry_px":            entry_px,
                    "liq_px":              liq_px,
                    "mark_px":             mark_px,
                    "notional":            round(notional, 2),
                    "distance_to_liq_pct": round(distance_to_liq_pct, 4),
                    "side":                "long" if szi > 0 else "short",
                })

        return result

    def save_snapshots(self, snapshots: list[dict]) -> int:
        """Guarda snapshots en SQLite. Retorna número de filas insertadas."""
        if not snapshots:
            return 0
        con = sqlite3.connect(self.db_path)
        try:
            cur = con.executemany(_INSERT_SQL, snapshots)
            con.commit()
            return cur.rowcount
        finally:
            con.close()

    def get_recent_snapshots(
        self, coin: Optional[str] = None, limit: int = 100
    ) -> list[dict]:
        """Lee snapshots recientes de SQLite. Filtra por coin si se indica."""
        con = sqlite3.connect(self.db_path)
        con.row_factory = sqlite3.Row
        try:
            if coin is not None:
                rows = con.execute(
                    "SELECT * FROM position_snapshots WHERE coin = ? "
                    "ORDER BY ts DESC LIMIT ?",
                    (coin, limit),
                ).fetchall()
            else:
                rows = con.execute(
                    "SELECT * FROM position_snapshots ORDER BY ts DESC LIMIT ?",
                    (limit,),
                ).fetchall()
            return [dict(r) for r in rows]
        finally:
            con.close()

    def run_once(self, top_n: int = 100) -> dict:
        """Llama collect_snapshots + save_snapshots.

        Retorna: {"collected": int, "saved": int, "ts": float}
        """
        snapshots = self.collect_snapshots(top_n=top_n)
        saved = self.save_snapshots(snapshots)
        ts = snapshots[0]["ts"] if snapshots else time.time()
        result = {"collected": len(snapshots), "saved": saved, "ts": ts}
        log.info("run_once: %s", result)
        return result

    def run_loop(self, top_n: int = 100, interval_s: int = 60) -> None:
        """Loop cada interval_s segundos."""
        log.info("PositionSnapshotCollector loop iniciado (interval=%ds)", interval_s)
        while True:
            try:
                summary = self.run_once(top_n=top_n)
                log.info("Snapshot: collected=%d saved=%d", summary["collected"], summary["saved"])
            except Exception as exc:
                log.error("run_loop error: %s", exc)
            time.sleep(interval_s)
