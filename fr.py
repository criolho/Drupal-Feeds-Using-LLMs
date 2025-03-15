#!/usr/bin/env python

from ai_utils import title_exists
from bs4 import BeautifulSoup
from config.agency_settings import get_settings, AgencySettings
from datetime import datetime
from dotenv import load_dotenv
from llm_factory import LLMFactory
from pydantic import BaseModel, Field
from time import sleep
from typing import Optional
import argparse
import json
import logging
import os
import pandas as pd
import re
import requests
import sys

load_dotenv()


# ===== Set up logging =====
def setup_logging(log_level=logging.INFO):
    """Configure logging for the application."""
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s - %(levelname)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        # Write to log and to console if desired
        handlers=[logging.FileHandler("/var/ai/fr.log"), logging.StreamHandler()],
    )

    # Reduce verbosity of external libraries
    logging.getLogger("requests").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)

    return logging.getLogger(__name__)


# Initialize logger
logger = setup_logging()


class NewsSummaryModel(BaseModel):
    """
    Pydantic model for generating a simple news summary.
    """
    summary: str = Field(description="Summary of several news stories in the form of one or more HTML paragraphs")

class SummaryModel(BaseModel):
    """
    Pydantic model for generating different types of summaries.
    """

    high_school_summary: str = Field(description="Concise summary for high school students")
    lobbyist_summary: str = Field(description="Detailed summary for lobbyists")
    activist_summary: str = Field(description="Detailed summary for activists")


def get_agency_settings(agency_name: str) -> AgencySettings:
    """
    Retrieves agency settings by name.

    Args:
        agency_name: Agency name (FR name or short name).

    Returns:
        AgencySettings: Settings for the agency.
    """
    settings = get_settings()
    agency_settings = settings.get_agency_by_name(agency_name)
    if agency_settings is None:
        logger.error(
            f"No settings found for agency '{agency_name}'. Available agencies:"
        )
        for (
            agency
        ) in settings.__dict__.values():  # Directly iterate through agency settings
            if isinstance(agency, AgencySettings) and agency.short_name:
                logger.error(f"  - {agency.short_name} ({agency.name})")
        sys.exit(1)
    return agency_settings


def format_federal_register_url(agency_settings: AgencySettings, date: str) -> str:
    """
    Formats the Federal Register URL.

    Args:
        agency_settings: Agency settings.
        date: Date in YYYY-MM-DD format.

    Returns:
        str: Formatted URL.
    """
    url = agency_settings.federal_register_url.replace(
        "FR_AGENCY_NAME", agency_settings.fr_agency_name
    )
    url = url.replace("DATE_PLACEHOLDER", date)
    return url


def fetch_fr_data(url: str) -> dict:
    """
    Fetches JSON data from the Federal Register API.

    Args:
        url: The URL to fetch.

    Returns:
        dict: JSON data as a dictionary.
    """
    try:
        response = requests.get(url)
        response.raise_for_status()  # Raise HTTPError for bad responses (4xx or 5xx)
        return response.json()

    except requests.exceptions.RequestException as e:
        logger.error(f"Error fetching FR data from {url}: {e}")
        sys.exit(1)

    except json.JSONDecodeError as e:
        logger.error(f"Error decoding JSON response from FR API: {e}")
        sys.exit(1)


def process_fr_data(data: dict) -> pd.DataFrame:
    """
    Processes the fetched Federal Register data into a Pandas DataFrame.
    Args:
        data: JSON data from Federal Register API.
    Returns:
        pd.DataFrame: DataFrame containing processed data.
    """
    results = data.get("results", [])
    if not results:
        logger.warning("No results found in FR data.")
        return pd.DataFrame()  # Return empty DataFrame instead of exiting

    df = pd.json_normalize(
        results,
        record_path=None,
        meta=[
            "abstract",
            "citation",
            "effective_on",
            "document_number",
            "pdf_url",
            "body_html_url",
            "title",
            "type"
        ],
        errors="ignore",
    )

    # Keep track of rows to delete if a given record title is already in Drupal
    rows_to_delete = []

    for record_idx, record in enumerate(results):
        df.at[record_idx, "agency_names"] = ",".join(record.get("agency_names", []))

        df.at[record_idx, "abstract"] = f'<p>{df.at[record_idx, "abstract"]}</p><p class=\"infobox\">This article contains AI-generated summaries.</p>'

        # Process title for each record individually
        if "citation" in df.columns and "title" in df.columns:
            df.at[record_idx, "citation"] = df.at[record_idx, "citation"].strip()
            df.at[record_idx, "title"] = df.at[record_idx, "title"].strip()
            df.at[record_idx, "title"] = (
                df.at[record_idx, "citation"] + " - " + df.at[record_idx, "title"]
            )
            node_title = df.at[record_idx, "title"]

            if title_exists(node_title):
                logger.warning(f"Skipping {node_title} as it already exists")
                # Mark this row for deletion
                rows_to_delete.append(record_idx)
            else:
                logger.info(f"Processing {node_title}")

    # Remove all rows that have existing titles
    if rows_to_delete:
        df = df.drop(rows_to_delete)
        # Reset index after dropping rows so we don't have gaps due to deletions
        df = df.reset_index(drop=True)

    return df


def clean_article_text(html_content: str) -> str:
    """
    Cleans HTML article text using BeautifulSoup.

    Args:
        html_content: HTML content of the article.

    Returns:
        str: Cleaned article text.
    """
    soup = BeautifulSoup(html_content, "html.parser")
    doc_headings = soup.find("div", class_="document-headings")
    if doc_headings:
        doc_headings.decompose()
    article_text = soup.get_text(separator=" ", strip=True)
    article_text = (
        article_text.replace("\n", " ")
        .replace("\u2003", " ")
        .replace("\u2009", " ")
        .replace("\u200b", "")
    )
    article_text = re.sub(r" {3,}", " ", article_text)
    return article_text


def fetch_and_clean_article_text(url: str) -> Optional[str]:
    """
    Fetches HTML from a URL and cleans the article text.

    Args:
        url: URL of the article.

    Returns:
        Optional[str]: Cleaned article text, or None if fetching fails.
    """
    try:
        sleep(1)  # Keep sleep for rate limiting
        response = requests.get(url)
        response.raise_for_status()
        return clean_article_text(response.text)
    except requests.exceptions.RequestException as e:
        logger.error(f"Error fetching article from {url}: {e}")
        return None


def generate_summaries(llm, system_message: str, article_text: str) -> Optional[SummaryModel]:
    """
    Generates summaries using the LLM.

    Args:
        llm: Initialized LLMFactory instance.
        system_message: System message for the LLM.
        article_text: Text of the article to summarize.

    Returns:
        Optional[SummaryModel]: SummaryModel object, or None if LLM processing fails.
    """
    try:
        llm_response = llm.create_completion(
            response_model=SummaryModel,
            messages=[
                {
                    "role": "user",
                    "content": f"""{system_message}\nText to analyze:\n{article_text}""",
                },
            ],
        )
        return llm_response
    except (
        Exception
    ) as e:  # Consider more specific LLM exceptions if possible from your LLMFactory
        logger.error(f"Error during LLM processing: {e}")
        return None


def save_results(df: pd.DataFrame, agency_settings: AgencySettings):
    """
    Saves the DataFrame to a JSON file structured as {"documents": [{...}, {...}]}.

    Args:
        df: DataFrame to save.
        agency_settings: Agency settings object.
    """

    """
    Convert DataFrame to a list of dictionaries.  orient='records' converts 
    each row of the DataFrame into a dictionary where the column names are 
    the keys
    """
    documents = df.to_dict(orient="records")

    # Create the output structure
    output_data = {"documents": documents}

    output_filename = os.path.join(os.environ.get("DDEV_ROOT"), "fr.json")

    with open(output_filename, "w", encoding="utf-8") as f:
        json.dump(output_data, f, indent=2)

    logger.info(f"FR data saved to {output_filename}")

def add_paragraph_tags(text: str) -> str:
    """
    Examines a string and if it has no <p> tags:
    1. Prepends with <p>
    2. Appends with </p>
    3. Replaces \n\n with </p><p> throughout
    
    Args:
        text (str): The input string to process
    
    Returns:
        str: The processed string with paragraph tags
    """
    # Check if the string already contains paragraph tags
    if "<p>" in text or "</p>" in text:
        return text
    
    # Extract just the body content if needed
    if '"body":' in text:
        # Find the actual content between quotes after "body":
        import re
        match = re.match(r'"body": "(.*)"$', text)
        if match:
            content = match.group(1)
        else:
            content = text
    else:
        content = text
    
    # Add paragraph tags
    # 1. Replace \n\n with </p><p>
    content_with_tags = content.replace("\n\n", "</p><p>")
    
    # 2. Prepend with <p> and append with </p>
    result = f"<p>{content_with_tags}</p>"
    
    # If we extracted from a "body" field, put it back in that format
    if '"body":' in text:
        return f'"body": "{result}"'
    else:
        return result

def track_date_range(date_strings):
    # Initialize with None to handle empty lists
    oldest_date = None
    newest_date = None
    
    for date_str in date_strings:
        # Parse the string to a datetime object
        current_date = datetime.strptime(date_str, "%Y-%m-%d")
        
        # For the first date in the list
        if oldest_date is None or newest_date is None:
            oldest_date = current_date
            newest_date = current_date
        else:
            # Update oldest date if current date is older
            if current_date < oldest_date:
                oldest_date = current_date
            
            # Update newest date if current date is newer
            if current_date > newest_date:
                newest_date = current_date
    
    # Convert back to string format
    oldest_date_str = oldest_date.strftime("%Y-%m-%d") if oldest_date else None
    newest_date_str = newest_date.strftime("%Y-%m-%d") if newest_date else None
    
    return oldest_date_str, newest_date_str

def overview(df: pd.DataFrame, llm: LLMFactory, agency_settings: AgencySettings, start_date: str):
    '''
    Writes a simple review article given a list of news items
    '''
    request_data = ""
    for index, row in df.iterrows():
        title = row['title']
        date = row['publication_date']
        abstract = row['abstract']
        activist_summary = row['activist_summary']
       
        request_data += f"Title: {title}\nDate: {date}\nFederal Register Abstract: {abstract}\nActivist Summary: {activist_summary}\n\n"
 
    request_data = re.sub(r'<.*?>', '', request_data)
    system_message = f"Review the following {len(df)} articles from the federal register.  You should write an engaging news-like summary with any highlights or trends.  Provide specific details, cite individual federal registers and dates and discuss deeper implications. Output as 4 HTML paragraphs using only <p> tags with no line breaks within the HTML string. Do not use <html>, <head>, or <body> tags. Put bold <b> tags around this non-exclusive list of words of interest to activists: Environmental Impact Terms: Environmental contamination, Ecosystems, Public health, Climate change, Air pollution, Hazardous air pollutants, Environmental protection.  Advocacy Terms: Advocate, Push for, Demand, Mobilize, Scrutinize, Challenge, Voice concerns.  Social Justice Terms: Vulnerable populations, Environmental justice, Community involvement, Transparency, Accountability, Public access.  Specific Environmental Concerns: Emissions, Acid rain, Respiratory problems, Smog, Monitoring, Long-term effects, Non-target organisms, Soil health.  "

    try:
        llm_response = llm.create_completion(
            response_model=NewsSummaryModel,
            messages=[
                {
                    "role": "user",
                    "content": f"""{system_message}\nText to analyze:\n{request_data}""",
                },
            ],
        )

        # Figure out oldest and newest dates so we can include them in the title
        all_dates = []
        for index, row in df.iterrows():
            date = row['publication_date']
            all_dates.append(date)

        # Find oldest and newest dates
        oldest, newest = track_date_range(all_dates)
    
        # Format dates in a readable format (February 28, 2025)
        oldest_formatted = datetime.strptime(oldest, "%Y-%m-%d").strftime("%B %d, %Y") if oldest else ""
        newest_formatted = datetime.strptime(newest, "%Y-%m-%d").strftime("%B %d, %Y") if newest else ""

        ddev_root = os.environ.get("DDEV_ROOT")
        output_filename = os.path.join(os.environ.get("DDEV_ROOT"), "fr_news.json")

        # Create title based on whether oldest and newest dates are the same
        if oldest == newest:
            title = f"{agency_settings.name} Regulatory Review from {oldest_formatted}"
        else:
            title = f"{agency_settings.name} Regulatory Review from {oldest_formatted} to {newest_formatted}"
        
        data = {
            "title": title,
            "ai_tags": "AI-Generated Text",
            "summary": add_paragraph_tags(llm_response.summary)
        }

        # Create a wrapper dictionary with "documents" key
        wrapper = {"documents": data}

        with open(output_filename, "w", encoding="utf-8") as f:
            json.dump(wrapper, f, indent=2, ensure_ascii=False)

        logger.info(f"News summary saved to {output_filename}")
    except (
        Exception
    ) as e:  # Consider more specific LLM exceptions if possible from your LLMFactory
        logger.error(f"Error during LLM processing: {e}")
        return None



def main():
    today = datetime.now().strftime("%Y-%m-%d")
    parser = argparse.ArgumentParser(
        description="Fetch Federal Register data and generate summaries."
    )
    parser.add_argument("-a", "--agency", type=str, required=True, help="Agency name")
    parser.add_argument(
        "-d", "--date", type=str, default=today, help="Start date (YYYY-MM-DD)"
    )
    parser.add_argument(
        "-l",
        "--llm",
        type=str,
        default="gemini",
        choices=["gemini", "openai", "anthropic"],
        help="LLM provider",
    )
    # Write summary over all results?
    parser.add_argument('-n', '--news', action='store_true', help='Write news overview')

    args = parser.parse_args()
    news_overview = 1 if args.news else 0
        
    try:
        datetime.strptime(args.date, "%Y-%m-%d")  # Date validation is good here
    except ValueError:
        logger.error(f"Error: Date must be in YYYY-MM-DD format. Got: {args.date}")
        sys.exit(1)

    llm = LLMFactory(args.llm)
    logger.info(f"Using LLM provider: {args.llm}")

    agency_settings = get_agency_settings(args.agency)
    logger.info(f"Processing data for {agency_settings.name} from {args.date} on")

    fr_url = format_federal_register_url(agency_settings, args.date)
    fr_data = fetch_fr_data(fr_url)
    df = process_fr_data(fr_data)

    if df.empty:  # Handle empty DataFrame from process_fr_data gracefully
        logger.info(f"No results to process for {agency_settings.name} on {args.date}.")
        sys.exit(0)

    logger.info(f"Found {len(df)} results")

    system_message = f"""
    You are a helpful assistant knowledgeable about the {agency_settings.name}. Summarize the following text in three different styles:

    1. FOR HIGH SCHOOL STUDENTS (150-200 words): Create a concise summary using simple, straightforward language. Avoid technical jargon, define any necessary terms, and focus on explaining why this matters to everyday people and the environment.
    2. FOR CORPORATE LOBBYISTS (250-300 words): Create a detailed summary emphasizing business implications and regulatory impact. Use blunt language indicating actionables. Focus on compliance requirements, timelines, costs, and potential business opportunities or challenges.
    3. FOR ENVIRONMENTAL ACTIVISTS (250-300 words): Create a detailed summary emphasizing environmental concerns and advocacy points with regard to the rule changes being discussed. Highlight potential impacts on ecosystems, public health, and climate, as well as areas where the regulation could be strengthened.

    Each summary should be formatted as HTML using only <p> tags with no line breaks within the HTML string. Do not use <html>, <head>, or <body> tags. Focus on the most important information from the text.  Do not mention specific dates, e.g . Effective or Comment dates, that isn't useful info. Do put HTML bold tags <b> around keywords such as this non-exclusive list:  Of interest to lobbyists:  Regulatory Terms: Compliance, Regulation, Requirements, Implementation, Standards, Tolerances, Exemption, Permitting, Primacy

Economic/Business Terms: Costs, Operational impacts, Economic implications, Business operations, Competitive advantage, Market expansion, Supply chains, Streamlining, Burden reduction

Action-Oriented Terms: Comment period, Opportunities to engage, Prepare and submit comments, Influence the final rule, Compliance strategy, Actionable items

Industry-Specific: State Implementation Plan (SIP), National Emission Standards, Class VI wells, Pesticide tolerances, Biopesticide, Confidential Business Information (CBI)

Words of Interest to Activists:

Environmental Impact Terms: Environmental contamination, Ecosystems, Public health, Climate change, Air pollution, Hazardous air pollutants, Environmental protection

Advocacy Terms: Advocate, Push for, Demand, Mobilize, Scrutinize, Challenge, Voice concerns

Social Justice Terms: Vulnerable populations, Environmental justice, Community involvement, Transparency, Accountability, Public access

Specific Environmental Concerns: Emissions, Acid rain, Respiratory problems, Smog, Monitoring, Long-term effects, Non-target organisms, Soil health

    If the input text is highly technical, ensure you translate complex concepts into accessible language appropriate for each audience. Prioritize explaining the practical impact of the regulation over procedural details.
If there isn't sufficient information in the text to create a meaningful summary for one of the audiences, indicate this briefly but still provide the best possible summary with the available information.
Your response MUST be valid JSON conforming to this schema:

```json
    {json.dumps(SummaryModel.model_json_schema(), indent=2)}
"""

    # Initialize columns before loop for clarity
    df["article_text"] = None
    df["high_school_summary"] = None
    df["lobbyist_summary"] = None
    df["activist_summary"] = None

    # Iterate through dataframe, get texts to analyze and add LLM-generated summaries
    for index, row in df.iterrows():
        article_text = fetch_and_clean_article_text(row["body_html_url"])

        if article_text:  # Proceed only if article text was fetched and cleaned
            df.at[index, "article_text"] = article_text
            logger.info(
                f"Processing document {index + 1}/{len(df)}: {row['document_number']}"
            )
            llm_response = generate_summaries(llm, system_message, article_text)

            if llm_response:
                # Metadata tracking
                df["llm"] = llm.settings.default_model
                df["ai_tags"] = "AI-Generated Text"
                df["time"] = datetime.now().strftime("%a, %d %b %Y %H:%M:%S")

                # Summaries
                df.at[index, "high_school_summary"] = llm_response.high_school_summary
                df.at[index, "lobbyist_summary"] = llm_response.lobbyist_summary
                df.at[index, "activist_summary"] = llm_response.activist_summary

                logger.info("Generated summaries successfully")

    save_results(df, agency_settings)

    if news_overview:
        overview(df, llm, agency_settings, args.date)

if __name__ == "__main__":
    main()
