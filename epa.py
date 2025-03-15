#!/usr/bin/env python

from ai_utils import get_environmental_issues, title_exists
from bs4 import BeautifulSoup
from datetime import datetime
from dotenv import load_dotenv
from llm_factory import LLMFactory
from pydantic import BaseModel, Field, field_validator
from typing import List, Literal, Optional, Tuple, Dict
from urllib.parse import urljoin
import PyPDF2
import argparse
import json
import logging
import os
import re
import requests
import sys
import tempfile
import time

# Load environment variables
load_dotenv()

# ===== Configuration =====
# EPA URLs and endpoints
EPA_BASE_URL = "https://www.epa.gov"
EPA_ENFORCEMENT_PAGE = f"{EPA_BASE_URL}/enforcement/civil-and-cleanup-enforcement-cases-and-settlements"

# HTTP request settings
HTTP_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
}
HTTP_TIMEOUT = 30  # seconds

# PDF processing settings
PDF_DOWNLOAD_DELAY = 1  # seconds between PDF downloads

# Text analysis settings
TEXT_LENGTH_THRESHOLDS = [6000, 12000, 20000]
DEFAULT_NUM_PARAGRAPHS = [2, 3, 4, 5]  # Paragraphs for each threshold

# Output settings
OUTPUT_FILENAME = "epa.json"


# ===== Set up logging =====
def setup_logging(log_level=logging.INFO):
    """Configure logging for the application."""
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s - %(levelname)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        # Write to log and to console if desired
        handlers=[logging.FileHandler("/var/log/epa_scraper.log"), logging.StreamHandler()],
    )

    # Reduce verbosity of external libraries
    logging.getLogger("requests").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)

    return logging.getLogger(__name__)


# Initialize logger
logger = setup_logging()


# ===== Pydantic Data Models =====
class FederalLaw(BaseModel):
    """
    Represents a federal law citation, categorized as either a Statute or Rule.

    A Statute refers to a U.S. Code citation (U.S.C.), which contains laws passed
    by Congress.  A Rule refers to a Code of Federal Regulations citation (C.F.R.),
    which contains regulations issued by federal agencies.

    Both types of citations are validated for proper format and normalized
    for consistency.
    """

    model_config = {
        "json_schema_extra": {
            "examples": [
                {"type": "Statute", "citation": "42 U.S.C. § 7401"},
                {"type": "Statute", "citation": "5 USC 552"},
                {"type": "Rule", "citation": "40 C.F.R. § 1068.101"},
                {"type": "Rule", "citation": "10 CFR 50.47"},
            ]
        }
    }

    type: Literal["Statute", "Rule"] = Field(
        description="""Type of federal law citation - either 'Statute'
        for U.S.C. citations or 'Rule' for C.F.R. citations"""
    )

    citation: str = Field(
        description="""Properly formatted citation string for federal
        laws with these flexible patterns:
        - Statutes: '1-3 digits U.S.C. [§/§§] section number' (e.g.,
          '42 U.S.C. § 7401', '5 USC 552')
        - Rules: '1-2 digits C.F.R. [§/§§] section number' (e.g.,
          '40 C.F.R. § 1068.101', '10 CFR 50.47')
        Periods in 'U.S.C.' and 'C.F.R.' are optional, section symbols
        (§) are optional, and 'Part' designations are normalized out."""
    )

    @field_validator("citation")
    def check_citation(cls, value, info):
        """
        Validates and normalizes federal law citations.

        Transformations applied:
        1. Double section symbols (§§) are converted to single (§)
           Example: "5 U.S.C. §§ 552" → "5 U.S.C. § 552"

        2. "Parts" is turned into single "Part" and then "Part" is
           removed from citations

           Examples:
           - "18 C.F.R. Parts 145" → "18 C.F.R. 145"
           - "40 C.F.R. Part 1039" → "40 C.F.R. 1039"
           - "42 U.S.C. Part 7401" → "42 U.S.C. 7401"

        3. Combinations of both transformations
           Example: "40 C.F.R. §§ Part 1039" → "40 C.F.R. § 1039"

        Validation rules:
        - USC format: "XX U.S.C. [§] XXX"
        - CFR format: "XX C.F.R. [§] XXX"

        Args:
            value: The citation string to validate and transform
            info: ValidationInfo containing field context

        Returns:
            Normalized citation string

        Raises:
            ValueError: If citation format is invalid after transformation
            attempts
        """
        if "type" in info.data:
            # First, normalize any double section symbols to single
            value = value.replace("§§", "§")

            # Normalize different dash types to regular hyphen
            value = value.replace("–", "-").replace("—", "-")
        
            # Normalize spacing around hyphens
            value = re.sub(r'\s*-\s*', '-', value)

        if info.data["type"] == "Statute":
            # Check for Part/Parts in USC
            part_match = re.fullmatch(
                r"^(\d+)\sU\.?S\.?C\.?\s?§?\s?Parts?\s+([\d\w\.\(\)\-]+)$",
                value,
                re.IGNORECASE,
            )
            if part_match:
                return f"{part_match.group(1)} U.S.C. {part_match.group(2)}"
            # Check regular USC format
            if not re.fullmatch(
                r"^(\d+)\sU\.?S\.?C\.?\s?§?\s?([\d\w\.\(\)\-]+)$", value
            ):
                raise ValueError("Invalid USC citation format")

        elif info.data["type"] == "Rule":
            # Check for Part/Parts in CFR
            part_match = re.fullmatch(
                r"^(\d{1,2})\sC\.?F\.?R\.?\s?§?\s?Parts?\s+([\d\w\.\(\)\-]+)$",
                value,
                re.IGNORECASE,
            )
            if part_match:
                return f"{part_match.group(1)} C.F.R. {part_match.group(2)}"

            # Check regular CFR format - expanded to allow more complex section references
            if not re.fullmatch(
                r"^(\d{1,2})\sC\.?F\.?R\.?\s?§?\s?([\d\w\.\(\)\-]+)$", value
            ):
                # Added a more flexible pattern for complex CFR citations
                complex_cfr = re.fullmatch(
                    r"^(\d{1,2})\sC\.?F\.?R\.?\s?§?\s?([\d\w\.\(\)\-]+(?:\([a-z]\))?(?:–\([a-z]\))?)$", 
                    value
                )
                if complex_cfr:
                    # Normalize the format
                    return f"{complex_cfr.group(1)} C.F.R. {complex_cfr.group(2)}"
                else:
                    raise ValueError("Invalid CFR citation format")

        return value

class LegalAnalysis(BaseModel):
    """
    Top-level model representing a complete legal analysis of a document.

    This model contains structured data extracted from legal documents, including:

    1. Federal law citations (both statutes and rules)
    2. A detailed expert summary of the legal case.  HTML bold any legal citations you find, such as 40 C.F.R. § 263.21(a), as well as proper names of people and companies, and penalty information.
    3. An optional penalty amount if the target of the action was sanctioned
    4. What environmental issues the document addresses

    This structured format allows for consistent extraction and processing
    of legal citations and data.
    """

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "federal_law": [
                        {"type": "Statute", "citation": "42 U.S.C. § 7522(a)(1)"},
                        {"type": "Rule", "citation": "40 C.F.R. § 1068.101"},
                    ],
                    "summary": "This case involves violations of emissions standards under the Clean Air Act. The defendant is alleged to have sold vehicles that did not comply with EPA certification requirements.",
                    "penalty": 47500,
                    "environmental_issues": ["Automobiles and Trucks", "Hazardous Waste"]
                }
            ]
        }
    }

    federal_law: Optional[List[FederalLaw]] = Field(
        default=None,
        description="List of federal statutes (U.S.C.) and rules (C.F.R.) cited in the legal document",
    )

    summary: str = Field(
        description="A detailed legal expert summary of the case, explaining the key legal issues and citations.  HTML bold any legal citations you find, such as 40 C.F.R. § 263.21(a), as well as proper names of people and companies, and penalty information."
    )

    penalty: Optional[float] = Field(
        None, description="Monetary penalty amount in USD, if any"
    )
    
    environmental_issues: Optional[List[str]] = Field(
        default=None,
        description="The environmental issues the document touches upon. Can be empty list or null if none of our enumerated issues applies."
    )
    
    '''
    Validate categories sent back by the LLM against our dynamically-created list from Drupal
    '''
    @field_validator("environmental_issues")
    def validate_environmental_issues(cls, value):
        """
        Validate categories sent back by the LLM against our dynamically-created list from Drupal
        and converts empty lists to None.
        """
        # If None already, just return it
        if value is None:
            return None
        
        # Convert empty list to None for consistency
        if len(value) == 0:
            return None
        
        # Get the current list of valid issue categories dynamically from Drupal database
        valid_issues = get_environmental_issues()
        
        # Validate each issue against the list from Drupal
        for issue in value:
            if issue not in valid_issues:
                raise ValueError(f"Invalid environmental issue: {issue}")
        
        return value

    @field_validator("federal_law")
    def validate_federal_law(cls, value):
        """
        Validates federal_law list and converts empty lists to None.

        Args:
            value: The federal_law list to validate

        Returns:
            The value or None if it's an empty list
        """
        # If None already, just return it
        if value is None:
            return None

        # Convert empty list to None for consistency
        if len(value) == 0:
            return None

        return value

    @field_validator("penalty")
    def check_penalty(cls, value):
        """
        Validates that the penalty is a float with at most two decimal places.
        """
        if value is None:
            return None  # Allow None values

        if not isinstance(value, (int, float)):
            raise ValueError("Penalty must be a number (int or float)")

        # Convert to float if it's an integer
        value = float(value)

        # Check the number of decimal places
        decimal_part = str(value).split(".")[1] if "." in str(value) else ""
        if len(decimal_part) > 2:
            raise ValueError("Penalty can have at most two decimal places")

        return value

# ===== LLM System Message =====
def create_system_message(num_paragraphs: int) -> str:
    """Create the system message for the LLM with the specified number of paragraphs."""

    # Get current environmental issues dynamically from Drupal DB
    issues_list = get_environmental_issues()
    
    # Format the issues as a bullet list for use in the prompt
    issues_bullet_points = "\n".join([f"       - {issue}" for issue in issues_list])

    system_message = f"""
    You are a highly specialized legal assistant. You have 4 tasks:

    1. Produce a detailed summary of the text
    2. Extract an accurate penalty, if any
    3. Extract *specific* citations of federal statutes and rules from legal text

    Your response MUST be valid JSON conforming to this schema:

    ```json
    {json.dumps(LegalAnalysis.model_json_schema(), indent=2)}

    4. Environmental Issues: Classify the document into appropriate categories from this list:
    {issues_bullet_points}

       A document can relate to no issues, one issue, or multiple issues.
       Only include issues that are clearly relevant to the case.
       Return an empty list [] or null if no issues apply.


    EXTREMELY IMPORTANT INSTRUCTIONS:

    1. The summary field should be exactly {num_paragraphs} paragraphs long,
    providing a detailed legal analysis of the case. Focus on the most
    important information and avoid unnecessary detail. Format the summary in
    HTML using <p> tags. Do not include newlines; output the HTML as a single,
    long one-line string. Use only inner HTML tags; do not include `<html>`,
    `<head>`, or `<body>` tags."

    2. Penalty - Identify the total fine or penalty amount, if any.
    It must be explicitly stated in the document. If no such order is
    explicitly made you should not guess or infer a result and should
    output a 0 (zero). Be sure you are accurate in determining the penalty.
    Sometimes multiple matters are involved and there is a total penalty,
    if so use this larger total.  Report the dollar total as a number. Note
    that if a number is reported as, say, $3 million, convert the million
    to a number, e.g. 3,000,000.

    3. Extract ONLY Specific Citations: Do NOT include the general name of
    a law (e.g., "Clean Air Act"). You MUST extract the precise citation in
    the following formats:

       a. Federal Statutes: XX U.S.C. § YYYY (e.g., 42 U.S.C. § 7521)
       b. Federal Rules: XX C.F.R. § YYYY (e.g., 40 C.F.R. § 1068.101)

    4. Federal Laws: For each federal law:

       a. "type": MUST be either "Statute" or "Rule".
       b. "citation": MUST be the exact citation string.

    5. Environmental Issues: Classify the document into appropriate categories from this list:
       - Automobiles and Trucks
       - Boats
       - Chemicals
       - Construction Equipment
       - Drinking Water
       - Hazardous Waste
       - Oil and Gas
       - Sewage
       
       A document can relate to no issues, one issue, or multiple issues.
       Only include issues that are clearly relevant to the case.
       Return an empty list [] or null if no issues apply.

    6. No Laws Found: If you find NO specific citations, return:
    {{"federal_law": null}}.

    7. No Hallucinations: Do NOT include any law or rule unless you find a
    specific citation in the provided text. Do NOT guess or invent citations.

    8. JSON Only: Return ONLY the JSON. No introductory or explanatory text.

    Example (Illustrative):

    If the text contains: "...violates 42 U.S.C. § 7522(a)(1) and 40 C.F.R. § 1068.101..."

    Your JSON should include:

    {{
      "federal_law": [
        {{
          "type": "Statute",
          "citation": "42 U.S.C. § 7522(a)(1)"
        }},
        {{
          "type": "Rule",
          "citation": "40 C.F.R. § 1068.101"
        }}
      ],
      "summary": "<p>This case involves violations of emissions standards under the Clean Air Act...</p>",
      "penalty": 47500,
      "environmental_issues": ["Automobiles and Trucks", "Hazardous Waste"]
    }}
    """
    return system_message

# ===== Web Scraping Functions =====
def download_and_extract_pdf_text(pdf_url: str) -> str:
    """
    Download a PDF from the given URL and extract its text content.

    Args:
        pdf_url: URL of the PDF to download

    Returns:
        Extracted text content with whitespace normalized
    """
    try:
        logger.info(f"Downloading PDF: {pdf_url}")
        response = requests.get(pdf_url, headers=HTTP_HEADERS, timeout=HTTP_TIMEOUT)
        response.raise_for_status()

        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=True) as temp_file:
            temp_file.write(response.content)
            temp_file.seek(0)

            try:
                pdf_reader = PyPDF2.PdfReader(temp_file)

                if len(pdf_reader.pages) == 0:
                    logger.warning(f"PDF at {pdf_url} has no pages")
                    return ""

                logger.debug(f"PDF has {len(pdf_reader.pages)} pages")
                text_content = []
                for page in pdf_reader.pages:
                    page_text = page.extract_text() or ""
                    text_content.append(page_text)

                text = " ".join(text_content).strip()

                # Clean up excessive whitespace
                text = re.sub(r"\s+", " ", text).strip()

                # Clean up common PDF text extraction artifacts
                text = re.sub(r"\.{4,}", "...", text)
                text = re.sub("_{3,}", "", text)

                logger.debug(f"Extracted {len(text)} characters from PDF")
                return text

            except PyPDF2.errors.PdfReadError as e:
                logger.error(f"Error parsing PDF {pdf_url}: {e}")
                return f"[PDF parsing error: {str(e)}]"

    except requests.exceptions.Timeout:
        logger.error(f"Timeout error downloading PDF {pdf_url}")
        return ""
    except requests.exceptions.HTTPError as e:
        logger.error(f"HTTP error {e.response.status_code} downloading PDF {pdf_url}")
        return ""
    except requests.exceptions.ConnectionError:
        logger.error(f"Connection error downloading PDF {pdf_url}")
        return ""
    except requests.exceptions.RequestException as e:
        logger.error(f"Request error downloading PDF {pdf_url}: {e}")
        return ""
    except Exception as e:
        logger.error(f"Unexpected error processing PDF {pdf_url}: {e}", exc_info=True)
        return ""


def get_page_content(url: str) -> Tuple[str, str, str]:
    """
    Scrape article text, PDF links, and PDF text from a page.

    Args:
        url: URL of the page to scrape

    Returns:
        Tuple containing:
        - Article text
        - Comma-separated list of PDF links
        - Concatenated PDF texts
    """
    try:
        logger.info(f"Fetching page: {url}")
        response = requests.get(url, headers=HTTP_HEADERS, timeout=HTTP_TIMEOUT)
        response.raise_for_status()

        soup = BeautifulSoup(response.text, "html.parser")
        article = soup.find("article")
        article_text = ""

        if article:
            # Remove comment and contact sections
            comment_section = article.find(id="comment")
            contact_section = article.find(id="contact")

            if comment_section:
                logger.debug("Removing comment section from article")
                for elem in comment_section.find_all_next():
                    elem.decompose()
                comment_section.decompose()
            elif contact_section:
                logger.debug("Removing contact section from article")
                for elem in contact_section.find_all_next():
                    elem.decompose()
                contact_section.decompose()

            text_parts = [element for element in article.stripped_strings]
            article_text = " ".join(text_parts)
            article_text = re.sub(r"\s+", " ", article_text).strip()
            logger.debug(f"Extracted {len(article_text)} characters from article")

        found_pdf_links = []
        found_pdf_texts = []
        box_content = soup.find("div", class_="box__content")

        if box_content:
            # Find all PDF links
            pdf_links = []
            for link in box_content.find_all("a", href=True):
                if link["href"].lower().endswith(".pdf"):
                    pdf_links.append(link["href"])

            logger.info(f"Found {len(pdf_links)} PDF links")

            for href in pdf_links:
                if not href.startswith("http"):
                    href = urljoin(EPA_BASE_URL, href)
                found_pdf_links.append(href)

                # Download and extract text from PDF
                logger.info(f"Downloading and processing PDF: {href}")
                pdf_text = download_and_extract_pdf_text(href)
                if pdf_text:
                    found_pdf_texts.append(pdf_text)
                # Be nice to the server
                time.sleep(PDF_DOWNLOAD_DELAY)

        # Return statement properly aligned at function level
        return article_text, ",".join(found_pdf_links), " --- ".join(found_pdf_texts)

    except requests.exceptions.Timeout:
        logger.error(f"Timeout error fetching content from {url}")
        return "", "", ""
    except requests.exceptions.HTTPError as e:
        logger.error(f"HTTP error {e.response.status_code} fetching content from {url}")
        return "", "", ""
    except requests.exceptions.ConnectionError:
        logger.error(f"Connection error fetching content from {url}")
        return "", "", ""
    except requests.exceptions.RequestException as e:
        logger.error(f"Request error fetching content from {url}: {e}")
        return "", "", ""
    except Exception as e:
        logger.error(
            f"Unexpected error fetching content from {url}: {e}", exc_info=True
        )
        return "", "", ""


def extract_row_data(row) -> Dict:
    """
    Extract data from a single table row.

    Args:
        row: BeautifulSoup table row element

    Returns:
        Dictionary containing extracted data

    Raises:
        ValueError: If row doesn't have enough columns
    """
    try:
        # Get all td elements
        tds = row.select("td")
        if not tds or len(tds) < 4:
            raise ValueError("Row doesn't have enough td elements")

        # Extract href from first td if it exists
        href = ""
        respondent_td = tds[0]
        link = respondent_td.select_one("a")
        if link:
            href = link.get("href", "")
            if href and not href.startswith("http"):
                href = f"{EPA_BASE_URL}{href}"

        data = {
            "title": f"EPA Enforcement - {respondent_td.get_text(strip=True)}",
            "date": tds[3].get_text(strip=True),
            "source_url": href,
            "article_text": "",
            "pdf_links": "",
            "pdf_texts": "",
        }

        return data

    except ValueError as e:
        logger.warning(f"Data extraction error: {e}")
        raise
    except Exception as e:
        logger.error(f"Unexpected error extracting row data: {e}", exc_info=True)
        raise


def scrape_epa_cases(numrecs) -> Optional[List[Dict]]:
    """
    Scrape EPA enforcement cases from the main enforcement page.

    Args:
        numrecs: Number of most recent records to scrape

    Returns:
        List of dictionaries containing case data, or None if scraping fails
    """
    try:
        logger.info(f"Starting to scrape EPA cases, fetching {numrecs} records")
        response = requests.get(
            EPA_ENFORCEMENT_PAGE, headers=HTTP_HEADERS, timeout=HTTP_TIMEOUT
        )
        response.raise_for_status()

        soup = BeautifulSoup(response.text, "html.parser")
        rows = soup.select("table#datatable tbody tr")

        if not rows:
            logger.warning("No table rows found on the page")
            return None

        logger.info(
            f"Found {len(rows)} rows, processing first {min(numrecs, len(rows))}"
        )

        cases_data = []
        processed_count = 0
        skipped_count = 0

        for i, row in enumerate(rows[:numrecs]):
            try:
                logger.info(f"Processing row {i + 1}/{min(numrecs, len(rows))}")

                # First extract basic data
                basic_data = extract_row_data(row)
                node_title = basic_data["title"]

            		# Check if we should even process this record

                if title_exists(node_title):
                    logger.warning(f"Skipping {node_title} as it already exists")
                    skipped_count += 1
                    continue

                # Now fetch the full content since we know we need it
                if basic_data.get("link"):
                    logger.info(f"Fetching details for: {node_title}")
                    article_text, pdf_links, pdf_texts = get_page_content(
                        basic_data["link"]
                    )
                    basic_data["article_text"] = article_text
                    basic_data["pdf_links"] = pdf_links
                    basic_data["pdf_texts"] = pdf_texts

                    # Be nice to the server
                    time.sleep(1)

                cases_data.append(basic_data)
                processed_count += 1
                logger.info(f"Successfully processed data for {node_title}")

            except ValueError as e:
                logger.warning(
                    f"Skipping row {i + 1} due to data extraction error: {e}"
                )
                continue
            except Exception as e:
                logger.error(
                    f"Skipping row {i + 1} due to unexpected error: {e}", exc_info=True
                )
                continue

        # Log summary statistics
        logger.info(
            f"Processing summary: {processed_count} records processed, {skipped_count} records skipped"
        )

        # If we processed all requested records but they were all skipped,
        # return an empty list but with a special log message so main() knows it's not an error
        if len(cases_data) == 0 and skipped_count > 0:
            logger.warning(
                "All records were skipped because they already exist. This is not an error."
            )
            return []

        return cases_data

    except requests.exceptions.Timeout:
        logger.error(f"Timeout error connecting to {EPA_ENFORCEMENT_PAGE}")
        return None
    except requests.exceptions.HTTPError as e:
        logger.error(f"HTTP error {e.response.status_code} for {EPA_ENFORCEMENT_PAGE}")
        return None
    except requests.exceptions.ConnectionError:
        logger.error(f"Connection error for {EPA_ENFORCEMENT_PAGE}")
        return None
    except requests.exceptions.RequestException as e:
        logger.error(f"Request error for {EPA_ENFORCEMENT_PAGE}: {e}")
        return None
    except Exception as e:
        logger.error(f"Unexpected error during EPA case scraping: {e}", exc_info=True)
        return None


def save_to_json(data: List[Dict], filename: str = OUTPUT_FILENAME):
    """
    Save the extracted data to a JSON file.

    Args:
        data: List of dictionaries to save
        filename: Name of the output file
    """
    try:
        # Create a wrapper dictionary with "documents" key
        wrapper = {"documents": data}

        ddev_root = os.environ.get("DDEV_ROOT")
        output_filename = os.path.join(ddev_root, filename)

        with open(output_filename, "w", encoding="utf-8") as f:
            json.dump(wrapper, f, indent=2, ensure_ascii=False)
        logger.info(f"Data successfully saved to {filename}")

    except IOError as e:  # Catch file I/O errors
        logger.error(f"Error saving to JSON file '{filename}': {e}")

    except TypeError as e:  # Catch JSON serialization errors
        logger.error(f"Error serializing data to JSON: {e}")

    except Exception as e:  # Catch any other unexpected errors during saving
        logger.error(f"Unexpected error saving JSON data: {e}", exc_info=True)

def deduplicate_federal_laws(federal_law_list):
    """
    Deduplicate a list of federal law dictionaries.
    
    Args:
        federal_law_list: List of dictionaries, each with 'type' and 'citation' keys
        
    Returns:
        A new list of dictionaries with duplicate laws removed
    """
    if not federal_law_list:
        return []
        
    # Use a set to track unique law combinations
    unique_laws = set()
    deduplicated_list = []
    
    for law in federal_law_list:
        # Create a tuple from the law's type and citation for uniqueness checking
        law_key = (law['type'], law['citation'])
        
        # Only add this law if we haven't seen it before
        if law_key not in unique_laws:
            unique_laws.add(law_key)
            deduplicated_list.append(law)
            
    return deduplicated_list

def flatten_federal_laws(federal_law_list):
    """
    Convert a list of federal law dictionaries into a flat comma-separated string,
    alphabetically sorted.

    Args:
        federal_law_list: List of dictionaries, each with 'type' and 'citation' keys

    Returns:
        A comma-separated string in the format "Type - Citation,Type - Citation,..."
        sorted alphabetically, or an empty string if the input is None or empty
    """
    if not federal_law_list:
        return ""

    flattened_laws = []
    for law in federal_law_list:
        flattened_laws.append(f"{law['type']} - {law['citation']}")

    # Sort the laws alphabetically before joining
    flattened_laws.sort()

    return ",".join(flattened_laws)


def determine_paragraph_count(text_length: int) -> int:
    """
    Determine the number of paragraphs for the summary based on text length.

    Args:
        text_length: Length of the text to analyze

    Returns:
        Recommended number of paragraphs
    """
    for i, threshold in enumerate(TEXT_LENGTH_THRESHOLDS):
        if text_length <= threshold:
            return DEFAULT_NUM_PARAGRAPHS[i]
    return DEFAULT_NUM_PARAGRAPHS[-1]  # Use the last value for very long texts


# ===== Main Function =====
def main():
    """Main entry point for the EPA scraper."""
    parser = argparse.ArgumentParser(description="EPA Enforcement Case Scraper")
    parser.add_argument(
        "-llm", default="gemini", type=str, help="The name of the LLM (default: gemini)"
    )
    parser.add_argument(
        "-numrecs",
        default=1,
        type=int,
        help="Number of records to process (default: 1)",
    )
    parser.add_argument(
        "-log",
        default="INFO",
        type=str,
        help="Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)",
    )
    args = parser.parse_args()

    # Set logging level based on argument
    log_level = getattr(logging, args.log.upper(), logging.INFO)
    logger.setLevel(log_level)

    logger.info(
        f"Starting EPA case scraper with LLM: {args.llm}, processing {args.numrecs} records"
    )

    cases_data = scrape_epa_cases(args.numrecs)
    if cases_data is None:
        logger.error("No cases data found. Scraping failed or no data available.")
        return

    if not cases_data:
        logger.info("No new cases to process - all cases were already in the database.")
        return

    for row in cases_data:
        logging.info(f"Processing {row['title']}")

        text_to_analyze = row.get("article_text", "")
        pdf_texts = row.get("pdf_texts", "")

        # Concatenate all texts for subsequent LLM analysis
        text_to_analyze += " " + pdf_texts

        if not row.get('title') or not text_to_analyze:
            logger.warning(f"Skipping {row['title']} due to empty text.")
            continue
        else:
            logger.info(f"Analyzing: {row['title']}")

        # Determine detail level based on text length
        text_len = len(text_to_analyze)
        num_paragraphs = determine_paragraph_count(text_len)
        logger.debug(f"Text length: {text_len}, using {num_paragraphs} paragraphs")

        system_message_updated = create_system_message(num_paragraphs)

        llm_response = None

        try:
            if args.llm == "openai" and len(text_to_analyze) < 100000:
                logger.info("Using OpenAI for analysis")
                llm = LLMFactory("openai")
            elif args.llm == "gemini" or len(text_to_analyze) > 99999:
                logger.info(
                    "Using Gemini for analysis (text length or user preference)"
                )
                llm = LLMFactory("gemini")
            else:
                logger.error(f"Unknown LLM: {args.llm}")
                sys.exit(1)  # Exit with error code for unknown LLM

            logger.info(f"Submitting text for analysis ({text_len} characters)")

            llm_response = llm.create_completion(
                response_model=LegalAnalysis,
                messages=[
                    {
                        "role": "user",
                        "content": f"""{system_message_updated}
                    Text to analyze:
                    {text_to_analyze}""",
                    },
                ],
            )
            logger.info(f"Successfully got response from LLM for {row['title']}")

        except ValueError as e:
            logger.error(f"LLM validation error for {row['title']}: {e}")
            continue
        except ConnectionError as e:
            logger.error(f"LLM connection error for {row['title']}: {e}")
            continue
        except Exception as e:
            logger.error(
                f"Unexpected error during LLM processing for {row['title']}: {e}",
                exc_info=True,
            )
            continue  # Move to the next case on LLM error

        if llm_response:  # Only process if LLM response was successful
            row["ai_tags"] = []

            # Add summary at the top level (summary is required by the model, so shouldn't be None)
            row["summary"] = f"<p class=\"infobox\">This article contains AI-generated summaries.</p><div>{llm_response.summary}</div>"
            row["ai_tags"].append("AI-Generated Text")

            # Only add penalty if it exists
            if llm_response.penalty is not None:
                row["penalty"] = llm_response.penalty

            # Add the environmental issues (if any)
            if llm_response.environmental_issues is not None:
                row["environmental_issues"] = llm_response.environmental_issues

            # If federal_law exists, add both the structured and flattened versions
            if llm_response.federal_law is not None:
                # Convert federal_law objects to dictionaries for JSON serialization
                federal_law_dicts = [
                    law.model_dump() for law in llm_response.federal_law
                ]
                
                # Deduplicate the federal laws
                deduplicated_laws = deduplicate_federal_laws(federal_law_dicts)
            
                # Add the structured version (deduplicated)
                if "laws" not in row:
                    row["laws"] = {}
                row["laws"]["federal_law"] = deduplicated_laws
            
                # Add the flattened version
                row["flattened_federal_laws"] = flatten_federal_laws(deduplicated_laws)
            else:
                row["flattened_federal_laws"] = ""

            if llm_response.penalty is not None or llm_response.federal_law is not None:
                row["ai_tags"].append("AI-Generated Entity Extraction")

            # Metadata tracking
            row["llm"] = llm.settings.default_model
            row["time"] = datetime.now().strftime("%a, %d %b %Y %H:%M:%S")
            logger.info(f"Added legal analysis data for {row['title']}")
        else:
            logger.warning(
                f"No valid LLM response received for {row['title']}. Skipping law extraction."
            )

        row["raw_text"] = row["article_text"] + " " + row["pdf_texts"]
        del row["article_text"]
        del row["pdf_texts"]

    save_to_json(cases_data)
    logger.info("Data processing complete")


if __name__ == "__main__":
    main()
