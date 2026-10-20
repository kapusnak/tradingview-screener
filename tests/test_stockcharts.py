from __future__ import annotations

import struct
from urllib.parse import parse_qs, urlparse

from src.stockcharts import (
    CHARTS,
    MIN_PIXEL_HEIGHT,
    MIN_PIXEL_WIDTH,
    PNG_MAGIC,
    REQUEST_HEIGHT,
    REQUEST_WIDTH,
    ChartSpec,
    _validate_png,
    chart_image_url,
    png_dimensions,
)


def _png(width: int, height: int, extra: bytes = b"") -> bytes:
    ihdr = struct.pack(">II", width, height)
    return PNG_MAGIC + b"\x00\x00\x00\rIHDR" + ihdr + extra.ljust(16, b"\x00")


def test_charts_are_nasi_and_vix_permalinks() -> None:
    assert [c.symbol for c in CHARTS] == ["$NASI", "$VIX"]
    assert CHARTS[0].permalink_id == "p90909166991"
    assert CHARTS[1].permalink_id == "p04839659995"
    assert CHARTS[0].caption == "$NASI"
    assert CHARTS[1].caption == "$VIX"
    assert CHARTS[1].extra_params["yr"] == "1"


def test_image_url_requests_max_size_and_permalink() -> None:
    spec = CHARTS[0]
    url = chart_image_url(spec, cache_bust_ms=123)
    parsed = urlparse(url)
    assert parsed.path == "/c-sc/sc"
    q = parse_qs(parsed.query)
    assert q["s"] == ["$NASI"]
    assert q["i"] == ["p90909166991"]
    assert q["width"] == [str(REQUEST_WIDTH)]
    assert q["height"] == [str(REQUEST_HEIGHT)]
    assert REQUEST_WIDTH == 2500
    assert REQUEST_HEIGHT == 2000
    assert q["r"] == ["123"]


def test_vix_url_keeps_saved_range() -> None:
    q = parse_qs(urlparse(chart_image_url(CHARTS[1], cache_bust_ms=1)).query)
    assert q["p"] == ["D"]
    assert q["yr"] == ["1"]
    assert q["mn"] == ["0"]
    assert q["dy"] == ["0"]
    assert q["width"] == ["2500"]
    assert q["height"] == ["2000"]


def test_png_dimensions_and_high_res_floor() -> None:
    data = _png(1750, 2000) + (b"x" * 20_000)
    assert png_dimensions(data) == (1750, 2000)
    spec = ChartSpec("$NASI", "p1", "$NASI", "nasi.png")
    assert _validate_png(data, spec) == (1750, 2000)


def test_validate_png_rejects_small_thumbnail() -> None:
    spec = ChartSpec("$NASI", "p1", "$NASI", "nasi.png")
    data = _png(1050, 811) + (b"x" * 20_000)
    try:
        _validate_png(data, spec)
        assert False, "expected ValueError"
    except ValueError as e:
        assert str(MIN_PIXEL_WIDTH) in str(e)
        assert str(MIN_PIXEL_HEIGHT) in str(e)
