"""Fetch morning chart PNGs from StockCharts and Finviz (no browser screenshot).

StockCharts: saved SharpCharts permalinks (``id=p…`` on /sc3/ui/) render as
``/c-sc/sc?i=p…`` images. Finviz: the quote-page daily candle chart is served
from ``charts2-node.finviz.com/chart`` with explicit ``w``/``h``.

A browser-like User-Agent is required; StockCharts returns 404 otherwise.
"""

from __future__ import annotations

import logging
import struct
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from typing import Mapping

logger = logging.getLogger(__name__)

STOCKCHARTS_IMAGE_BASE = "https://stockcharts.com/c-sc/sc"
FINVIZ_CHART_BASE = "https://charts2-node.finviz.com/chart"
PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
# Real chart PNGs are tens of KB; overlay stubs / error pages are tiny.
MIN_PNG_BYTES = 8_000
# Request the SharpCharts documented maximum; /c-sc/sc currently caps at 1750×2000.
REQUEST_WIDTH = 2500
REQUEST_HEIGHT = 2000
# Finviz node renderer rejects > ~2e6 pixels (400). 2000×1000 is the max width that works.
FINVIZ_REQUEST_WIDTH = 2000
FINVIZ_REQUEST_HEIGHT = 1000
# Fail rather than send a compressed/default thumbnail-sized chart.
MIN_PIXEL_WIDTH = 1600
MIN_PIXEL_HEIGHT = 1600
FINVIZ_MIN_WIDTH = 1800
FINVIZ_MIN_HEIGHT = 800

_BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/128.0.0.0 Safari/537.36"
    ),
    "Accept": "image/png,image/*,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

# Quote-page overlays from FinvizSettings.TA on /quote.ashx?t=QQQ&p=d
_FINVIZ_DAILY_OVERLAYS: tuple[tuple[str, str, str], ...] = (
    ("sma", "20", "DC32B363"),
    ("sma", "50", "FF8F33C6"),
    ("sma", "200", "DCB3326D"),
    ("patterns", "", "000"),
)


@dataclass(frozen=True)
class ChartSpec:
    """One chart to fetch as a PNG (StockCharts permalink or Finviz quote chart)."""

    symbol: str
    caption: str
    filename: str
    source: str = "stockcharts"
    permalink_id: str = ""
    extra_params: Mapping[str, str] = field(default_factory=dict)
    ui_url: str = ""
    min_width: int = MIN_PIXEL_WIDTH
    min_height: int = MIN_PIXEL_HEIGHT


# Order is the Telegram album order: $NASI, $VIX, QQQ.
CHARTS: tuple[ChartSpec, ...] = (
    ChartSpec(
        symbol="$NASI",
        caption="$NASI",
        filename="NASI.png",
        source="stockcharts",
        permalink_id="p90909166991",
        extra_params={},
        ui_url="https://stockcharts.com/sc3/ui/?s=%24NASI&id=p90909166991",
    ),
    ChartSpec(
        symbol="$VIX",
        caption="$VIX",
        filename="VIX.png",
        source="stockcharts",
        permalink_id="p04839659995",
        extra_params={"p": "D", "yr": "1", "mn": "0", "dy": "0"},
        ui_url="https://stockcharts.com/sc3/ui/?s=%24VIX&p=d&yr=1&mn=0&dy=0&id=p04839659995",
    ),
    ChartSpec(
        symbol="QQQ",
        caption="QQQ",
        filename="QQQ.png",
        source="finviz",
        ui_url="https://finviz.com/quote.ashx?t=QQQ&p=d",
        min_width=FINVIZ_MIN_WIDTH,
        min_height=FINVIZ_MIN_HEIGHT,
    ),
)


def chart_image_url(spec: ChartSpec, *, cache_bust_ms: int | None = None) -> str:
    """Build the PNG URL for ``spec`` (StockCharts ``/c-sc/sc`` or Finviz node chart)."""
    if spec.source == "finviz":
        return _finviz_image_url(spec, cache_bust_ms=cache_bust_ms)
    params: dict[str, str] = {"s": spec.symbol}
    params.update(spec.extra_params)
    params["i"] = spec.permalink_id
    params["width"] = str(REQUEST_WIDTH)
    params["height"] = str(REQUEST_HEIGHT)
    if cache_bust_ms is None:
        cache_bust_ms = int(time.time() * 1000)
    params["r"] = str(cache_bust_ms)
    return f"{STOCKCHARTS_IMAGE_BASE}?{urllib.parse.urlencode(params)}"


def _finviz_image_url(spec: ChartSpec, *, cache_bust_ms: int | None = None) -> str:
    """Daily candle chart matching the public Finviz quote page (SMA 20/50/200)."""
    if cache_bust_ms is None:
        cache_bust_ms = int(time.time() * 1000)
    params: list[tuple[str, str]] = [
        ("w", str(FINVIZ_REQUEST_WIDTH)),
        ("h", str(FINVIZ_REQUEST_HEIGHT)),
        ("bw", "2"),
        ("bm", "1"),
        ("bb", "1"),
        ("t", spec.symbol),
        ("tf", "d"),
        ("s", "linear"),
        ("pm", "0"),
        ("am", "0"),
        ("ct", "candle_stick"),
    ]
    for i, (overlay, period, color) in enumerate(_FINVIZ_DAILY_OVERLAYS):
        params.append((f"o[{i}][ot]", overlay))
        params.append((f"o[{i}][op]", period))
        params.append((f"o[{i}][oc]", color))
    params.append(("_", str(cache_bust_ms)))
    return f"{FINVIZ_CHART_BASE}?{urllib.parse.urlencode(params)}"


def png_dimensions(data: bytes) -> tuple[int, int]:
    """Return ``(width, height)`` from a PNG IHDR; raise if not a PNG."""
    if not data.startswith(PNG_MAGIC) or len(data) < 24:
        raise ValueError("not a PNG")
    width, height = struct.unpack(">II", data[16:24])
    return int(width), int(height)


def _request_headers(spec: ChartSpec) -> dict[str, str]:
    headers = dict(_BROWSER_HEADERS)
    if spec.source == "finviz":
        headers["Referer"] = spec.ui_url or "https://finviz.com/"
    else:
        headers["Referer"] = "https://stockcharts.com/"
    return headers


def _validate_png(data: bytes, spec: ChartSpec) -> tuple[int, int]:
    if not data.startswith(PNG_MAGIC):
        preview = data[:80].decode("latin-1", errors="replace")
        raise ValueError(
            f"{spec.symbol}: response was not a PNG (got {len(data)} bytes, head={preview!r})"
        )
    if len(data) < MIN_PNG_BYTES:
        raise ValueError(
            f"{spec.symbol}: PNG too small ({len(data)} bytes); refusing possible overlay stub"
        )
    width, height = png_dimensions(data)
    if width < spec.min_width or height < spec.min_height:
        raise ValueError(
            f"{spec.symbol}: PNG {width}x{height} is below the high-res floor "
            f"{spec.min_width}x{spec.min_height}"
        )
    return width, height


def fetch_chart_png(
    spec: ChartSpec,
    *,
    timeout: int = 60,
    retries: int = 3,
    cache_bust_ms: int | None = None,
) -> bytes:
    """GET the chart PNG for ``spec``. Retries transient HTTP/network errors."""
    url = chart_image_url(spec, cache_bust_ms=cache_bust_ms)
    last_error: Exception | None = None
    for attempt in range(1, retries + 1):
        req = urllib.request.Request(url, headers=_request_headers(spec), method="GET")
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                data = resp.read()
            width, height = _validate_png(data, spec)
            logger.info(
                "Fetched %s chart PNG %sx%s (%s bytes) from %s",
                spec.symbol,
                width,
                height,
                len(data),
                spec.source,
            )
            return data
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, ValueError) as e:
            last_error = e
            logger.warning(
                "%s fetch for %s attempt %s/%s failed: %s",
                spec.source,
                spec.symbol,
                attempt,
                retries,
                e,
            )
            if attempt < retries:
                time.sleep(1.5 * attempt)
    assert last_error is not None
    raise last_error


def fetch_all_charts(specs: tuple[ChartSpec, ...] = CHARTS) -> list[tuple[ChartSpec, bytes]]:
    """Fetch every chart; fail the whole run if any image is missing."""
    out: list[tuple[ChartSpec, bytes]] = []
    for spec in specs:
        out.append((spec, fetch_chart_png(spec)))
    return out
