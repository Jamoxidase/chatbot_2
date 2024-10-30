import unittest
from cache import SequenceCache
from tools.cacheCrawl import DBSearchTool
import sqlite3

class TestDBSearchTool(unittest.TestCase):
    def setUp(self):
        """Set up test environment before each test"""
        self.sequence_cache = SequenceCache()
        self.db_tool = DBSearchTool(self.sequence_cache)
        
        # Add some test sequences that match the database schema
        test_sequences = [
            {
                'id': 'URS0000TEST01_9606',
                'data': {
                    'sequence': 'ACGT',
                    'description': 'Test tRNA 1',
                    'genes': ['tRNA-Leu-CAA-4-1']
                },
                'friendly_name': 'tRNA-Leu-CAA-4-1',
                'locations': ['chr1:1234-5678']
            },
            {
                'id': 'URS0000TEST02_9606',
                'data': {
                    'sequence': 'GCTA',
                    'description': 'Test tRNA 2',
                    'genes': ['tRNA-Glu-TTC-14-1']
                },
                'friendly_name': 'tRNA-Glu-TTC-14-1',
                'locations': ['chr2:1234-5678']
            }
        ]
        
        # Connect to DB directly to verify data after adding
        with sqlite3.connect(self.sequence_cache.db_path) as conn:
            print("\nInitial DB state:")
            cursor = conn.cursor()
            cursor.execute('SELECT sequence_id, friendly_name FROM sequences')
            print("Existing records:", cursor.fetchall())
        
        for seq in test_sequences:
            print(f"\nAdding sequence {seq['id']} with friendly_name {seq['friendly_name']}")
            self.sequence_cache.add_sequence(
                sequence_id=seq['id'],
                sequence_data={'sequence': seq['data']['sequence'],
                            'description': seq['data']['description'],
                            'genes': seq['data']['genes']},
                friendly_name=seq['friendly_name']  # Pass friendly_name separately
            )
            
            # Verify after adding
            with sqlite3.connect(self.sequence_cache.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute('SELECT sequence_id, friendly_name FROM sequences WHERE sequence_id = ?', 
                            (seq['id'],))
                result = cursor.fetchone()
                print(f"DB record after adding: {result}")
    def test_sequence_id_query(self):
        """Test searching by sequence ID"""
        query = 'CHECK_DB sequence_id:"URS0000TEST01_9606" operation:"AND"'
        result = self.db_tool.use_db_search_tool(query)
        print("\nSequence ID Query Test:")
        print("Query:", query)
        print("Result:", result)
        self.assertTrue('results' in result)

    def test_friendly_name_query(self):
        """Test searching by friendly name"""
        # First verify the data is in the DB
        with sqlite3.connect(self.sequence_cache.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT sequence_id, friendly_name FROM sequences')
            print("\nAll records before test:", cursor.fetchall())
        
        query = 'CHECK_DB friendly_name:"tRNA-Leu-CAA-4-1" operation:"AND"'
        result = self.db_tool.use_db_search_tool(query)
        print("\nFriendly Name Query Test:")
        print("Query:", query)
        print("Result:", result)
        
        self.assertTrue('results' in result)
        self.assertTrue('tRNA-Leu-CAA-4-1' in str(result['results']))
        result_value = list(result['results'].values())[0]
        self.assertNotEqual(result_value, 'No results found, use GET_TRNA tool to acquire sequence data')

    def test_multiple_queries(self):
        """Test multiple queries separated by NEXT_QUERY"""
        query = '''CHECK_DB sequence_id:"URS0000TEST01_9606" operation:"AND"
        NEXT_QUERY
        friendly_name:"tRNA-Glu-TTC-14-1" operation:"OR"'''
        result = self.db_tool.use_db_search_tool(query)
        print("\nMultiple Queries Test:")
        print("Query:", query)
        print("Result:", result)
        self.assertTrue('results' in result)

    def test_nonexistent_sequence(self):
        """Test searching for a sequence that doesn't exist"""
        query = 'CHECK_DB sequence_id:"URS0000NOTFOUND_9606" operation:"AND"'
        result = self.db_tool.use_db_search_tool(query)
        print("\nNonexistent Sequence Test:")
        print("Query:", query)
        print("Result:", result)
        self.assertTrue('results' in result)

    def test_invalid_query(self):
        """Test handling of invalid query format"""
        query = 'CHECK_DB invalid_field:"something" operation:"AND"'
        result = self.db_tool.use_db_search_tool(query)
        print("\nInvalid Query Test:")
        print("Query:", query)
        print("Result:", result)
        self.assertTrue('results' in result or 'error' in result)

    def tearDown(self):
        """Clean up after each test"""
        self.sequence_cache.clear()

if __name__ == '__main__':
    # Run with more verbose output
    unittest.main(verbosity=2)