import re
import json
from typing import Tuple, Dict, Optional


class BasicAlignmentTool:
    """
    AI generated test tool, not a functioning align tool
    """
    def __init__(self, sequence_cache=None):
        if sequence_cache is None:
            from cache import SequenceCache
            sequence_cache = SequenceCache()


        self.sequence_cache = sequence_cache
        self.gap_penalty = -1
        self.match_score = 1
        self.mismatch_penalty = -2
        
    def create_scoring_matrix(self, seq1: str, seq2: str) -> Tuple[list, list]:
        """
        Create scoring matrix using Needleman-Wunsch algorithm
        """
        rows = len(seq1) + 1
        cols = len(seq2) + 1
        
        # Initialize scoring matrix and traceback matrix
        score_matrix = [[0 for _ in range(cols)] for _ in range(rows)]
        traceback = [['' for _ in range(cols)] for _ in range(rows)]
        
        # Initialize first row and column
        for i in range(rows):
            score_matrix[i][0] = i * self.gap_penalty
            traceback[i][0] = 'up'
        for j in range(cols):
            score_matrix[0][j] = j * self.gap_penalty
            traceback[0][j] = 'left'
            
        # Fill in the matrices
        for i in range(1, rows):
            for j in range(1, cols):
                # Calculate scores for all possible moves
                match = score_matrix[i-1][j-1] + (
                    self.match_score if seq1[i-1] == seq2[j-1] 
                    else self.mismatch_penalty
                )
                delete = score_matrix[i-1][j] + self.gap_penalty
                insert = score_matrix[i][j-1] + self.gap_penalty
                
                # Find best score and movement
                score_matrix[i][j] = max(match, delete, insert)
                
                # Record the move in traceback matrix
                if score_matrix[i][j] == match:
                    traceback[i][j] = 'diag'
                elif score_matrix[i][j] == delete:
                    traceback[i][j] = 'up'
                else:
                    traceback[i][j] = 'left'
                    
        return score_matrix, traceback
    
    def get_alignment(self, seq1: str, seq2: str, 
                     score_matrix: list, traceback: list) -> Tuple[str, str, str]:
        """
        Reconstruct the alignment from scoring and traceback matrices
        """
        aligned1 = []
        aligned2 = []
        symbols = []
        
        i = len(seq1)
        j = len(seq2)
        
        while i > 0 or j > 0:
            if i > 0 and j > 0 and traceback[i][j] == 'diag':
                aligned1.append(seq1[i-1])
                aligned2.append(seq2[j-1])
                if seq1[i-1] == seq2[j-1]:
                    symbols.append('|')
                else:
                    symbols.append('*')
                i -= 1
                j -= 1
            elif i > 0 and traceback[i][j] == 'up':
                aligned1.append(seq1[i-1])
                aligned2.append('-')
                symbols.append(' ')
                i -= 1
            elif j > 0:
                aligned1.append('-')
                aligned2.append(seq2[j-1])
                symbols.append(' ')
                j -= 1
                
        return (''.join(reversed(aligned1)), 
                ''.join(reversed(symbols)), 
                ''.join(reversed(aligned2)))
    
    def format_alignment(self, aligned1: str, symbols: str, 
                        aligned2: str, width: int = 60) -> str:
        """
        Format the alignment for pretty printing with line wrapping
        """
        result = []
        for i in range(0, len(aligned1), width):
            slice_end = min(i + width, len(aligned1))
            result.extend([
                f"Seq1: {aligned1[i:slice_end]}",
                f"      {symbols[i:slice_end]}",
                f"Seq2: {aligned2[i:slice_end]}",
                ""
            ])
        return "\n".join(result)
    
    def parse_step(self, step: str) -> Optional[Tuple[str, str]]:
        """Extract the RNA Central IDs from the step description"""
        match = re.search(r'rnaCentralIDs:\s*(\[[^\]]+\])', step)
        if match:
            try:
                rna_central_ids = json.loads(match.group(1))
                return tuple(rna_central_ids[:2]) if len(rna_central_ids) >= 2 else None
            except json.JSONDecodeError:
                return None
        return None
    
    def calculate_alignment_stats(self, aligned1: str, aligned2: str) -> Dict[str, float]:
        """Calculate alignment statistics"""
        matches = sum(1 for a, b in zip(aligned1, aligned2) if a == b)
        gaps = sum(1 for a, b in zip(aligned1, aligned2) if a == '-' or b == '-')
        total = len(aligned1)
        
        return {
            "identity": round(matches / total * 100, 2),
            "gaps": round(gaps / total * 100, 2),
            "alignment_length": total
        }
    
    def use_tool(self, step: str) -> str:
        # Get sequence IDs
        print("Step:", step)
        seq_ids = self.parse_step(step)
        if seq_ids is None:
            return "Invalid step description"
            
        # Get sequences from cache, could optimize by passing universal instance from websocket
        seq1_json = self.sequence_cache.get_by_rnacentral_id(seq_ids[0])
        seq2_json = self.sequence_cache.get_by_rnacentral_id(seq_ids[1])
        
        seq1_data = seq1_json["sequence_data"]
        seq2_data = seq2_json["sequence_data"]

        if seq1_data is None or seq2_data is None:
            return "Sequence not found in cache"
            
        # Extract sequences
        try:
            seq1 = seq1_data["sequence"]
            seq2 = seq2_data["sequence"]
        except (KeyError, TypeError) as e:
            return f"Error accessing sequence data: {str(e)}"
            
        # Perform alignment
        score_matrix, traceback = self.create_scoring_matrix(seq1, seq2)
        aligned1, symbols, aligned2 = self.get_alignment(
            seq1, seq2, score_matrix, traceback
        )
        
        # Calculate statistics
        stats = self.calculate_alignment_stats(aligned1, aligned2)
        
        # Format results
        result = [
            f"Alignment Statistics:",
            f"Sequence Identity: {stats['identity']}%",
            f"Gap Percentage: {stats['gaps']}%",
            f"Alignment Length: {stats['alignment_length']} bp",
            "",
            "Alignment:",
            self.format_alignment(aligned1, symbols, aligned2)
        ]
        
        print("\n".join(result)) # add to db
        return "\n".join(result)

if __name__ == "__main__":
    # Initialize tool and cache with test data
    tool = BasicAlignmentTool()
    
    test_sequences = {
        "URS0000176051_10090": {
            "id": "URS0000176051_10090",
            "sequence": "GCATTGGTGGTCCCCCGTGGTAGAATTCTCGCCT",
            "metadata": {
                "type": "tRNA",
                "organism": "Mus musculus"
            }
        },
        "URS000068B98D_10090": {
            "id": "URS000068B98D_10090",
            "sequence": "GCATTGGTGGTTCAGTGGTAGAAAATTCTCGCCT",
            "metadata": {
                "type": "tRNA",
                "organism": "Mus musculus"
            }
        }
    }
    
    # Add sequences to cache
    for seq_id, seq_data in test_sequences.items():
        tool.seq_cache.add_sequence(seq_id, seq_data)
    
    # Test the alignment
    result = tool.use_tool('ALIGNER: rnaCentralIDs: ["URS0000176051_10090", "URS000068B98D_10090"]')
    print("\nFinal alignment result:", result)