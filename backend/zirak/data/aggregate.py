"""Aggregate candles into a coarser resolution (e.g. 1m -> 15m, 1h -> 4h).

Wallex's `udf/history` only reliably serves 1m / 1h / 1d (docs/wallex-api/market-data.md), so 5m, 15m
and 4h are built here. Buckets are aligned to UTC epoch multiples; a bucket is emitted only when it is
complete in time (its end <= `until`), even if some 1m candles inside it are missing (no trades).
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from zirak.models import RESOLUTION_SECONDS, Candle

# Which stored resolution each derived resolution is built from.
DERIVED_FROM: dict[str, str] = {"5m": "1m", "15m": "1m", "4h": "1h"}


def bucket_start(ts: datetime, seconds: int) -> datetime:
    epoch = int(ts.timestamp())
    return datetime.fromtimestamp(epoch - epoch % seconds, UTC)


def aggregate(candles: list[Candle], resolution: str, until: datetime | None = None) -> list[Candle]:
    """Group `candles` (sorted, any finer resolution) into `resolution` buckets."""
    seconds = RESOLUTION_SECONDS[resolution]
    out: list[Candle] = []
    group: list[Candle] = []
    current: datetime | None = None

    def flush() -> None:
        if not group or current is None:
            return
        if until is not None and current.timestamp() + seconds > until.timestamp():
            return  # bucket not finished yet
        out.append(
            Candle(
                current,
                group[0].open,
                max(c.high for c in group),
                min(c.low for c in group),
                group[-1].close,
                sum((c.volume for c in group), Decimal(0)),
            )
        )

    for c in candles:
        start = bucket_start(c.ts, seconds)
        if start != current:
            flush()
            group, current = [], start
        group.append(c)
    flush()
    return out
