"""Fetch rendered StockCharts SharpCharts as PNG (no browser screenshot).

Saved chart permalinks on stockcharts.com/sc3/ui/ use ``id=p…``. The same layout
is available as a static image at ``/c-sc/sc`` with ``i=p…`` (and the rest of the
query string). That avoids headless Chrome and ad overlays.

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
PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
# Real SharpCharts PNGs are tens of KB; the "visit stockcharts.com" stub is tiny.
MIN_PNG_BYTES = 8_000
# Request the SharpCharts documented maximum; /c-sc/sc currently caps at 1750×2000.
REQUEST_WIDTH = 2500
REQUEST_HEIGHT = 2000
# Fail rather than send a compressed/default thumbnail-sized chart.
MIN_PIXEL_WIDTH = 1600
MIN_PIXEL_HEIGHT = 1600

_BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/128.0.0.0 Safari/537.36"
    ),
    "Accept": "image/png,image/*,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://stockcharts.com/",
}


@dataclass(frozen=True)
class ChartSpec:
    """One saved SharpCharts layout to fetch as a PNG."""

    symbol: str
    permalink_id: str
    caption: str
    filename: str
    # Extra query params from the saved UI URL (period/range). Empty = use layout defaults.
    extra_params: Mapping[str, str] = field(default_factory=dict)
    ui_url: str = ""


# Saved layouts from the owner (NASI with RSI panel; VIX with Bollinger + VIX:VXV).
CHARTS: tuple[ChartSpec, ...] = (
    ChartSpec(
        symbol="$NASI",
        permalink_id="p90909166991",
        caption="$NASI",
        filename="NASI.png",
        extra_params={},
        ui_url="https://stockcharts.com/sc3/ui/?s=%24NASI&id=p90909166991",
    ),
    ChartSpec(
        symbol="$VIX",
        permalink_id="p04839659995",
        caption="$VIX",
        filename="VIX.png",
        extra_params={"p": "D", "yr": "1", "mn": "0", "dy": "0"},
        ui_url="https://stockcharts.com/sc3/ui/?s=%24VIX&p=d&yr=1&mn=0&dy=0&id=p04839659995",
    ),
)


def chart_image_url(spec: ChartSpec, *, cache_bust_ms: int | None = None) -> str:
    """Build the ``/c-sc/sc`` image URL for a saved chart permalink."""
    params: dict[str, str] = {"s": spec.symbol}
    params.update(spec.extra_params)
    params["i"] = spec.permalink_id
    params["width"] = str(REQUEST_WIDTH)
    params["height"] = str(REQUEST_HEIGHT)
    if cache_bust_ms is None:
        cache_bust_ms = int(time.time() * 1000)
    params["r"] = str(cache_bust_ms)
    return f"{STOCKCHARTS_IMAGE_BASE}?{urllib.parse.urlencode(params)}"


def png_dimensions(data: bytes) -> tuple[int, int]:
    """Return ``(width, height)`` from a PNG IHDR; raise if not a PNG."""
    if not data.startswith(PNG_MAGIC) or len(data) < 24:
        raise ValueError("not a PNG")
    width, height = struct.unpack(">II", data[16:24])
    return int(width), int(height)


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
    if width < MIN_PIXEL_WIDTH or height < MIN_PIXEL_HEIGHT:
        raise ValueError(
            f"{spec.symbol}: PNG {width}x{height} is below the high-res floor "
            f"{MIN_PIXEL_WIDTH}x{MIN_PIXEL_HEIGHT}"
        )
    return width, height


def fetch_chart_png(
    spec: ChartSpec,
    *,
    timeout: int = 60,
    retries: int = 3,
    cache_bust_ms: int | None = None,
) -> bytes:
    """GET the SharpCharts PNG for ``spec``. Retries transient HTTP/network errors."""
    url = chart_image_url(spec, cache_bust_ms=cache_bust_ms)
    last_error: Exception | None = None
    for attempt in range(1, retries + 1):
        req = urllib.request.Request(url, headers=_BROWSER_HEADERS, method="GET")
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                data = resp.read()
            width, height = _validate_png(data, spec)
            logger.info(
                "Fetched %s chart PNG %sx%s (%s bytes) from StockCharts permalink %s",
                spec.symbol,
                width,
                height,
                len(data),
                spec.permalink_id,
            )
            return data
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, ValueError) as e:
            last_error = e
            logger.warning(
                "StockCharts fetch for %s attempt %s/%s failed: %s",
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
