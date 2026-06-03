"""Comprehensive tests for PositionManager."""

import json
import time
from pathlib import Path
from unittest.mock import MagicMock, mock_open, patch

import pytest

from kairos.trades.position import Position, PositionManager, PositionStatus


class TestPositionDataclass:
    """Test Position dataclass."""

    def test_position_defaults(self):
        pos = Position(id="test1", symbol="BTC/USDT", side="long", entry_price=50000.0, amount=0.01, leverage=5)
        assert pos.status == PositionStatus.OPEN
        assert pos.stop_loss is None
        assert pos.take_profit is None
        assert pos.strategy == ""
        assert pos.notes == ""

    def test_position_to_dict(self):
        pos = Position(id="test1", symbol="BTC/USDT", side="long", entry_price=50000.0, amount=0.01, leverage=5)
        d = pos.to_dict()
        assert d["id"] == "test1"
        assert d["symbol"] == "BTC/USDT"
        assert d["status"] == "open"

    def test_position_from_dict(self):
        data = {
            "id": "test1", "symbol": "BTC/USDT", "side": "long",
            "entry_price": 50000.0, "amount": 0.01, "leverage": 5,
            "status": "closed",
        }
        pos = Position.from_dict(data)
        assert pos.status == PositionStatus.CLOSED

    def test_position_status_enum(self):
        assert PositionStatus.OPEN.value == "open"
        assert PositionStatus.CLOSED.value == "closed"
        assert PositionStatus.PARTIAL.value == "partial"


class TestPositionManager:
    """Test PositionManager class."""

    @pytest.fixture
    def mock_position_manager(self, tmp_path):
        """Create a PositionManager with temp file."""
        with patch("kairos.trades.position.get_config_dir", return_value=tmp_path):
            pm = PositionManager()
            return pm

    def test_init_creates_empty_positions(self, mock_position_manager):
        assert mock_position_manager.positions == {}

    def test_open_position(self, mock_position_manager):
        pos = mock_position_manager.open_position(
            symbol="BTC/USDT", side="long", entry_price=50000.0,
            amount=0.01, leverage=5
        )
        assert pos.symbol == "BTC/USDT"
        assert pos.side == "long"
        assert pos.status == PositionStatus.OPEN
        assert len(mock_position_manager.positions) == 1

    def test_open_position_with_strategy(self, mock_position_manager):
        pos = mock_position_manager.open_position(
            symbol="BTC/USDT", side="long", entry_price=50000.0,
            amount=0.01, leverage=5, strategy="breakout", notes="Test note"
        )
        assert pos.strategy == "breakout"
        assert pos.notes == "Test note"

    def test_close_position_long(self, mock_position_manager):
        pos = mock_position_manager.open_position(
            symbol="BTC/USDT", side="long", entry_price=50000.0,
            amount=0.01, leverage=5
        )
        closed = mock_position_manager.close_position(pos.id, exit_price=51000.0)

        assert closed is not None
        assert closed.status == PositionStatus.CLOSED
        assert closed.exit_price == 51000.0
        assert closed.pnl == 10.0  # (51000 - 50000) * 0.01

    def test_close_position_short(self, mock_position_manager):
        pos = mock_position_manager.open_position(
            symbol="BTC/USDT", side="short", entry_price=50000.0,
            amount=0.01, leverage=5
        )
        closed = mock_position_manager.close_position(pos.id, exit_price=49000.0)

        assert closed is not None
        assert closed.pnl == 10.0  # (50000 - 49000) * 0.01

    def test_close_position_with_pnl(self, mock_position_manager):
        pos = mock_position_manager.open_position(
            symbol="BTC/USDT", side="long", entry_price=50000.0,
            amount=0.01, leverage=5
        )
        closed = mock_position_manager.close_position(pos.id, exit_price=51000.0, pnl=15.0)

        assert closed.pnl == 15.0

    def test_close_position_not_found(self, mock_position_manager):
        result = mock_position_manager.close_position("nonexistent", exit_price=50000.0)
        assert result is None

    def test_get_open_positions(self, mock_position_manager):
        mock_position_manager.open_position("BTC/USDT", "long", 50000.0, 0.01, 5)
        mock_position_manager.open_position("ETH/USDT", "long", 3000.0, 0.1, 5)

        open_pos = mock_position_manager.get_open_positions()
        assert len(open_pos) == 2

    def test_get_open_positions_filtered(self, mock_position_manager):
        mock_position_manager.open_position("BTC/USDT", "long", 50000.0, 0.01, 5)
        mock_position_manager.open_position("ETH/USDT", "long", 3000.0, 0.1, 5)

        open_pos = mock_position_manager.get_open_positions(symbol="BTC/USDT")
        assert len(open_pos) == 1
        assert open_pos[0].symbol == "BTC/USDT"

    def test_get_position_history(self, mock_position_manager):
        from unittest.mock import patch as mock_patch
        # Create positions with unique IDs by mocking time
        counter = [1000.0]

        def mock_time_func():
            counter[0] += 1.0
            return counter[0]

        with mock_patch("kairos.trades.position.time.time", side_effect=mock_time_func):
            pos1 = mock_position_manager.open_position("BTC/USDT", "long", 50000.0, 0.01, 5)
            pos2 = mock_position_manager.open_position("BTC/USDT", "long", 51000.0, 0.01, 5)
            mock_position_manager.close_position(pos1.id, 52000.0)
            mock_position_manager.close_position(pos2.id, 50000.0)

        history = mock_position_manager.get_position_history()
        assert len(history) == 2

    def test_get_position_history_filtered(self, mock_position_manager):
        pos1 = mock_position_manager.open_position("BTC/USDT", "long", 50000.0, 0.01, 5)
        mock_position_manager.open_position("ETH/USDT", "long", 3000.0, 0.1, 5)
        mock_position_manager.close_position(pos1.id, 52000.0)

        history = mock_position_manager.get_position_history(symbol="BTC/USDT")
        assert len(history) == 1

    def test_get_position_history_limit(self, mock_position_manager):
        for i in range(10):
            pos = mock_position_manager.open_position(f"SYM{i}/USDT", "long", 100.0, 1.0, 5)
            mock_position_manager.close_position(pos.id, 110.0)

        history = mock_position_manager.get_position_history(limit=5)
        assert len(history) == 5

    def test_get_strategy_stats(self, mock_position_manager):
        from unittest.mock import patch as mock_patch
        counter = [1000.0]

        def mock_time_func():
            counter[0] += 1.0
            return counter[0]

        with mock_patch("kairos.trades.position.time.time", side_effect=mock_time_func):
            pos1 = mock_position_manager.open_position("BTC/USDT", "long", 50000.0, 0.01, 5, strategy="breakout")
            pos2 = mock_position_manager.open_position("BTC/USDT", "long", 51000.0, 0.01, 5, strategy="breakout")
            mock_position_manager.close_position(pos1.id, 52000.0)
            mock_position_manager.close_position(pos2.id, 50000.0)

        stats = mock_position_manager.get_strategy_stats("breakout")
        assert stats["total"] == 2
        assert stats["wins"] == 1
        assert stats["losses"] == 1

    def test_get_strategy_stats_no_positions(self, mock_position_manager):
        stats = mock_position_manager.get_strategy_stats("nonexistent")
        assert stats["total"] == 0
        assert stats["wins"] == 0

    def test_get_strategy_stats_all(self, mock_position_manager):
        pos = mock_position_manager.open_position("BTC/USDT", "long", 50000.0, 0.01, 5, strategy="test")
        mock_position_manager.close_position(pos.id, 52000.0)

        stats = mock_position_manager.get_strategy_stats()
        assert stats["total"] == 1

    def test_save_and_load_positions(self, tmp_path):
        """Test that positions persist across instances."""
        with patch("kairos.trades.position.get_config_dir", return_value=tmp_path):
            pm1 = PositionManager()
            pm1.open_position("BTC/USDT", "long", 50000.0, 0.01, 5)

            pm2 = PositionManager()
            assert len(pm2.positions) == 1

    def test_load_positions_file_not_exists(self, tmp_path):
        """Test loading when file doesn't exist."""
        with patch("kairos.trades.position.get_config_dir", return_value=tmp_path / "nonexistent"):
            pm = PositionManager()
            assert pm.positions == {}

    def test_load_positions_invalid_json(self, tmp_path):
        """Test loading with invalid JSON."""
        positions_file = tmp_path / "positions.json"
        positions_file.write_text("invalid json")

        with patch("kairos.trades.position.get_config_dir", return_value=tmp_path):
            pm = PositionManager()
            assert pm.positions == {}
