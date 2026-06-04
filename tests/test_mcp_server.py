"""Tests for MCP server tools — all mock-based for speed."""

from unittest.mock import MagicMock, patch

from kairos.mcp_server import check_exit_signals, check_pyramiding, detect_box_pattern, detect_signal, get_market_cycle, scan_symbols


def _make_mock_ohlcv(price: float = 68500.0, n: int = 30, trend: float = 0.0):
    """Build mock OHLCV data for tests."""
    import numpy as np

    timestamps = np.arange(n, dtype=float) * 3_600_000 + 1_700_000_000_000.0
    base_prices = price + np.arange(n) * trend
    opens = base_prices.astype(float) - 50.0
    highs = base_prices.astype(float) + 100.0
    lows = base_prices.astype(float) - 100.0
    closes = base_prices.astype(float)
    volumes = np.full(n, 10_000_000.0, dtype=float)
    return np.column_stack([timestamps, opens, highs, lows, closes, volumes]).tolist()


def _make_mock_exchange(price: float = 68500.0, ohlcv_n: int = 30):
    """Create a mock exchange with working REST methods."""
    ex = MagicMock()
    ex.fetch_ticker.return_value = {"last": price, "quoteVolume": 1e10, "percentage": 2.5}
    ex.fetch_ohlcv.return_value = _make_mock_ohlcv(price, ohlcv_n)
    ex.load_markets.return_value = {
        "BTC/USDT": {"base": "BTC", "quote": "USDT"},
        "ETH/USDT": {"base": "ETH", "quote": "USDT"},
    }
    return ex


class TestMCPServer:
    """Test MCP server tools with mocked exchange."""

    def test_get_market_cycle(self):
        """Test get_market_cycle returns expected fields."""
        mock_ex = _make_mock_exchange()
        with patch("kairos.mcp_server._get_exchange", return_value=MagicMock(exchange=mock_ex)):
            result = get_market_cycle()
        assert result["success"] is True
        assert "cycle" in result
        assert result["cycle"]["phase"] in ["spring", "summer", "autumn", "winter", "unknown"]
        assert "confidence" in result["cycle"]

    def test_get_market_cycle_returns_advice(self):
        """Test get_market_cycle gives actionable advice."""
        mock_ex = _make_mock_exchange()
        with patch("kairos.mcp_server._get_exchange", return_value=MagicMock(exchange=mock_ex)):
            result = get_market_cycle()
        assert "recommendations" in result
        assert len(result["recommendations"]) > 0

    def test_detect_box_pattern(self):
        """Test detect_box_pattern returns box structure."""
        mock_ex = _make_mock_exchange(ohlcv_n=100)
        with patch("kairos.mcp_server._get_exchange", return_value=MagicMock(exchange=mock_ex)):
            result = detect_box_pattern("BTC/USDT", "15m")
        assert result["success"] is True
        assert "box_pattern" in result
        bp = result["box_pattern"]
        assert "status" in bp
        assert "high" in bp or bp.get("detected") is False

    def test_detect_box_pattern_no_data(self):
        """Test detect_box_pattern handles missing data gracefully."""
        mock_ex = _make_mock_exchange()
        mock_ex.fetch_ohlcv.return_value = None
        with patch("kairos.mcp_server._get_exchange", return_value=MagicMock(exchange=mock_ex)):
            result = detect_box_pattern("NOEXIST/USDT", "15m")
        assert result["success"] is False

    def test_scan_symbols(self):
        """Test scan_symbols returns candidates."""
        mock_ex = _make_mock_exchange()
        mock_ex.fetch_ticker.return_value = {
            "last": 68_500.0,
            "quoteVolume": 2.5e10,
            "percentage": 3.2,
        }
        with patch("kairos.mcp_server._get_exchange", return_value=MagicMock(exchange=mock_ex)):
            result = scan_symbols()
        assert result["success"] is True
        assert "candidates" in result
        assert "summary" in result

    def test_scan_symbols_with_formula(self):
        """Test scan_symbols with perfect formula."""
        mock_ex = _make_mock_exchange()
        mock_ex.fetch_ticker.return_value = {
            "last": 142.0,
            "quoteVolume": 3e10,
            "percentage": 5.0,
        }
        with patch("kairos.mcp_server._get_exchange", return_value=MagicMock(exchange=mock_ex)):
            result = scan_symbols(formula="perfect")
        assert result["success"] is True
        for c in result["candidates"]:
            assert "score" in c

    def test_detect_signal(self):
        """Test detect_signal returns signal data."""
        mock_ex = _make_mock_exchange(ohlcv_n=100)
        with patch("kairos.mcp_server._get_exchange", return_value=MagicMock(exchange=mock_ex)):
            result = detect_signal("BTC/USDT")
        assert result["success"] is True
        assert "signal" in result
        assert "detected" in result["signal"]
        assert "direction" in result["signal"]
        assert "entry_price" in result["signal"]

    def test_detect_signal_with_strategy(self):
        """Test detect_signal with explicit strategy."""
        mock_ex = _make_mock_exchange(ohlcv_n=100)
        with patch("kairos.mcp_server._get_exchange", return_value=MagicMock(exchange=mock_ex)):
            result = detect_signal("BTC/USDT", strategy="box_breakout")
        assert result["success"] is True
        assert result["strategy"] == "box_breakout"

    def test_check_pyramiding_no_price(self):
        """Test pyramiding with no price data."""
        mock_ex = _make_mock_exchange()
        mock_ex.fetch_ticker.return_value = None
        with patch("kairos.mcp_server._get_exchange", return_value=MagicMock(exchange=mock_ex)):
            result = check_pyramiding("NOEXIST/USDT")
        assert result["success"] is False

    def test_check_exit_signals_no_price(self):
        """Test exit signals with no price data."""
        mock_ex = _make_mock_exchange()
        mock_ex.fetch_ticker.return_value = None
        with patch("kairos.mcp_server._get_exchange", return_value=MagicMock(exchange=mock_ex)):
            result = check_exit_signals("NOEXIST/USDT")
        assert result["success"] is False

    def test_detect_signal_no_price(self):
        """Test detect_signal with no price data."""
        mock_ex = _make_mock_exchange()
        mock_ex.fetch_ticker.return_value = None
        with patch("kairos.mcp_server._get_exchange", return_value=MagicMock(exchange=mock_ex)):
            result = detect_signal("NOEXIST/USDT")
        assert result["success"] is False

    def test_detect_box_pattern_no_price(self):
        """Test detect_box_pattern when no OHLCV data."""
        mock_ex = _make_mock_exchange()
        mock_ex.fetch_ohlcv.return_value = None
        mock_ex.fetch_ticker.return_value = {"last": 100.0}
        with patch("kairos.mcp_server._get_exchange", return_value=MagicMock(exchange=mock_ex)):
            result = detect_box_pattern("BTC/USDT", "1d")
        assert result["success"] is False  # No OHLCV data

    def test_check_exit_signals_with_data(self):
        """Test exit signals analysis with realistic data."""
        mock_ex = _make_mock_exchange(ohlcv_n=50)
        with patch("kairos.mcp_server._get_exchange", return_value=MagicMock(exchange=mock_ex)):
            result = check_exit_signals("BTC/USDT")
        assert result["success"] is True
        assert "exit_signals" in result
        assert "exit_recommendation" in result

    def test_scan_symbols_fallback_on_no_markets(self):
        """Test scan_symbols when no USDT markets found."""
        mock_ex = _make_mock_exchange()
        mock_ex.load_markets.return_value = {"BTC/BUSD": {}}
        with patch("kairos.mcp_server._get_exchange", return_value=MagicMock(exchange=mock_ex)):
            result = scan_symbols()
        assert result["success"] is True
        assert "candidates" in result
