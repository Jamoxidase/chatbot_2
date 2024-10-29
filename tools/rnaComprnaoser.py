from selenium import webdriver, common
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, WebDriverException
import re
import time
import logging

import json



logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class RNAFoldingTool:
    def __init__(self, sequence_cache=None):
        self.base_url = "http://rnacomposer.ibch.poznan.pl"
        self.driver = None

        if sequence_cache is None:
            from cache import SequenceCache
            sequence_cache = SequenceCache
        self.sequence_cache = sequence_cache
        
    def _setup_driver(self):
        """Initialize Chrome driver with headless mode"""
        options = webdriver.ChromeOptions()
        options.add_argument('--headless')
        options.add_argument('--no-sandbox')
        options.add_argument('--disable-dev-shm-usage')
        # Add window size to ensure elements are visible
        options.add_argument('--window-size=1920,1080')
        # Add additional options that might help with stability
        options.add_argument('--disable-gpu')
        options.add_argument('--disable-extensions')
        
        try:
            self.driver = webdriver.Chrome(options=options)
            self.driver.set_page_load_timeout(30)
        except WebDriverException as e:
            logger.error(f"Failed to initialize Chrome driver: {str(e)}")
            raise
        
        
    def _format_input(self, rnacentral_id: str, sequence: str, structure: str) -> str:
        """Format the input in FASTA format with the correct structure notation"""
        # Truncate ID to just the URS part (first 15 chars) since _9606 is just the taxonomy ID
        task_id = rnacentral_id.split('_')[0]  # This will get just 'URS0000C8E9CE'
        if len(task_id) > 15:
            logger.warning(f"Truncating task_id from {len(task_id)} to 15 characters")
            task_id = task_id[:15]
            
        # Convert structure notation
        structure = structure.replace('>', '(').replace('<', ')')
        # Convert sequence to RNA (uppercase and T->U)
        sequence = sequence.upper().replace('T', 'U')
        
        return f">{task_id}\n{sequence}\n{structure}"
        
    
    def _submit_and_wait(self, input_data: str, max_wait: int = 300) -> str:
        """Submit the data and wait for results with improved error handling"""
        try:
            # Navigate to the page
            logger.info("Navigating to RNA Composer...")
            self.driver.get(self.base_url)
            time.sleep(2)  # Add small delay to ensure page loads
            
            # Find and fill the input textarea
            logger.info("Finding input textarea...")
            textarea = WebDriverWait(self.driver, 20).until(
                EC.presence_of_element_located((By.ID, "input"))
            )
            textarea.clear()
            textarea.send_keys(input_data)
            
            # Find and click the compose button
            logger.info("Clicking compose button...")
            submit_button = WebDriverWait(self.driver, 10).until(
                EC.element_to_be_clickable((By.ID, "send"))
            )
            submit_button.click()
            
            # Wait and check for errors first
            logger.info("Checking for validation errors...")
            try:
                error_div = self.driver.find_element(By.CLASS_NAME, "errorDiv")
                if error_div.is_displayed():
                    error_text = error_div.text
                    logger.error(f"Validation error: {error_text}")
                    # Extract specific error messages
                    error_table = error_div.find_element(By.CLASS_NAME, "errorDivInnerTable")
                    error_messages = error_table.find_elements(By.TAG_NAME, "td")
                    for msg in error_messages:
                        if msg.text and not msg.text.strip() == "Message":
                            logger.error(f"Error message: {msg.text}")
                    raise ValueError("Input validation failed")
            except common.exceptions.NoSuchElementException:
                pass  # No validation errors found

            # Wait for progress log
            logger.info("Waiting for progress updates...")
            progress_div = WebDriverWait(self.driver, 30).until(
                EC.presence_of_element_located((By.ID, "progressLog"))
            )
            
            # Wait and monitor for task completion
            start_time = time.time()
            while time.time() - start_time < max_wait:
                # Check for "Task completed" message
                try:
                    task_status = self.driver.find_elements(By.CLASS_NAME, "task-log")
                    if any("Task completed" in status.text for status in task_status):
                        logger.info("Task completion detected")
                        break
                except:
                    pass
                time.sleep(2)  # Poll every 2 seconds
                
            # Now wait for results div to be populated
            logger.info("Waiting for results to appear...")
            results_div = WebDriverWait(self.driver, 30).until(
                EC.presence_of_element_located((By.ID, "results"))
            )
            
            # Wait a bit more for the content to be populated
            time.sleep(5)
            
            # Find blocks.txt link
            logger.info("Looking for .pdb link...")
            try:
                blocks_link = WebDriverWait(self.driver, 20).until(
                    EC.presence_of_element_located((By.XPATH, "//a[contains(@href, 'GetResult') and contains(@href, '.pdb')]"))
                )
                blocks_url = blocks_link.get_attribute('href')
                logger.info(f"Found blocks URL: {blocks_url}")
                return blocks_url
            except Exception as e:
                logger.error("Failed to find blocks.pdb link")
                # Log the current state of the results div
                logger.error(f"Results div content: {results_div.get_attribute('innerHTML')}")
                raise
                
        except TimeoutException as e:
            logger.error("Timeout while waiting for results")
            # Take screenshot and log page state
            if self.driver:
                self.driver.save_screenshot("timeout_error.png")
                logger.error("Current page source:")
                logger.error(self.driver.page_source)
                # Try to get any progress information
                try:
                    progress = self.driver.find_element(By.ID, "progressLog").text
                    logger.error(f"Progress log content: {progress}")
                except:
                    pass
            raise
        except Exception as e:
            logger.error(f"Error during submission: {str(e)}")
            if self.driver:
                self.driver.save_screenshot("general_error.png")
                logger.error(self.driver.page_source)
            raise

    def _download_blocks_file(self, url: str) -> str:
        """Download the blocks.txt file with retry mechanism"""
        import requests
        from requests.adapters import HTTPAdapter
        from urllib3.util.retry import Retry
        
        # Setup retry strategy
        session = requests.Session()
        retries = Retry(total=5,
                       backoff_factor=0.1,
                       status_forcelist=[500, 502, 503, 504])
        session.mount('http://', HTTPAdapter(max_retries=retries))
        session.mount('https://', HTTPAdapter(max_retries=retries))
        
        try:
            response = session.get(url, timeout=30)
            response.raise_for_status()
            return response.text
        except Exception as e:
            logger.error(f"Error downloading blocks file: {str(e)}")
            raise

    def process_sequence(self, rnacentral_id: str, sequence: str, structure: str, cache= None) -> str:
        """Main method to process a sequence and get blocks data
        
        Args:
            rnacentral_id: The RNA central ID
            sequence: The RNA sequence
            structure: The secondary structure
            cache: The SequenceCache instance to store results (optional)
            
        Returns:
            str: The blocks file content
        """
        try:
            print("initiating rnafold driver")
            self._setup_driver()
            
            # Format input data
            input_data = self._format_input(rnacentral_id[:13], sequence, structure)
            logger.info(f"Formatted input:\n{input_data}")
            
            # Submit and get blocks URL
            blocks_url = self._submit_and_wait(input_data)
            logger.info(f"Got blocks URL: {blocks_url}")
            
            # Download blocks file
            blocks_content = self._download_blocks_file(blocks_url)
            logger.info("Successfully downloaded blocks file")
            

            success = self.sequence_cache.update_tool_data(rnacentral_id, 
                                                'blocks_file', 
                                                blocks_content)
            if success:
                print(f"Successfully stored blocks data in cache for {rnacentral_id}")
            else:
                print(f"Failed to store blocks data in cache for {rnacentral_id}")

            return blocks_content
        
        except Exception as e:
            print(f"Error processing sequence: {str(e)}")

        finally:
            if self.driver:
                self.driver.quit()

    def check_sequence_and_structure_lengths(self, sequence: str, structure: str) -> str:
        try:
            assert len(sequence) == len(structure), "Sequence and secondary structure lengths do not match"
            return True
        except AssertionError:
            return False


    def use_tool(self, step: str) -> str:
        """Use the RNA folding tool with the provided step data"""
        print("Recieved Step: ", step)
        match = re.search(r'RNAcentral ID:\s*(\S+)', step)
        if match:
            try:
                rna_central_id = match.group(1)
            except:
                return "Error: Invalid RNAcentral ID"
        # Get sequence from cache
        sequence_json = self.sequence_cache.get_by_rnacentral_id(rna_central_id)
        sequence = sequence_json["sequence_data"]["trnascan_sequence"]
        ss = sequence_json["sequence_data"]["secondary_structure"]
        validity = self.check_sequence_and_structure_lengths(sequence, ss)

        if not sequence:
            return "sequence not found in cache- get sequence"
        
        if not validity:
            return "Sequence and secondary structure lengths do not match, please check the input"

        
        try:
            result = self.process_sequence(rna_central_id, sequence, ss)
            return result
        except Exception as e:
            return f"Error processing sequence: {str(e)}"