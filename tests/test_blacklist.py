"""Tests for Blacklist utility."""

import time

from kairos.utils.blacklist import Blacklist


class TestBlacklist:
    def test_add_and_check(self, tmp_path):
        b = Blacklist(str(tmp_path / "blacklist.json"))
        assert b.add("BTC/USDT:USDT", "noise")
        assert b.is_blocked("BTC/USDT:USDT")
        assert b.is_blocked("btc/usdt:usdt")  # Case insensitive

    def test_remove(self, tmp_path):
        b = Blacklist(str(tmp_path / "blacklist.json"))
        b.add("ETH/USDT:USDT")
        assert b.remove("ETH/USDT:USDT")
        assert not b.is_blocked("ETH/USDT:USDT")

    def test_duplicate_add(self, tmp_path):
        b = Blacklist(str(tmp_path / "blacklist.json"))
        assert b.add("SOL/USDT:USDT")
        assert not b.add("SOL/USDT:USDT")  # Already blocked

    def test_expiration(self, tmp_path):
        b = Blacklist(str(tmp_path / "blacklist.json"))
        b.add("DOGE/USDT:USDT", duration_hours=0.001)  # ~3.6 seconds
        time.sleep(4)
        assert not b.is_blocked("DOGE/USDT:USDT")  # Should be expired

    def test_blocked_symbols(self, tmp_path):
        b = Blacklist(str(tmp_path / "blacklist.json"))
        b.add("BTC/USDT:USDT", "test")
        b.add("ETH/USDT:USDT", "test")
        symbols = b.blocked_symbols()
        assert "BTC/USDT:USDT" in symbols
        assert "ETH/USDT:USDT" in symbols

    def test_clear(self, tmp_path):
        b = Blacklist(str(tmp_path / "blacklist.json"))
        b.add("BTC/USDT:USDT")
        b.add("ETH/USDT:USDT")
        assert b.clear() == 2
        assert b.blocked_symbols() == []

    def test_list_entries(self, tmp_path):
        b = Blacklist(str(tmp_path / "blacklist.json"))
        b.add("BTC/USDT:USDT", "too noisy", duration_hours=0)
        entries = b.list_entries()
        assert len(entries) == 1
        assert entries[0]["symbol"] == "BTC/USDT:USDT"
        assert entries[0]["permanent"] is True

    def test_persistence(self, tmp_path):
        path = str(tmp_path / "blacklist.json")
        b1 = Blacklist(path)
        b1.add("BTC/USDT:USDT", "persist test")
        del b1

        b2 = Blacklist(path)
        assert b2.is_blocked("BTC/USDT:USDT")
