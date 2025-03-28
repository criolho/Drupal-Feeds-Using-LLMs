## Simple techniques

Grab a web page with curl and select the HTML of interest (automatically discards the cruft), then summarize it - all from the command line.  A shout out to Simon Willison:  https://simonwillison.net/2023/May/18/cli-tools-for-llms.

### Simple summarization prompt
`curl -s https://www.epa.gov/enforcement/turn-14-clean-air-act-settlement-summary
  | strip-tags .article
  | llm --system "Summarize legal points, penalty, and laws violated"`

### Summarization prompt where we ask for JSON

`curl -s https://www.epa.gov/enforcement/turn-14-clean-air-act-settlement-summary 
  | strip-tags .article 
  | llm --system "Summarize legal points, penalty, and laws violated.  Output as JSON."`

### Summarization prompt where we ask for JSON without markdown

`curl -s https://www.epa.gov/enforcement/turn-14-clean-air-act-settlement-summary 
  | strip-tags .article 
  | llm --system "Summarize legal points, penalty, and laws violated.  Output as JSON but don't use any markdown."`

  ### Summarization prompt where we refine our field request

`curl -s https://www.epa.gov/enforcement/turn-14-clean-air-act-settlement-summary 
  | strip-tags .article 
  | llm --system "Summarize legal points, penalty, and laws violated.  Output as JSON but don't use markdown.  The Penalty, if any, should be shown as a simple dollar value without any other text."`

  ### Further work

  Of course we could continue to refine this shell pipeline but at some point - depending on how precise and detailed your needs - it may make sense to move to a full-powered language like Python.  Simon Willison continues to refine his shell tool llm, though, and now supports schema templates, not unlike Pydantic:  https://simonwillison.net/2025/Feb/28/llm-schemas.
