#!/usr/bin/env python3
"""
DragonCP AppSettings Model
Key-value settings store in SQLite for dynamic configuration
"""

from typing import Optional


class AppSettings:
    """Simple key-value settings store in SQLite."""
    
    def __init__(self, db_manager):
        self.db = db_manager

    def get(self, key: str, default: Optional[str] = None) -> Optional[str]:
        """Get setting value by key"""
        with self.db.get_connection() as conn:
            row = conn.execute('SELECT value FROM app_settings WHERE key = ?', (key,)).fetchone()
            return (row[0] if row else default)

    def set(self, key: str, value: str) -> None:
        """Set setting value"""
        with self.db.get_connection() as conn:
            conn.execute('''
                INSERT INTO app_settings (key, value, updated_at) VALUES (?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = CURRENT_TIMESTAMP
            ''', (key, value))
            conn.commit()

    def get_bool(self, key: str, default: bool = False) -> bool:
        """Get boolean setting value"""
        val = self.get(key)
        if val is None:
            return default
        return str(val).lower() in ('1', 'true', 'yes', 'on')

    def set_bool(self, key: str, value: bool) -> None:
        """Set boolean setting value"""
        self.set(key, 'true' if value else 'false')

