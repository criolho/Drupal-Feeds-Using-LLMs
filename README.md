# Drupal Feeds Using LLMs

If you regularly bring data into Drupal from external sources, you may be able to enrich the data using LLMs and a bit of custom programming.  This repo demos a workflow utilizing Python scripts running on a Linux server, web scraping, LLMs and the Drupal Feeds module.  Your tech stack may be different but the techniques discussed in this talk are easily translated to other environments.

The repo demonstrates two scrapers, one that interacts with the Federal Register API and the other which scrapes an EPA web page. The scrapers output JSON suitable for Drupal feeds import.

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

<br><br><br>
### Drupal

On the Drupal side of things we have a content type Federal Register that has matching fields:

<img width="778" alt="Federal Register Content Type" src="https://github.com/user-attachments/assets/b43c9eb2-e664-4a10-bda1-977a28093c36" />

<br><br><br>
And our Federal Register Feed that will consume our JSON output looks like this:

<img width="1272" alt="Federal Register Feed" src="https://github.com/user-attachments/assets/af23c4ad-fec2-4d1c-8cc2-81fc13372f6f" />



<br><br><br>

### News Meta-summary

We can also have our script create a News summary that iterates over all the Federal Registers we are importing and ask the LLM to summarize all the other summaries, a kind of meta-summary.  This should not be published as is – that’s “cheating” – but it could certainly form the skeleton on which a human editor could build.  Imagining we are using a simple Drupal "Article" content type we might see:


<br><br>


<img width="837" alt="News Metasummary" src="https://github.com/user-attachments/assets/1f02178e-375f-4905-952c-eb45f90c60a1" />

<br><br>

### Sample Federal Register

After importing here's what a sample FR looks like:

<img width="1035" alt="sample federal register" src="https://github.com/user-attachments/assets/a155ab4f-3aec-4b4a-a84a-7e9b00ed3a6d" />




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

## Document content type we’ll be using for the EPA Civil Actions and its associated Feed

<img width="904" alt="Document Content Type" src="https://github.com/user-attachments/assets/5f119ce4-a5ae-4c55-b28a-468cfd76381c" />

<br><br>

<img width="1134" alt="Document Feed" src="https://github.com/user-attachments/assets/953fe2e1-4859-46da-98f2-419f5b14d1cb" />
<br><br><br>

## Drupal Taxonomies

Here are the sample vocabularies and terms used in the project.  Note that we dynamically import the Environmental Issues tags to our Python code at runtime, add them to our Pydantic model and use them as part of our prompt to the LLM to shape its behavior (“categorize documents according to these tags, and only these tags”).

<img width="1201" alt="Drupal Taxonomies" src="https://github.com/user-attachments/assets/2dddaa31-b301-4009-8bb6-0d1c753f0ac0" />

<br><br><br>
## Example civil action Document import:

<img width="914" alt="EPA Civil Action document example" src="https://github.com/user-attachments/assets/897a7a19-af5a-4e92-89dd-533cf4fcd709" />



<br><br><br>
### LLM Considerations

Closed models, open source – they’re constantly leapfrogging one another.  At present, closed source foundation models produce more **reliable structured output**.  This may change in the future.

The code here has options for OpenAI’s “gpt-4o”, Anthropic’s "claude-3-7-sonnet-latest" and Google’s “gemini-2.0-flash”.  Currently we default to **Gemini Flash** because it is fast, reliable, inexpensive (as of March 2025:   input $0.10 / 1,000,000 input tokens, $0.40 / 1,000,000 output tokens) and has a long context window (1,000,000 tokens) that can readily accommodate multi-hundred page PDFs.

<br><br>
**Optimization** – a custom title_exists() function checks to see if we already have a node in Drupal; if so, we avoid making unnecessary LLM calls.  This is essential when performing web scraping at scale.

### Pydantic and Instructor

Two Python libraries aid greatly in steering and validating the output of LLMs: 

- [Pydantic](https://docs.pydantic.dev/latest/) ensures that data meets certain criteria before being sent downstream.   It’s used in many contexts, not just with LLMs.  For example, in validating inputs to an API or outputs to a database.  A key feature for LLM usage is that Pydantic allows you to define a “data model” with rich annotations suitable for use with the Instructor library.
- [Instructor](https://python.useinstructor.com/) helps steer LLMs toward a desired behavior.  In particular, you can take a deeply annotated Pydantic model and use it to provide detailed prompt instructions to an LLM, then verify that the return data from the LLM conforms to your expectations. 

These libraries help us to tell LLMs precisely how we want them to structure their reply, e.g. JSON with particular fields and types of data; and validate the data before passing it on for downstream use.  In particular, we want anything GenAI-related to pass muster before importing it to Drupal.  Drupal, which is all about structured content, does well by partnering with a robust framework for getting structured output from LLMs.

Here are the models used for the EPA scraper:

<img width="679" alt="image" src="https://github.com/user-attachments/assets/9637a017-3e3a-4875-9293-8648a445a8b1" />


### Pydantic Field validators

These are optional functions you can write that automatically run against fields before Pydantic signs off on the data.  You can use them to simply confirm that data matches certain criteria, or you can modify the data to match your needs.  The point is that this is a structured way of enforcing standards for your data.

What we’re choosing to validate:

- **citation** – make sure legal citations are in a standardized format, e.g. 40 C.F.R. §§ Part 1039" should be transformed to "40 C.F.R. § 1039
- **penalty** – make sure it’s a numeric float with at most 2 decimal places
- **environmental_issues** – suppose we have a Drupal taxonomy we’re already using.  We can fetch the terms dynamically from the Drupal DB and use them both to tell the LLM what terms we want it to look for and then to make sure that’s what it did.

### Miscellaneous “Best Practices”

There are few “standards” yet for how websites should manage AI-generated content.  You may want to consider:

- Creating a vocabulary “AI Tags” to help you keep track of nodes to which you’ve applied GenAI.  For example:  AI-Generated Text, AI-Generated Categories, or AI-Generated Entity Extraction
- It is quite likely that you’ll use different LLMs over time.  You may want to have a vocabulary for these as well with terms such as:  claude-3-7-sonnet-latest, gpt-4o, gpt-4o-mini, gemini-2.0-flash
- If you’re going to the trouble of extracting lots of raw text for use in GenAI, even though in its raw state it may not be suitable for end users it might be good for a) fulltext search; b) future GenAI passes over the same nodes
- People are justifiably wary of what’s being pushed on them – consider including preamble / disclaimer text such as “This article contains an AI-generated summary” that fully informs people what they’re getting.
- It's possible that Drupal isn't the right place to perform auditing and bookkeeping.  In the examples presented here note that we're using LLMs at the Drupal field level - whereas the "AI Tags" as applied in these examples are assigned at the node level.  Having field-level tags for tracking AI may be a bit much to do within Drupal itself and an external auditing database may be a better bet (you might also wish to store the raw text blobs from PDFs externally as well so the Drupal DB doesn't bloat unnecessarily).  Or not - there are no best practices yet but it's worth keeping in mind the idea of field-level auditing of LLM usage.  Drupal is noteworthy precisely because of its structured approach to data, including fields, and we may want to respect (and take advantage of) that affordance of granularity when considering an LLM usage audit strategy.

## To Run the Scrapers

Note that these are barebones scrapers that only pull content from the first page of results.  A fully-fledged scraping process would involve paging.  That isn't the focus of this repo but the underlying code can readily be extended to accommodate paging.

1. You need Python 3.12 or higher
2. Create a new virtual env
3. Install requirements
4. Set env variables, e.g. use a .env file.  You’ll also need an API key for whatever LLMs you choose to you.  Then set an env variable such as OPENAI_KEY, GEMINI_KEY, ANTHROPIC_KEY, etc.
5. Run scrapers
```
# Example .env file:
DB_HOST=127.0.0.1
DB_PORT=49677
DB_USER=db
DB_PASSWORD=db
DB_NAME=db


# Set up virtual environment, activate it and install prerequisites:
python -m venv feeds_scraper
source feeds_scraper/bin/activate
pip install -r requirements.txt

# Run fr scraper for agency = EPA (see config/agencies.json file) retrieve Federal Registers dating 3/1/25 or later and generate a news summary.

python fr.py -a epa -d 2025-03-01 -n

# Grab first 5 rows of EPA enforcement actions
python epa.py -numrecs 5
```
