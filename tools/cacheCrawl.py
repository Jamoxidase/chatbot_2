import re
import json
from typing import List, Dict, Any, Optional, Union, Tuple
from pathlib import Path

# Global flag to control search method
USE_DIRECT_DB = False

class DBSearchTool:
    """
    Tool for searching sequence data using either SequenceCache object or direct DB access.
    Supports complex queries with AND/OR operations across multiple fields.
    """
    
    SEARCHABLE_FIELDS = {
        'sequence_id',
        'friendly_name',
        'rnacentral_link',
        'locations',
        'num_locations'
    }

    def __init__(self, sequence_cache, db_path: Optional[str] = None):
        """
        Initialize with a SequenceCache instance and optional db_path
        
        Args:
            sequence_cache: Instance of SequenceCache
            db_path: Optional path to SQLite database (used only if USE_DIRECT_DB is True)
        """
        self.sequence_cache = sequence_cache
        self.db_path = Path(db_path) if db_path else None

    def parse_search_terms(self, claude_response: str) -> List[Dict[str, Any]]:
        """Parse the search terms from Claude's response"""
        queries = []
        
        # Check for and remove the CHECK_DB flag
        if not claude_response.strip().startswith('CHECK_DB'):
            return {"error": "Invalid tool flag. Query must start with CHECK_DB"}
        
        # Remove the CHECK_DB flag from the response
        query_string = claude_response.replace('CHECK_DB', '', 1).strip()
        
        # Split into individual queries if multiple are present
        query_parts = query_string.split('NEXT_QUERY')
        
        for query_part in query_parts:
            if not query_part.strip():
                continue
                
            # Extract field-value pairs and operation
            field_value_pairs = []
            operation = 'AND'  # default operation
            
            # Find all field:value pairs using regex
            pairs = re.findall(r'(\w+):\s*"([^"]+)"', query_part)
            
            for field, value in pairs:
                field = field.lower()
                if field == 'operation':
                    operation = value.upper()
                elif field in self.SEARCHABLE_FIELDS:
                    field_value_pairs.append((field, value))
                else:
                    print(f"Warning: Unsupported search field '{field}' ignored")
            
            if field_value_pairs:  # Only add if we have valid search terms
                queries.append({
                    'terms': field_value_pairs,
                    'operation': operation
                })
        print("DBSearchTool.parse_search_terms - Parsed queries:", queries) # debug
        return queries

    def matches_query(self, sequence_data: Dict[str, Any], query: Dict[str, Any]) -> bool:
        """Check if sequence data matches query terms"""
        operation = query['operation']
        results = []

        for field, value in query['terms']:
            if field == 'sequence_id':
                match = value.lower() in sequence_data.get('sequence_id', '').lower()
            elif field == 'friendly_name':
                match = value.lower() in sequence_data.get('friendly_name', '').lower()
            elif field == 'rnacentral_link':
                match = value.lower() in sequence_data.get('rnacentral_link', '').lower()
            elif field == 'locations':
                locations = sequence_data.get('locations', [])
                match = any(value.lower() in loc.lower() for loc in locations)
            elif field == 'num_locations':
                try:
                    match = len(sequence_data.get('locations', [])) == int(value)
                except ValueError:
                    match = False
            else:
                match = False
            
            results.append(match)

        if operation == 'AND':
            return all(results)
        else:  # OR
            return any(results)

    def search_sequences(self, queries: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Search sequences using SequenceCache"""
        # First check if queries is actually a dict with an error
        if isinstance(queries, dict) and 'error' in queries:
            return queries
            
        all_results = {}
        
        for query in queries:
            matching_sequences = []
            
            # Create query key safely - ensure we're working with lists/tuples
            if isinstance(query['terms'], (list, tuple)):
                query_terms = [term[1] for term in query['terms'] if isinstance(term, (list, tuple))]
                query_key = " AND ".join(query_terms)
            else:
                print(f"Invalid terms format: {query['terms']}")
                continue
                
            try:
                # If searching by sequence_id, use direct lookup
                if any(term[0] == 'sequence_id' for term in query['terms']):
                    sequence_id = next(term[1] for term in query['terms'] if term[0] == 'sequence_id')
                    sequence_data = self.sequence_cache.get_by_rnacentral_id(sequence_id)
                    if sequence_data:
                        matching_sequences.append(sequence_data)
                else:
                    # Search by other fields
                    for field, value in query['terms']:
                        if not isinstance(field, str) or not isinstance(value, str):
                            print(f"Invalid field/value pair: {field}, {value}")
                            continue
                        results = self.sequence_cache.search_by_field(field, value)
                        if results:  # Only extend if we got results
                            matching_sequences.extend(results)
                
                # Format results based on number of matches
                if not matching_sequences:
                    all_results[query_key] = "No results found, use GET_TRNA tool to acquire sequence data"
                elif len(matching_sequences) > 1:
                    all_results[query_key] = "Multiple results found, please ask user for more specificity"
                else:
                    all_results[query_key] = matching_sequences[0]
                    
            except Exception as e:
                print(f"Error processing query: {str(e)}")
                all_results[query_key] = f"Error processing query: {str(e)}"
        
        return all_results

    def use_db_search_tool(self, step: str) -> Dict[str, Any]:
        """Main method to handle tool usage"""
        print("Received step:", step)
        try:
            # Parse queries from Claude's response
            queries = self.parse_search_terms(step)
            
            if not queries:
                return {"error": "No valid search terms provided"}
            
            # Execute search using appropriate method
            results = self.search_sequences(queries)
            return {"results": results}
            
        except Exception as e:
            return {"error": f"Search failed: {str(e)}"}
