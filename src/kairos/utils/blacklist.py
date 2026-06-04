"""Symbol blacklist — Hermes-controlled symbol bans with expiration."""

import json
import time
from pathlib import Path
from typing import Dict, List, Optional


class Blacklist:
    """Simple JSON-file-backed blacklist with optional expiration times.

    File: ~/.config/kairos/blacklist.json
    """

    def __init__(self, path: Optional[str] = None):
        if path is None:
            config_dir = Path.home() / ".config" / "kairos"
            config_dir.mkdir(parents=True, exist_ok=True)
            path = str(config_dir / "blacklist.json")
        self._path = Path(path)
        self._entries: Dict[str, dict] = self._load()

    def _load(self) -> Dict[str, dict]:
        if not self._path.exists():
            return {}
        try:
            with open(self._path) as f:
                data = json.load(f)
            return data if isinstance(data, dict) else {}
        except (json.JSONDecodeError, OSError):
            return {}

    def _save(self) -> None:
        with open(self._path, "w") as f:
            json.dump(self._entries, f, indent=2, ensure_ascii=False)

    def add(self, symbol: str, reason: str = "", duration_hours: float = 0) -> bool:
        """Blacklist a symbol. duration_hours=0 means permanent.

        Returns False if already blacklisted and not expired.
        """
        normalized = symbol.upper()
        existing = self._entries.get(normalized)
        if existing and (not existing.get("until") or existing["until"] > time.time()):
            return False  # Already active

        entry = {
            "symbol": normalized,
            "reason": reason,
            "added_at": time.time(),
            "until": time.time() + duration_hours * 3600 if duration_hours else 0,
        }
        self._entries[normalized] = entry
        self._save()
        return True

    def remove(self, symbol: str) -> bool:
        """Remove a symbol from blacklist. Returns True if it existed."""
        normalized = symbol.upper()
        if normalized in self._entries:
            del self._entries[normalized]
            self._save()
            return True
        return False

    def is_blocked(self, symbol: str) -> bool:
        """Check if a symbol is currently blacklisted."""
        normalized = symbol.upper()
        entry = self._entries.get(normalized)
        if not entry:
            return False
        until = entry.get("until", 0)
        if until and time.time() > until:
            # Expired — auto-remove
            del self._entries[normalized]
            self._save()
            return False
        return True

    def blocked_symbols(self) -> List[str]:
        """Return list of currently blocked symbols."""
        now = time.time()
        active = []
        expired = []
        for sym, entry in list(self._entries.items()):
            until = entry.get("until", 0)
            if until and now > until:
                expired.append(sym)
            else:
                active.append(sym)
        for sym in expired:
            del self._entries[sym]
        if expired:
            self._save()
        return sorted(active)

    def list_entries(self) -> List[dict]:
        """Return full entry list for display."""
        self.blocked_symbols()  # Clean expired
        now = time.time()
        result = []
        for entry in self._entries.values():
            until = entry.get("until", 0)
            remaining = max(0, until - now) / 3600 if until else None
            result.append(
                {
                    "symbol": entry["symbol"],
                    "reason": entry.get("reason", ""),
                    "permanent": until == 0,
                    "remaining_hours": round(remaining, 1) if remaining is not None else None,
                }
            )
        return sorted(result, key=lambda x: x["symbol"])

    def clear(self) -> int:
        """Clear all entries. Returns count removed."""
        count = len(self._entries)
        self._entries = {}
        self._save()
        return count
