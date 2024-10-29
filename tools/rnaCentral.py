import re
import json
from typing import List, Dict, Any, Optional, Tuple
from urllib.parse import quote

import requests
from selenium import webdriver
from selenium.webdriver.chrome.service import Service as ChromeService
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException
from webdriver_manager.chrome import ChromeDriverManager




class rnaCentralTool:
    '''
    When the chatbot initiates tool use, the tool request message is sent here, parsed, and the appropriate sequences are retrieved and returned to the bot.
    chatbot.py handles the tool request message and calls the appropriate tool handler to get the extra data.
    '''
    SEARCH_FIELDS = [
        "expert_db", "taxonomy", "tax_string", "species", "common_name", "rna_type",
        "so_rna_type_name", "gene", "organelle", "description", "length", "pub_title",
        "author", "pubmed", "doi", "md5", "interacting_protein", "interacting_rna",
        "evidence_for_interaction", "has_secondary_structure", "has_conserved_structure",
        "has_go_annotations", "has_genomic_coordinates", "has_interacting_proteins",
        "has_interacting_rnas", "has_lit_scan", "has_litsumm", "has_editing_event"
    ]

    AA_TO_ANTICODONS = {
        'ALA': ['AGC', 'GGC', 'CGC', 'TGC'],
        'ARG': ['ACG', 'GCG', 'CCG', 'TCG', 'CCT', 'TCT'],
        'ASN': ['ATT', 'GTT'],
        'ASP': ['ATC', 'GTC'],
        'CYS': ['ACA', 'GCA'],
        'GLU': ['CTC', 'TTC'],
        'GLN': ['CTG', 'TTG'],
        'GLY': ['ACC', 'GCC', 'CCC', 'TCC'],
        'HIS': ['ATG', 'GTG'],
        'ILE': ['AAT', 'GAT', 'TAT'],
        'LEU': ['AAG', 'GAG', 'CAG', 'TAG', 'CAA', 'TAA'],
        'LYS': ['CTT', 'TTT'],
        'MET': ['CAT'],
        'PHE': ['AAA', 'GAA'],
        'PRO': ['AGG', 'GGG', 'CGG', 'TGG'],
        'SER': ['AGA', 'GGA', 'CGA', 'TGA', 'ACT', 'GCT'],
        'THR': ['AGT', 'GGT', 'CGT', 'TGT'],
        'TRP': ['CCA'],
        'TYR': ['ATA', 'GTA'],
        'VAL': ['AAC', 'GAC', 'CAC', 'TAC'],
        'SEC': ['TCA'],
        'SUPPRESSOR': ['CTA', 'TTA']
    }

    def __init__(self, sequence_cache=None):
        if sequence_cache is None:
            from cache import SequenceCache
            sequence_cache = SequenceCache()
        
        self.sequence_cache = sequence_cache

        self.driver = self._setup_driver()


    @staticmethod
    def _setup_driver():
        chrome_options = Options()
        chrome_options.add_argument("--headless")
        chrome_options.add_argument("--no-sandbox")
        chrome_options.add_argument("--disable-dev-shm-usage")
        chrome_options.add_argument("--window-size=1920,1080")
        
        service = ChromeService(ChromeDriverManager().install())
        return webdriver.Chrome(service=service, options=chrome_options)

    def parse_search_terms(self, claude_response: str) -> Tuple[Dict[str, Any], Optional[int]]:
        search_terms = {'expert_db': '"GtRNAdb"'}  # Always include GtRNAdb
        num_sequences = None
        amino_acid = None

        field_value_pairs = re.findall(r'(\w+):\s*"([^"]+)"', claude_response)
        
        for field, value in field_value_pairs:
            field = field.lower()
            
            if field == 'num_sequences':
                num_sequences = None if value.lower() == 'none' else self._parse_num_sequences(value)
            elif field == 'amino_acid':
                amino_acid = value.upper()
            elif field in self.SEARCH_FIELDS:
                search_terms[field] = f'"{value}"'
            else:
                print(f"Unrecognized search field: {field}")

        if amino_acid:
            search_terms['amino_acid_query'] = self._get_amino_acid_query(amino_acid)

        return search_terms, num_sequences

    @staticmethod
    def _parse_num_sequences(value: str) -> Optional[int]:
        try:
            return int(value)
        except ValueError:
            print(f"Invalid num_sequences value: {value}")
            return None

    def _get_amino_acid_query(self, amino_acid: str) -> Optional[str]:
        if amino_acid in self.AA_TO_ANTICODONS:
            anticodons = self.AA_TO_ANTICODONS[amino_acid]
            if len(anticodons) > 1:
                anticodon_query = " OR ".join([f'description:"*{anticodon}*"' for anticodon in anticodons])
                return f'({anticodon_query})'
            return f'description:"*{anticodons[0]}*"'
        print(f"Unknown amino acid: {amino_acid}")
        return None

    def construct_search_query(self, claude_response: str) -> Tuple[str, Optional[int]]:
        search_terms, num_sequences = self.parse_search_terms(claude_response)
        query_parts = [f'expert_db:{search_terms["expert_db"]}']
        
        for field, value in search_terms.items():
            if field not in ['expert_db', 'amino_acid_query']:
                query_parts.append(f'{field}:{value}')
        
        if 'amino_acid_query' in search_terms:
            query_parts.append(search_terms['amino_acid_query'])
        
        query = " AND ".join(query_parts)
        
        return query, num_sequences

    def search_rnacentral(self, query: str) -> Tuple[List[str], str]:
        try:
            encoded_query = quote(query, safe='":')
            url = f"https://rnacentral.org/search?q={encoded_query}"
            
            print(f"Constructed search query: {query}")
            print(f"Accessing URL: {url}")
            self.driver.get(url)
            
            try:
                WebDriverWait(self.driver, 20).until(
                    EC.presence_of_element_located((By.CLASS_NAME, "text-search-result"))
                )
            except TimeoutException:
                print("No tRNA results found.")
                return [], url
            
            results = self.driver.find_elements(By.CLASS_NAME, "text-search-result")
            rnacentral_ids = self._extract_rna_ids(results)
            
            print(f"Found {len(rnacentral_ids)} results")

            return rnacentral_ids[:15], url
        except Exception as e:
            print(f"An error occurred during search: {str(e)}")
            return [], url

    @staticmethod
    def _extract_rna_ids(results) -> List[str]:
        rnacentral_ids = []
        for result in results:
            try:
                rna_id = result.find_element(By.CLASS_NAME, "text-muted").text
                rnacentral_ids.append(rna_id)
            except Exception as e:
                print(f"Error extracting RNAcentral ID: {str(e)}")
        return rnacentral_ids

    @staticmethod
    def get_trna_sequences(rnacentral_ids: List[str]) -> List[Dict[str, Any]]:
        base_url = "https://rnacentral.org/api/v1/rna"
        full_api_responses = []
        
        for rna_id in rnacentral_ids:
            response = requests.get(f"{base_url}/{rna_id}")
            
            if response.status_code == 200:
                data = response.json()
                full_api_responses.append(data)
            else:
                print(f"Error fetching data for {rna_id}: {response.status_code}")
        
        return full_api_responses

    def __del__(self):
        if hasattr(self, 'driver'):
            self.driver.quit()


    def use_rna_central_tool(self, step: str) -> Dict[str, Any]:
        print(f"Received step: {step}") #debug
        search_query, num_sequences = self.construct_search_query(step)
        rnacentral_ids, full_results_url = self.search_rnacentral(search_query)
        
        if rnacentral_ids:
            if num_sequences is not None:
                rnacentral_ids = rnacentral_ids[:num_sequences]
            full_api_responses = self.get_trna_sequences(rnacentral_ids)
            
            # Cache the sequences
            for sequence in full_api_responses:
                print("Sequence: ", sequence)
                self.sequence_cache.add_sequence(sequence['rnacentral_id'], sequence)
            
            return {
                "api_data": full_api_responses,
                "full_results_url": full_results_url
            }
        else:
            return {"error": "No tRNA sequences found for the given query."}




if __name__ == '__main__':
    tool = rnaCentralTool()
    result = tool.use_rna_central_tool('species:"Homo sapiens" amino_acid:"Glu" num_sequences:"3"')
    print(result)