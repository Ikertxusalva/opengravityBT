"""Funding Rate Scanner para HyperLiquid.

Obtiene funding rates de todos los crypto perps y activos HIP3 (xyz:/cash:)
en una sola llamada a metaAndAssetCtxs. Diseño inspirado en MoonDev,
usando directamente la API pública de HyperLiquid (sin clave).

Uso:
    btquantr data funding-scanner           # muestra tabla una vez
    btquantr data funding-scanner --loop    # repite cada 5 minutos
"""
from __future__ import annotations

import time
import logging
from typing import Any

import pandas as pd

from btquantr.data.sources.hyperliquid import HyperLiquidSource

log = logging.getLogger("FundingScanner")

# ─── Constantes ───────────────────────────────────────────────────────────────

LOOP_INTERVAL_SECONDS: int = 300       # 5 minutos entre iteraciones
MIN_OI_VALUE: float = 5_000_000        # $5M mínimo OI para filtrar ruido
ALERT_THRESHOLD_ANNUALIZED: float = 100.0  # |annualized %| > 100 → alerta

_HOURS_PER_YEAR = 24 * 365             # 8760


def _is_hip3(name: str) -> bool:
    return name.startswith("xyz:") or name.startswith("cash:")


# ─── FundingScanner ───────────────────────────────────────────────────────────

class FundingScanner:
    """Escanea funding rates de HyperLiquid en una sola llamada API."""

    def __init__(self, hl_source: HyperLiquidSource | None = None):
        self._hl = hl_source or HyperLiquidSource()
        self._meta_cache: dict | None = None

    # ── Acceso datos ────────────────────────────────────────────────────────

    def _get_meta_ctxs(self) -> dict:
        """Llama metaAndAssetCtxs una sola vez y cachea el resultado."""
        if self._meta_cache is None:
            self._meta_cache = self._hl.get_meta_and_asset_ctxs()
        return self._meta_cache

    def _invalidate_cache(self) -> None:
        self._meta_cache = None

    def _build_rows(self, only_hip3: bool) -> list[dict]:
        data = self._get_meta_ctxs()
        universe = data.get("meta", {}).get("universe", [])
        ctxs = data.get("ctxs", [])
        rows = []
        for asset, ctx in zip(universe, ctxs):
            name: str = asset.get("name", "")
            if bool(_is_hip3(name)) != only_hip3:
                continue
            try:
                rate_decimal = float(ctx.get("funding", 0))
                mark_px = float(ctx.get("markPx", 0))
                oi_units = float(ctx.get("openInterest", 0))
                rate_pct = rate_decimal * 100
                annualized_pct = rate_pct * _HOURS_PER_YEAR
                oi_usd = oi_units * mark_px
                rows.append({
                    "symbol": name,
                    "rate_pct": rate_pct,
                    "annualized_pct": annualized_pct,
                    "mark_price": mark_px,
                    "open_interest": oi_usd,
                })
            except (ValueError, TypeError) as e:
                log.debug("Skipping %s: %s", name, e)
        return rows

    # ── Fuentes públicas ────────────────────────────────────────────────────

    def fetch_crypto_funding(self) -> list[dict]:
        """Funding rates de todos los crypto perps (excluye xyz:/cash:)."""
        return self._build_rows(only_hip3=False)

    def fetch_hip3_funding(self) -> list[dict]:
        """Funding rates de activos HIP3 tokenizados (xyz: y cash:)."""
        return self._build_rows(only_hip3=True)

    # ── Parsing / transformación ────────────────────────────────────────────

    def parse_rates_to_df(self, data: list[dict] | dict, source_label: str) -> pd.DataFrame:
        """Convierte lista de dicts (o dict de {symbol: info}) a DataFrame con columna source."""
        if not data:
            return pd.DataFrame()
        if isinstance(data, dict):
            rows = [{"symbol": sym, **info} for sym, info in data.items()]
            df = pd.DataFrame(rows)
        else:
            df = pd.DataFrame(data)
        df["source"] = source_label
        return df

    def _standardize_df(self, df: pd.DataFrame) -> pd.DataFrame:
        """Renombra columnas internas a nombres legibles para display."""
        rename_map = {
            "coin": "Symbol",
            "symbol": "Symbol",
            "rate_pct": "Rate %",
            "annualized_pct": "Annualized %",
            "mark_price": "Mark Price",
            "price": "Mark Price",
            "open_interest": "OI Value",
            "oi": "OI Value",
        }
        df = df.rename(columns={k: v for k, v in rename_map.items() if k in df.columns})
        for col in ("Rate %", "Annualized %"):
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")
        return df

    # ── Helpers de filtrado/ordenamiento ───────────────────────────────────

    def _filter_by_oi(self, df: pd.DataFrame) -> pd.DataFrame:
        """Filtra filas con OI Value < MIN_OI_VALUE."""
        oi_col = "OI Value" if "OI Value" in df.columns else "open_interest"
        return df[df[oi_col] >= MIN_OI_VALUE].copy()

    def _get_top_n(self, df: pd.DataFrame, n: int = 30) -> pd.DataFrame:
        """Top N por Rate % descendente."""
        rate_col = "Rate %" if "Rate %" in df.columns else "rate_pct"
        return df.sort_values(rate_col, ascending=False).head(n)

    def _get_bottom_n(self, df: pd.DataFrame, n: int = 30) -> pd.DataFrame:
        """Bottom N por Rate % ascendente (más negativos primero)."""
        rate_col = "Rate %" if "Rate %" in df.columns else "rate_pct"
        return df.sort_values(rate_col, ascending=True).head(n)

    def _add_alert_flags(self, df: pd.DataFrame) -> pd.DataFrame:
        """Añade columna 'alert' (bool) cuando |Annualized %| > ALERT_THRESHOLD_ANNUALIZED."""
        ann_col = "Annualized %" if "Annualized %" in df.columns else "annualized_pct"
        df = df.copy()
        df["alert"] = df[ann_col].abs() > ALERT_THRESHOLD_ANNUALIZED
        return df

    # ── Display ─────────────────────────────────────────────────────────────

    def build_rich_table(self, df: pd.DataFrame, title: str) -> Any:
        """Crea una Rich Table a partir del DataFrame estandarizado."""
        from rich.table import Table

        t = Table(title=title, show_lines=False, highlight=True)
        t.add_column("Symbol",       style="bold cyan",  no_wrap=True)
        t.add_column("Rate %",       style="white",      justify="right")
        t.add_column("Annualized %", style="white",      justify="right")
        t.add_column("Mark Price",   style="dim",        justify="right")
        t.add_column("OI (USD)",     style="dim",        justify="right")
        t.add_column("",             style="yellow",     width=2)   # alerta

        df_std = self._standardize_df(df.copy())
        df_std = self._filter_by_oi(df_std)
        df_std = self._add_alert_flags(df_std)

        rate_col = "Rate %"
        df_std = df_std.sort_values(rate_col, ascending=False)

        for _, row in df_std.iterrows():
            rate = row.get("Rate %", 0) or 0
            ann = row.get("Annualized %", 0) or 0
            alert = row.get("alert", False)

            rate_style = "[green]" if rate > 0 else "[red]"
            ann_style  = "[green]" if ann  > 0 else "[red]"
            alert_str  = "⚠" if alert else ""

            t.add_row(
                str(row.get("Symbol", "")),
                f"{rate_style}{rate:+.4f}%[/]",
                f"{ann_style}{ann:+.1f}%[/]",
                f"{row.get('Mark Price', 0):,.2f}",
                f"${row.get('OI Value', 0):,.0f}",
                alert_str,
            )
        return t

    def run_once(self) -> None:
        """Ejecuta el scanner una vez y muestra las tablas en consola."""
        from btquantr.ui.theme import console

        self._invalidate_cache()

        crypto_rows = self.fetch_crypto_funding()
        hip3_rows   = self.fetch_hip3_funding()

        crypto_df = self.parse_rates_to_df(crypto_rows, "crypto")
        hip3_df   = self.parse_rates_to_df(hip3_rows,   "hip3")

        if not crypto_df.empty:
            table = self.build_rich_table(crypto_df, "🔵 Crypto Perps — Funding Rate Scanner")
            console.print(table)

        if not hip3_df.empty:
            table = self.build_rich_table(hip3_df, "🟡 HIP3 Tokenized Assets — Funding Rate Scanner")
            console.print(table)

        # Resumen de alertas
        all_df = pd.concat([crypto_df, hip3_df], ignore_index=True) if not crypto_df.empty or not hip3_df.empty else pd.DataFrame()
        if not all_df.empty:
            all_std = self._standardize_df(all_df)
            all_std = self._add_alert_flags(all_std)
            alerts = all_std[all_std["alert"]]
            if not alerts.empty:
                console.print(f"\n[bold yellow]⚠  {len(alerts)} activo(s) con |Annualized| > {ALERT_THRESHOLD_ANNUALIZED:.0f}%:[/bold yellow]")
                for _, row in alerts.iterrows():
                    ann = row.get("Annualized %", 0)
                    direction = "LONG premium" if ann > 0 else "SHORT premium"
                    console.print(
                        f"  [bold cyan]{row.get('Symbol', '')}[/bold cyan] "
                        f"[yellow]{ann:+.1f}%[/yellow] annualized — {direction}"
                    )

    def run_loop(self) -> None:
        """Ejecuta run_once en loop cada LOOP_INTERVAL_SECONDS."""
        from btquantr.ui.theme import console
        console.print(f"[muted]Loop activo — actualizando cada {LOOP_INTERVAL_SECONDS}s. Ctrl+C para detener.[/muted]")
        while True:
            self.run_once()
            console.print(f"[muted]Próxima actualización en {LOOP_INTERVAL_SECONDS}s...[/muted]")
            time.sleep(LOOP_INTERVAL_SECONDS)
