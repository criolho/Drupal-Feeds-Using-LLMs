# Drupal Feeds Using LLMs
How to generate JSON feeds enhanced with LLMs for import to Drupal.  This repo demonstrates two scrapers, one that interacts with the Federal Register API and the other which scrapes an EPA web page. 

## Federal Register

<img width="507" alt="image" src="https://github.com/user-attachments/assets/a53fde11-4b4a-40de-beaa-4ea1a0c05002" />


- Site:  https://federalregister.gov
- Background:  This is where the U.S. government publishes all proposed federal regulations or rules about to go into effect.  The site has an excellent UI and is also known for its developer-friendly API and JSON output.
- Goals:  connect to Federal Register API and get JSON metadata for recently-published rules.  Then:
  * Make minor transformations to their field data for our matching fields in Drupal, e.g. prepending a citation to their title to match our Drupal node title best practices
  * Add 3 LLM-generated summaries individually focused on the needs of:  1) high school students, 2) corporate lobbyists, 3) environmental activists.
<br><br><br>
### Federal Register processing pipeline

High level overview of the data processing game plan:

<img width="468" alt="image" src="https://github.com/user-attachments/assets/b8cb0187-b44b-4c2a-87f2-bc8667b31fe5" />
<br><br><br>

### Inputs and Outputs

Federal Register developer interactive API:
https://www.federalregister.gov/developers/documentation/api/v1#/Federal%20Register%20Documents/get_documents__format_

Federal Register JSON request for the EPA:
https://www.federalregister.gov/api/v1/documents.json?fields[]=abstract&fields[]=type&fields[]=pdf_url&fields[]=document_number&fields[]=publication_date&fields[]=agencies&fields[]=title&per_page=3&conditions[publication_date][gte]=2025-03-01&conditions[agencies][]=environmental-protection-agency&conditions[type][]=RULE&conditions[type][]=PRORULE

<img width="692" alt="image" src="https://github.com/user-attachments/assets/009a96c0-96d5-462a-98fd-ae54edf7dbba" />

<br>
### Drupal

On the Drupal side of things we have a content type Federal Register that has matching fields:

<img width="778" alt="Screenshot 2025-03-16 at 4 09 45 AM" src="https://github.com/user-attachments/assets/b43c9eb2-e664-4a10-bda1-977a28093c36" />


<br><br><br>






## Civil Enforcement Actions by the EPA

<img width="590" alt="image" src="https://github.com/user-attachments/assets/5cc4f8e8-fe52-4d3a-bf11-eea32954ee97" />


- Site:  https://www.epa.gov/enforcement/civil-and-cleanup-enforcement-cases-and-settlements
- Background:  Centralized source for EPA civil actions for violations.  The EPA [historically] enforces a wide range of environmental laws, including the Clean Air Act (CAA) and Clean Water Act (CWA).
- Goals:
  * Better summaries
  * Extract penalty info
  * What specific laws were violated?
  * Categorize environmental issues
 
## Inputs and Outputs

<img width="700" alt="image" src="https://github.com/user-attachments/assets/fa91cdb2-37c5-4001-b355-f069c96501ae" />


### LLM Considerations

Closed models, open source – they’re constantly leapfrogging one another.  At present, closed source foundation models produce more **reliable structured output**.  This may change in the future.

The code here has options for OpenAI’s “gpt-4o”, Anthropic’s "claude-3-7-sonnet-latest" and Google’s “gemini-2.0-flash”.  Currently we default to **Gemini Flash** because it is fast, reliable, inexpensive (as of March 2025:   input $0.10 / 1,000,000 input tokens, $0.40 / 1,000,000 output tokens) and has a long context window (1,000,000 tokens) that can readily accommodate multi-hundred page PDFs.
**Optimization** – a custom title_exists() function checks to see if we already have a node in Drupal, saving on unnecessary LLM calls

### Pydantic and Instructor

Two Python libraries aid greatly in steering and validating the output of LLMs: 

- Pydantic ensures that data meets certain criteria before being sent downstream.   It’s used in many contexts, not just with LLMs.  For example, in validating inputs to an API or outputs to a database.  A key feature for LLM usage is that Pydantic allows you to define a “data model” with rich annotations suitable for use with the Instructor library.
- Instructor helps steer LLMs toward a desired behavior.  In particular, you can take a deeply annotated Pydantic model and use it to provide detailed prompt instructions to an LLM, then verify that the return data from the LLM conforms to your expectations. 

Together, these libraries help us to tell LLMs precisely how we want them to structure their reply, e.g. JSON with particular fields and types of data; and validate the data before passing it on for downstream use.  In particular, we want anything GenAI-related to pass muster before importing it to Drupal.


<img width="679" alt="image" src="https://github.com/user-attachments/assets/9637a017-3e3a-4875-9293-8648a445a8b1" />


### Pydantic Field validators

These are optional functions you can write that automatically run against fields before Pydantic signs off on the data.  You can use them to simply confirm that data matches certain criteria, or you can modify the data to conform your needs.  The point is that this is a structured way of enforcing standards for your data.

What we’re choosing to validate:

- **citation** – make sure legal citations are in a standardized format, e.g. 40 C.F.R. §§ Part 1039" should be transformed to "40 C.F.R. § 1039
- **penalty** – make sure it’s a numeric float with at most 2 decimal places
- **environmental_issues** – suppose we have a Drupal taxonomy we’re already using.  We can fetch the terms dynamically from the Drupal DB and use them both to tell the LLM what terms we want it to look for and then to make sure that’s what it did.

### Miscellaneous “Best Practices”

There are few “standards” yet for how websites should manage AI-generated content.  You may want to consider:

- Creating a vocabulary “AI Tags” to help you keep track of nodes to which you’ve applied GenAI.  For example:  AI-Generated Text, AI-Generated Categories, or AI-Generated Entity Extraction
- It is quite likely that you’ll use different LLMs over time.  You may want to have a vocabulary for these as well with terms such as:  claude-3-7-sonnet-latest, gpt-4o, gpt-4o-mini, gemini-2.0-flash
- If you’re going to the trouble of extracting lots of raw text for use in GenAI, even though in its raw state it may not be suitable for end users it might be good for a) fulltext search; b) future GenAI passes over the same nodes
- People are justifiably wary of what’s being pushed on them – consider including preamble / info text such as “This article contains an AI-generated summary” that fully informs people what they’re getting.

## To Run the Scrapers

1. You need Python 3.12 or higher
2. Create a new virtual env
3. Install requirements
4. Run scrapers
```
python -m venv feeds_scraper
source feeds_scraper/bin/activate
pip install -r requirements.txt
python epa.py
python fr.py -a epa -d 2024-10-01
```
