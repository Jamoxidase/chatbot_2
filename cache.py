"""
Issues; right now im marking +/- coords as seperate locations...
"""

import json
import os
from typing import Dict, Any, Optional, List, Tuple, Callable, Coroutine, Literal
import sqlite3
from pathlib import Path
import asyncio

UpdateType = Literal['update', 'clear']

class SequenceCache:
    RNACENTRAL_BASE_URL = "https://rnacentral.org/rna/"

    def __init__(self, mapping_file_path: str = './db_mappings/gtrnadb_mappings.tsv'):
        self._memory_cache: Dict[str, Any] = {}
        self.mapping_file_path = mapping_file_path
        self._id_mapping: Dict[str, Tuple[List[str], str]] = {}
        self.db_update_callback: Optional[Callable[[str], Coroutine]] = None
        self.loop = None  # Add this line for event loop

        script_dir = Path(__file__).parent
        self.db_path = script_dir / 'sequence_cache.db'
        
        # Load the ID mapping file
        self._load_id_mapping()
        
        # Initialize the database with new schema (dev)
        self._init_db()

    def set_event_loop(self, loop):
        """Set the event loop to use for callbacks"""
        self.loop = loop

    def set_update_callback(self, callback: Callable[[str, UpdateType], Coroutine]):
        """Set callback for database updates"""
        self.db_update_callback = callback

    def _load_id_mapping(self):
        """Load and parse the GtRNAdb mapping file, grouping multiple locations"""
        location_map: Dict[str, List[str]] = {}
        friendly_names: Dict[str, str] = {}

        with open(self.mapping_file_path, 'r') as f:
            for line in f:
                parts = line.strip().split('\t')
                if len(parts) >= 5:
                    urs_id = parts[0]
                    gtrnadb_full = parts[2]
                    taxid = parts[3]
                    rnacentral_id = f"{urs_id}_{taxid}"
                    friendly_name = parts[-1]

                    # Extract location from GtRNAdb ID
                    location = gtrnadb_full.split(':')[2:]  # Get everything after the second colon
                    location = ':'.join(location)  # Rejoin in case there are more colons

                    # Initialize or append to locations list
                    if rnacentral_id not in location_map:
                        location_map[rnacentral_id] = []
                    location_map[rnacentral_id].append(location)
                    friendly_names[rnacentral_id] = friendly_name

        # Combine locations and friendly names into final mapping
        for rnacentral_id in location_map:
            self._id_mapping[rnacentral_id] = (location_map[rnacentral_id], friendly_names[rnacentral_id])

    def _init_db(self):
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS sequences (
                    sequence_id TEXT PRIMARY KEY,
                    sequence_data TEXT,
                    num_locations INTEGER,
                    locations TEXT,  -- JSON array of locations
                    friendly_name TEXT,
                    rnacentral_link TEXT,
                    trnascan_se_ss TEXT,  -- Secondary structure from tRNAscan-SE
                    sprinzl_pos TEXT,     -- Sprinzl position mapping
                    blocks_file TEXT,     -- Blocks file content
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            # Create indices for faster lookups
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_sequence_id ON sequences(sequence_id)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_friendly_name ON sequences(friendly_name)')
            
            conn.commit()

    def add_sequence(self, sequence_id: str, sequence_data: Any):
        """Add sequence to both memory cache and persistent storage with location information"""
        print("Adding sequence:", sequence_id)
        print("Callback exists:", self.db_update_callback is not None)
        print("Event loop exists:", self.loop is not None)
        
        # Get mapping information if available
        locations, friendly_name = self._id_mapping.get(sequence_id, ([], None))
        
        # Generate RNAcentral link
        rnacentral_link = f"{self.RNACENTRAL_BASE_URL}{sequence_id}"
        
        # Add to memory cache
        self._memory_cache[sequence_id] = sequence_data
        
        # Add to SQLite database with metadata
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                '''INSERT OR REPLACE INTO sequences 
                (sequence_id, sequence_data, num_locations, locations, 
                    friendly_name, rnacentral_link) 
                VALUES (?, ?, ?, ?, ?, ?)''',
                (
                    sequence_id,
                    json.dumps(sequence_data),
                    len(locations),
                    json.dumps(locations),
                    friendly_name,
                    rnacentral_link
                )
            )
            conn.commit()

        if self.db_update_callback and self.loop:
            try:
                print(f"Attempting callback for sequence: {sequence_id}")
                # Create the coroutine
                coro = self.db_update_callback(sequence_id, 'update')
                # Schedule it on the running loop
                future = asyncio.run_coroutine_threadsafe(coro, self.loop)
                
                def callback_done(fut):
                    try:
                        fut.result()  # This ensures exceptions are raised
                        print("Callback completed successfully")
                    except Exception as e:
                        print(f"Callback failed: {str(e)}")
                        import traceback
                        print(f"Traceback: {traceback.format_exc()}")
                
                future.add_done_callback(callback_done)
                
            except Exception as e:
                print(f"Error scheduling callback: {str(e)}")
                import traceback
                print(f"Traceback: {traceback.format_exc()}")
        else:
            print("Callback or loop missing:", {
                "callback": self.db_update_callback is not None,
                "loop": self.loop is not None
            })

    def get_by_rnacentral_id(self, sequence_id: str) -> Optional[Dict[str, Any]]:
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                '''SELECT sequence_data, num_locations, locations, 
                        friendly_name, rnacentral_link,
                        trnascan_se_ss, sprinzl_pos, blocks_file
                FROM sequences WHERE sequence_id = ?''',
                (sequence_id,)
            )
            result = cursor.fetchone()
            if result:
                data = {
                    'sequence_data': json.loads(result[0]),
                    'num_locations': result[1],
                    'locations': json.loads(result[2]) if result[2] else [],
                    'friendly_name': result[3],
                    'rnacentral_link': result[4],
                    'tool_data': {
                        'trnascan_se_ss': json.loads(result[5]) if result[5] else None,
                        'sprinzl_pos': json.loads(result[6]) if result[6] else None,
                        'blocks_file': result[7] if result[7] else None
                    }
                }
                return data
        print(f"Error getting by ID: Sequence not found: {sequence_id}")
        return None

    def _parse_trnascan_output(self, trnascan_output: str) -> Optional[Dict[str, str]]:
        """Parse both sequence and secondary structure from tRNAscan output
        
        Args:
            trnascan_output: Raw tRNAscan output string
            
        Returns:
            Optional[Dict[str, str]]: Dictionary containing 'sequence' and 'structure',
                                    None if parsing fails
        """
        try:
            result = {}
            lines = trnascan_output.strip().split('\n')
            
            for line in lines:
                if line.startswith('Seq: '):
                    result['trnascan_sequence'] = line.replace('Seq: ', '').strip()
                elif line.startswith('Str: ') or line.startswith('>>'):  # Handle both formats
                    result['secondary_structure'] = line.replace('Str: ', '').strip()
                    
            # Only return if we found both sequence and structure
            if 'trnascan_sequence' in result and 'secondary_structure' in result:
                return result
            return None
            
        except Exception as e:
            print(f"Error parsing tRNAscan output: {str(e)}") #debug
            return None
        
    def _parse_sprinzl_output(self, sprinzl_output: str) -> Dict[str, Any]:
        """Parse Sprinzl output into a structured format
        
        Args:
            sprinzl_output: Raw output string from Sprinzl tool
            
        Returns:
            Dictionary containing parsed positions
        """
        # Remove any formatting characters and extra whitespace
        cleaned = sprinzl_output.strip().replace('\n', '').replace('\r', '')
        
        return {
            'positions': cleaned
        }

    def update_tool_data(self, rnacentral_id: str, tool_name: str, data: Any) -> bool:
        """Update tool-specific data for a sequence

        Args:
            rnacentral_id: The RNA central ID
            tool_name: Name of the tool ('trnascan_se_ss', 'sprinzl_pos', or 'blocks_file')
            data: The data to store. For blocks_file, this should be the blocks file content string.
                For other tools, this can be any JSON-serializable data.

        Returns:
            bool: True if update was successful, False otherwise
        """
        allowed_tools = ['trnascan_se_ss', 'sprinzl_pos', 'blocks_file']
        if tool_name not in allowed_tools:
            raise ValueError(f"Unknown tool: {tool_name}")

        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                success = False

                # For blocks_file, store raw string; for other tools, JSON encode
                value = data if tool_name == 'blocks_file' else json.dumps(data)

                # Handle tRNAscan output
                if tool_name == 'trnascan_se_ss':
                    parsed_data = self._parse_trnascan_output(data)
                    if parsed_data:
                        cursor.execute(
                            'SELECT sequence_data FROM sequences WHERE sequence_id = ?',
                            (rnacentral_id,)
                        )
                        result = cursor.fetchone()
                        if result:
                            sequence_data = json.loads(result[0])
                            sequence_data.update({
                                'secondary_structure': parsed_data['secondary_structure'],
                                'trnascan_sequence': parsed_data['trnascan_sequence']
                            })
                            cursor.execute(
                                'UPDATE sequences SET sequence_data = ?, trnascan_se_ss = ? WHERE sequence_id = ?',
                                (json.dumps(sequence_data), value, rnacentral_id)
                            )
                            success = cursor.rowcount > 0

                # Handle Sprinzl output
                elif tool_name == 'sprinzl_pos':
                    parsed_sprinzl_data = self._parse_sprinzl_output(data)
                    cursor.execute(
                        'UPDATE sequences SET sprinzl_pos = ? WHERE sequence_id = ?',
                        (json.dumps(parsed_sprinzl_data), rnacentral_id)
                    )
                    success = cursor.rowcount > 0

                # Handle blocks file
                elif tool_name == 'blocks_file':
                    cursor.execute(
                        'UPDATE sequences SET blocks_file = ? WHERE sequence_id = ?',
                        (value, rnacentral_id)
                    )
                    success = cursor.rowcount > 0

                conn.commit()

                # Single websocket update at the end if successful
                if success and self.db_update_callback and self.loop:
                    try:
                        print(f"Attempting callback for sequence: {rnacentral_id}")
                        coro = self.db_update_callback(rnacentral_id, 'update')
                        future = asyncio.run_coroutine_threadsafe(coro, self.loop)

                        def callback_done(fut):
                            try:
                                fut.result()
                                print("Callback completed successfully")
                            except Exception as e:
                                print(f"Callback failed: {str(e)}")
                                import traceback
                                print(f"Traceback: {traceback.format_exc()}")

                        future.add_done_callback(callback_done)

                    except Exception as e:
                        print(f"Error scheduling callback: {str(e)}")
                        import traceback
                        print(f"Traceback: {traceback.format_exc()}")
                else:
                    print("Callback or loop missing:", {
                        "callback": self.db_update_callback is not None,
                        "loop": self.loop is not None
                    })

                return success

        except Exception as e:
            print(f"Error updating {tool_name} data: {str(e)}")
            return False


    def clear(self):
        """Clear both memory cache and persistent storage"""
        self._memory_cache.clear()
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('DELETE FROM sequences')
            conn.commit()

        # Notify about clear
        if self.db_update_callback:
            asyncio.create_task(self.db_update_callback(None, 'clear'))

    def cleanup_old_entries(self, days: int = 30):
        """Remove entries older than specified days"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                'DELETE FROM sequences WHERE created_at < datetime("now", "-? days")',
                (days,)
            )
            conn.commit()

            # Could add notification here if needed for cleanup events
            # if self.db_update_callback and hasattr(self.db_update_callback, 'cleanup'):
            #     asyncio.create_task(self.db_update_callback.cleanup(days))

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

    def clear(self):
        """Clear both memory cache and persistent storage"""
        self._memory_cache.clear()
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('DELETE FROM sequences')
            conn.commit()

        # Notify about clear with specific update type
        if self.db_update_callback:
            asyncio.create_task(self.db_update_callback(update_type='clear'))


if __name__ == "__main__":
    import tempfile
    import os

    # Mock mapping file with test data
    test_mapping_content = """URS000000002F	GTRNADB	GTRNADB:tRNA-Leu-GAG-1-1:HE616747.1:617025-617106	4950	tRNA	tRNA-Leu-GAG-1-1
URS000000002F	GTRNADB	GTRNADB:tRNA-Leu-GAG-1-1:HE616747.2:617025-617106	4950	tRNA	tRNA-Leu-GAG-1-1
URS00001DA281	GTRNADB	GTRNADB:tRNA-SeC-TCA-1-1:CM000681.1:45981859-45981945	9606	tRNA	tRNA-SeC-TCA-1-1
URS00001DA281	GTRNADB	GTRNADB:tRNA-SeC-TCA-1-1:CM000681.2:45478601-45478687	9606	tRNA	tRNA-SeC-TCA-1-1"""

    # Create temporary mapping file
    with tempfile.NamedTemporaryFile(mode='w', delete=False) as f:
        f.write(test_mapping_content)
        temp_mapping_file = f.name

    try:
        # Initialize cache with test mapping file
        cache = SequenceCache(temp_mapping_file)

        # Test 1: Add and retrieve sequence with multiple locations
        print("\nTest 1: Adding and retrieving sequence with multiple locations")
        test_rnacentral_id = "URS000000002F_4950"
        test_sequence_data = {"sequence": "ACGT", "extra_field": "test"}
        
        cache.add_sequence(test_rnacentral_id, test_sequence_data)
        result = cache.get_by_rnacentral_id(test_rnacentral_id)
        
        assert result is not None, "Failed to retrieve sequence"
        assert result['sequence_data'] == test_sequence_data, "Sequence data mismatch"
        assert result['num_locations'] == 2, "Wrong number of locations"
        assert len(result['locations']) == 2, "Wrong number of locations in list"
        assert "HE616747.1" in result['locations'][0], "Location 1 mismatch"
        assert "HE616747.2" in result['locations'][1], "Location 2 mismatch"
        print("✓ Test 1 passed")

        # Test 2: RNAcentral link generation
        print("\nTest 2: RNAcentral link generation")
        expected_link = f"https://rnacentral.org/rna/{test_rnacentral_id}"
        assert result['rnacentral_link'] == expected_link, "RNAcentral link mismatch"
        print("✓ Test 2 passed")

        # Test 3: Test with sequence having different locations
        print("\nTest 3: Testing different sequence with multiple locations")
        test_rnacentral_id_2 = "URS00001DA281_9606"
        test_sequence_data_2 = {"sequence": "GCCU", "extra_field": "test2"}
        
        cache.add_sequence(test_rnacentral_id_2, test_sequence_data_2)
        result = cache.get_by_rnacentral_id(test_rnacentral_id_2)
        
        assert result['num_locations'] == 2, "Wrong number of locations"
        assert "CM000681.1" in result['locations'][0], "Location 1 mismatch"
        assert "CM000681.2" in result['locations'][1], "Location 2 mismatch"
        print("✓ Test 3 passed")

        # Test 4: Test cache size
        print("\nTest 4: Testing cache size")
        cache_size = cache.get_cache_size()
        assert cache_size['persistent_entries'] == 2, "Wrong number of entries in database"
        assert cache_size['memory_entries'] == 2, "Wrong number of entries in memory cache"
        print("✓ Test 4 passed")

        # Test 5: Test clearing cache
        print("\nTest 5: Testing cache clearing")
        cache.clear()
        cache_size = cache.get_cache_size()
        assert cache_size['persistent_entries'] == 0, "Database not cleared"
        assert cache_size['memory_entries'] == 0, "Memory cache not cleared"
        print("✓ Test 5 passed")

        # Test 6: Test non-existent sequence
        print("\nTest 6: Testing retrieval of non-existent sequence")
        result = cache.get_by_rnacentral_id("URS000000XXXX_1234")
        assert result is None, "Should return None for non-existent sequence"
        print("✓ Test 6 passed")

        print("\nAll tests passed!")

    finally:
        # Cleanup
        os.unlink(temp_mapping_file)  # Remove temporary mapping file
        if os.path.exists('sequence_cache.db'):
            os.unlink('sequence_cache.db')  # Remove test database