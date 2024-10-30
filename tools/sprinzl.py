import os
import sys
import subprocess
import json
import tempfile
from pathlib import Path
from typing import Dict, Optional, Tuple
from datetime import datetime
import logging
from abc import ABC
import re
import shutil
#from cache import SequenceCache

RETAIN_OUTPUT_FILES = False
TOOLS_ROOT = Path(os.path.dirname(os.path.abspath(__file__)))

class ToolManager(ABC):
    """Abstract base class for tRNA analysis tools."""
    
    def __init__(self, work_dir: str, enable_logging: bool = False):
        self.work_dir = Path(work_dir).resolve() / 'tools'
        self.data_dir = self.work_dir / 'data'
        self.logs_dir = self.data_dir / 'logs'
        self.results_dir = self.data_dir / 'results'
        
        # Create directories
        for directory in [self.data_dir, self.logs_dir, self.results_dir]:
            directory.mkdir(parents=True, exist_ok=True)
            
        if enable_logging:
            self.setup_logging()
        else:
            self.logger = logging.getLogger(self.__class__.__name__)
            self.logger.addHandler(logging.NullHandler())

    
    
    def setup_logging(self):
        """Configure logging for the tool."""
        self.logger = logging.getLogger(self.__class__.__name__)
        self.logger.setLevel(logging.INFO)
        
        if not self.logger.handlers:
            formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
            
            # File handler
            fh = logging.FileHandler(self.logs_dir / f'{self.__class__.__name__.lower()}_{datetime.now():%Y%m%d_%H%M%S}.log')
            fh.setFormatter(formatter)
            self.logger.addHandler(fh)
            
            # Console handler
            ch = logging.StreamHandler()
            ch.setFormatter(formatter)
            self.logger.addHandler(ch)
    
    def _run_command(self, cmd: list, tool_name: str) -> Dict[str, str]:
        """Execute a command and save output to log files."""
        print(f"\nRunning {tool_name}...")
        
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        stdout_file = self.logs_dir / f'{tool_name}-stdout-{timestamp}.log'
        stderr_file = self.logs_dir / f'{tool_name}-stderr-{timestamp}.log'
        
        self.logger.info(f"Running command: {' '.join(cmd)}")
        self.logger.info(f"Output files: stdout={stdout_file}, stderr={stderr_file}")
        
        try:
            with open(stdout_file, 'w') as stdout_fh, open(stderr_file, 'w') as stderr_fh:
                result = subprocess.run(
                    cmd,
                    stdout=stdout_fh,
                    stderr=stderr_fh,
                    text=True,
                    check=True
                )
            
            return {
                'stdout_file': str(stdout_file),
                'stderr_file': str(stderr_file)
            }
            
        except subprocess.CalledProcessError as e:
            self.logger.error(f"Command failed with return code {e.returncode}")
            with open(stderr_file) as f:
                error_content = f.read()
            raise RuntimeError(f"Command failed: {error_content}")
                        


class TRNAScan(ToolManager):
    """Interface for tRNAscan-SE tool."""
    
    VALID_CLADES = {'Eukaryota', 'Bacteria', 'Archaea'}
    
    def __init__(self, work_dir: str, enable_logging: bool = True):
        super().__init__(work_dir, enable_logging)
        self.executable = "/usr/local/bin/tRNAscan-SE" ################################################################################################################################
        if not Path(self.executable).is_file():
            raise FileNotFoundError(f"tRNAscan-SE executable not found at {self.executable}")

    def run_from_sequence(self, sequence: str, clade: str) -> str:
        """
        Run tRNAscan-SE analysis from a sequence string.
        Returns the contents of the .ss file.
        """
        if clade not in self.VALID_CLADES:
            raise ValueError(f"Invalid clade. Must be one of: {self.VALID_CLADES}")
            
        # Create temporary FASTA file
        with tempfile.NamedTemporaryFile(mode='w', suffix='.fa', delete=False) as temp_fasta:
            temp_fasta.write(f">temp_seq\n{sequence}\n")
            temp_fasta_path = temp_fasta.name
            
        try:
            # Run tRNAscan-SE
            output_base = self.results_dir / "temp_output"
            ss_file = f"{output_base}.ss"
            
            cmd = [
                self.executable,
                '-E' if clade == 'Eukaryota' else '-B' if clade == 'Bacteria' else '-A',
                '-f', ss_file,
                '-o', f"{output_base}.out",
                '-m', f"{output_base}.stats",
                temp_fasta_path
            ]
            
            self._run_command(cmd, "tRNAscan")
            
            # Read SS file contents
            with open(ss_file) as f:
                ss_contents = f.read()
                
            return ss_contents
            
        finally:
            # Cleanup only if RETAIN_OUTPUT_FILES is False
            os.unlink(temp_fasta_path)  # Always remove temp input
            if not RETAIN_OUTPUT_FILES:
                for ext in ['.ss', '.out', '.stats']:
                    try:
                        os.unlink(f"{output_base}{ext}")
                    except FileNotFoundError:
                        pass


class Sprinzl(ToolManager):
    """Interface for tRNA_sprinzl_pos tool."""
    
    VALID_CLADES = {'Eukaryota', 'Bacteria', 'Archaea'}
    
    def __init__(self, work_dir: str, enable_logging: bool = True):
        super().__init__(work_dir, enable_logging)
        
        self.sprinzl_dir = TOOLS_ROOT / 'trna_software' / 'sprinzl' ########
        self.executable = self.sprinzl_dir / 'tRNA_sprinzl_pos'
        
        if not self.executable.is_file():
            raise FileNotFoundError(f"tRNA_sprinzl_pos executable not found at {self.executable}")

    def run_from_ss(self, ss_content: str, clade: str) -> str:
        """
        Run Sprinzl analysis from SS file contents.
        Returns the contents of the .pos file.
        """
        if clade not in self.VALID_CLADES:
            raise ValueError(f"Invalid clade. Must be one of: {self.VALID_CLADES}")
            
        # Create temporary SS file
        with tempfile.NamedTemporaryFile(mode='w', suffix='.ss', delete=False) as temp_ss:
            temp_ss.write(ss_content)
            temp_ss_path = temp_ss.name
            
        try:
            # Create temporary output directory
            temp_output_dir = self.results_dir / f"sprinzl_temp_{datetime.now():%Y%m%d_%H%M%S}"
            temp_output_dir.mkdir(exist_ok=True)
            
            # Save current directory and change to sprinzl directory
            original_dir = os.getcwd()
            os.chdir(self.sprinzl_dir)
            
            try:
                cmd = [
                    './tRNA_sprinzl_pos',
                    '-c', 'map-sprinzl-pos.conf',
                    '-d', clade,
                    '-s', temp_ss_path,
                    '-o', str(temp_output_dir)
                ]
                
                self._run_command(cmd, "Sprinzl")
                
                # Find and read .pos file
                pos_files = list(temp_output_dir.glob("*.pos"))
                if not pos_files:
                    raise RuntimeError("No .pos file generated")
                    
                with open(pos_files[0]) as f:
                    pos_contents = f.read()
                    
                return pos_contents
                
            finally:
                os.chdir(original_dir)
                
        finally:
            # Cleanup only if RETAIN_OUTPUT_FILES is False
            os.unlink(temp_ss_path)  # Always remove temp input
            if not RETAIN_OUTPUT_FILES:
                shutil.rmtree(temp_output_dir, ignore_errors=True)

class RunPipeline:
    def __init__(self, sequence_cache=None):
        if sequence_cache is None:
            from cache import SequenceCache
            self.sequence_cache = SequenceCache()
        else:
            self.sequence_cache = sequence_cache

    def parse_pipeline_request(self, message: str, work_dir: str = "./", enable_logging: bool = True) -> Tuple[str, str]:
        """
        Parse and process a combined tRNAscan-SE/SPRINZL request.
        Returns tuple of (ss_contents, pos_contents)
        
        Example message:
        tRNAscan-SE/SPRINZL
        RNAcentral ID: URS000000000A
        Clade: Eukaryota
        """

        print("Recieved Step: ", message) #debug
        # Validate that this is a pipeline request
        #if not message.startswith("tRNAscan-SE/SPRINZL"):
            #raise ValueError("Message must start with 'tRNAscan-SE/SPRINZL'")
        
        # Parse input
        rna_id_match = re.search(r'RNAcentral ID:\s*(\S+)', message)
        clade_match = re.search(r'Clade:\s*(\S+)', message)
        
        if not rna_id_match or not clade_match:
            raise ValueError("Message must contain 'RNAcentral ID:' and 'Clade:'")
            
        rna_id = rna_id_match.group(1)
        clade = clade_match.group(1)
        
        ####HERE
        sequence_json = self.sequence_cache.get_by_rnacentral_id(rna_id)

        if not sequence_json:
            return "sequence not found in cache- get sequence", ""
        

        sequence = sequence_json["sequence_data"]["sequence"]
        
        # Initialize tools, run pipeline
        trnascan = TRNAScan(work_dir, enable_logging)
        ss_contents = trnascan.run_from_sequence(sequence, clade)
        self.sequence_cache.update_tool_data(
            rna_id,
            "trnascan_se_ss",
            ss_contents
        )
        
        sprinzl = Sprinzl(work_dir, enable_logging)
        pos_contents = sprinzl.run_from_ss(ss_contents, clade)
        self.sequence_cache.update_tool_data(
            rna_id,
            "sprinzl_pos",
            pos_contents
        )

        print(pos_contents) #debug
        
        return ss_contents, pos_contents
