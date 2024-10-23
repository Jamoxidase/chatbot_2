import json
import os
from typing import Dict, Any, Optional
import sqlite3
from pathlib import Path

class SequenceCache:
    def __init__(self):
        # In-memory cache
        self._memory_cache: Dict[str, Any] = {}
        
        # Get the directory where the script is located
        script_dir = Path(__file__).parent
        
        # Set up database file in the same directory as the script
        self.db_path = script_dir / 'sequence_cache.db'
        
        # Initialize the SQLite database
        self._init_db()
        
        # Load any existing cache into memory
        self.load_cache()

    def _init_db(self):
        """Initialize SQLite database with proper schema"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS sequences (
                    sequence_id TEXT PRIMARY KEY,
                    sequence_data TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            # Create an index for faster lookups
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_sequence_id ON sequences(sequence_id)')
            conn.commit()

    def add_sequence(self, sequence_id: str, sequence_data: Any):
        """Add sequence to both memory cache and persistent storage"""
        # Add to memory cache
        self._memory_cache[sequence_id] = sequence_data
        
        # Add to SQLite database
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                'INSERT OR REPLACE INTO sequences (sequence_id, sequence_data) VALUES (?, ?)',
                (sequence_id, json.dumps(sequence_data))
            )
            conn.commit()

    def get_sequence(self, sequence_id: str) -> Optional[Any]:
        """
        Get sequence from cache, trying memory first then database
        Returns None if sequence is not found in either location
        """
        # First try memory cache
        if sequence_id in self._memory_cache:
            return self._memory_cache[sequence_id]
        
        # If not in memory, try database
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT sequence_data FROM sequences WHERE sequence_id = ?', (sequence_id,))
            result = cursor.fetchone()
            
            if result:
                # Found in database, load into memory cache and return
                sequence_data = json.loads(result[0])
                self._memory_cache[sequence_id] = sequence_data
                return sequence_data
                
        return None

    def clear(self):
        """Clear both memory cache and persistent storage"""
        self._memory_cache.clear()
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('DELETE FROM sequences')
            conn.commit()

    def load_cache(self):
        """Load frequently accessed items from database into memory cache"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            # You can modify this query to load only recent or frequently accessed items
            cursor.execute('SELECT sequence_id, sequence_data FROM sequences')
            for sequence_id, sequence_data in cursor.fetchall():
                self._memory_cache[sequence_id] = json.loads(sequence_data)

    def cleanup_old_entries(self, days: int = 30):
        """Remove entries older than specified days"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                'DELETE FROM sequences WHERE created_at < datetime("now", "-? days")',
                (days,)
            )
            conn.commit()

    def get_cache_size(self) -> Dict[str, int]:
        """Return the size of both memory and persistent cache"""
        return {
            'memory_entries': len(self._memory_cache),
            'persistent_entries': self._count_persistent_entries()
        }

    def _count_persistent_entries(self) -> int:
        """Count entries in the persistent storage"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT COUNT(*) FROM sequences')
            return cursor.fetchone()[0]