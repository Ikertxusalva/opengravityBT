"""Tick data sources para BTQUANTR."""
from .base import BaseTickSource, TICK_COLUMNS
from .hl_websocket import HLWebSocketTickSource
from .hl_s3 import HLS3TickSource
from .dukascopy import DukascopyTickSource
from .tardis_source import TardisTickSource

__all__ = [
    "BaseTickSource", "TICK_COLUMNS",
    "HLWebSocketTickSource", "HLS3TickSource",
    "DukascopyTickSource", "TardisTickSource",
]
