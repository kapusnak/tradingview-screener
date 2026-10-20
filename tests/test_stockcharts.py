from __future__ import annotations

import struct
from urllib.parse import parse_qs, urlparse, unquote

from src.stockcharts import (
    CHARTS,
    FINVIZ_REQUEST_HEIGHT,
    FINVIZ_REQUEST_WIDTH,
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


def test_charts_order_is_nasi_vix_qqq() -> None:
    assert [c.symbol for c in CHARTS] == ["$NASI", "$VIX", "QQQ"]
    assert [c.caption for c in CHARTS] == ["$NASI", "$VIX", "QQQ"]
    assert CHARTS[0].permalink_id == "p90909166991"
    assert CHARTS[1].permalink_id == "p04839659995"
    assert CHARTS[1].extra_params["yr"] == "1"
    assert CHARTS[2].source == "finviz"
    assert CHARTS[2].ui_url == "https://finviz.com/quote.ashx?t=QQQ&p=d"


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


def test_qqq_finviz_url_is_large_daily_candle() -> None:
    url = chart_image_url(CHARTS[2], cache_bust_ms=99)
    parsed = urlparse(url)
    assert parsed.netloc == "charts2-node.finviz.com"
    assert parsed.path == "/chart"
    q = parse_qs(parsed.query)
    assert q["t"] == ["QQQ"]
    assert q["tf"] == ["d"]
    assert q["ct"] == ["candle_stick"]
    assert q["w"] == [str(FINVIZ_REQUEST_WIDTH)]
    assert q["h"] == [str(FINVIZ_REQUEST_HEIGHT)]
    assert FINVIZ_REQUEST_WIDTH == 2000
    assert FINVIZ_REQUEST_HEIGHT == 1000
    decoded = unquote(url)
    assert "o[0][ot]=sma" in decoded
    assert "o[0][op]=20" in decoded
    assert "o[1][op]=50" in decoded
    assert "o[2][op]=200" in decoded


def test_png_dimensions_and_high_res_floor() -> None:
    data = _png(1750, 2000) + (b"x" * 20_000)
    assert png_dimensions(data) == (1750, 2000)
    spec = ChartSpec(symbol="$NASI", caption="$NASI", filename="nasi.png")
    assert _validate_png(data, spec) == (1750, 2000)


def test_validate_png_rejects_small_thumbnail() -> None:
    spec = ChartSpec(symbol="$NASI", caption="$NASI", filename="nasi.png")
    data = _png(1050, 811) + (b"x" * 20_000)
    try:
        _validate_png(data, spec)
        assert False, "expected ValueError"
    except ValueError as e:
        assert str(MIN_PIXEL_WIDTH) in str(e)
        assert str(MIN_PIXEL_HEIGHT) in str(e)


def test_finviz_floor_rejects_quote_page_thumbnail() -> None:
    spec = CHARTS[2]
    data = _png(466, 219) + (b"x" * 20_000)
    try:
        _validate_png(data, spec)
        assert False, "expected ValueError"
    except ValueError as e:
        assert "466x219" in str(e)
