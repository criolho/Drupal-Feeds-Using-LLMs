# Model providers
from anthropic import Anthropic
from openai import OpenAI
import google.generativeai as genai

from config.llm_settings import get_settings  # Import settings from config module
from pydantic import BaseModel                # For defining structured data models
from typing import Any, Dict, List, Type      # Type hints for better code readability
import instructor

class LLMFactory:
    """
    Factory class that provides a unified interface to different LLM providers (for now 
    OpenAI, Anthropic, Google's Gemini) with structured output support via instructor.
    """

    def __init__(self, provider: str):
        """
        Initialize the LLM client for the specified provider.
        
        Args:
            provider (str): The LLM provider to use - "openai", "anthropic", or "gemini"
        """
        self.provider = provider

        # Get the settings for this specific provider from our config
        self.settings = getattr(get_settings(), provider)

        # Initialize the appropriate client
        self.client = self._initialize_client()

    def _initialize_client(self) -> Any:
        """
        Initialize and return the appropriate client for the selected provider.
        Each provider requires different initialization parameters.
        
        Returns:
            An instructor-patched client for the selected provider
        """
        if self.provider == "openai":
            # For OpenAI, we just need to patch their client with instructor
            return instructor.from_openai(OpenAI())
        
        elif self.provider == "anthropic":
            # Similar approach for Anthropic
            return instructor.from_anthropic(Anthropic())
        
        elif self.provider == "gemini":
            # Gemini requires more configuration up front
            # Configure the API with our key
            genai.configure(api_key=self.settings.api_key)

            # Gemini is different - it needs temperature and token limits
            # specified during model creation, not during completion
            gemini_model = genai.GenerativeModel(
                model_name=self.settings.default_model,
                generation_config={
                    "temperature": self.settings.temperature,
                    # Gemini uses "max_output_tokens" instead of "max_tokens"
                    "max_output_tokens": self.settings.max_tokens
                }
            )

            # Patch with instructor in Gemini JSON mode and include a func to deal with Markdown
            return instructor.from_gemini(
                client=gemini_model,
                mode=instructor.Mode.GEMINI_JSON
            )
        else:
            # Raise error for unsupported providers
            raise ValueError(f"Unsupported LLM provider: {self.provider}")

    def create_completion(self, response_model: Type[BaseModel], messages: List[Dict[str, str]], **kwargs) -> Any:
        """
        Create a completion with the selected LLM provider and return structured output.
        
        Args:
            response_model (Type[BaseModel]): Pydantic model defining the structure of the expected response
            messages (List[Dict[str, str]]): List of message dictionaries (role/content pairs)
            **kwargs: Additional parameters to pass to the completion method
            
        Returns:
            An instance of the response_model populated with the LLM's response
        """
        # Set up completion parameters common to all providers
        completion_params = {
            "response_model": response_model,  # The structured output model
            "messages": messages,              # The conversation context
            "max_retries": kwargs.get("max_retries", self.settings.max_retries),  # Retry settings, used by instructor
        }
    
        # Add provider-specific parameters that are passed at completion time
        if self.provider in ["openai", "anthropic"]:
            # OpenAI and Anthropic allow these parameters to be set at completion time
            completion_params["model"] = kwargs.get("model", self.settings.default_model)
            completion_params["temperature"] = kwargs.get("temperature", self.settings.temperature)
    
            # max_tokens can be overridden at completion time for OpenAI/Anthropic
            max_tokens = kwargs.get("max_tokens", self.settings.max_tokens)
            if max_tokens is not None:
                completion_params["max_tokens"] = max_tokens
    
	        # For Gemini, try our custom solution for fixing problematic
          	# characters in HTML content stored as a JSON value
        if self.provider == "gemini":
            try:
                import json
                
                # First, get raw content directly without validation
                raw_response = self.client.client.generate_content(messages[0]["content"])
                raw_text = raw_response.text

                # If it's markdown code-fenced, extract just the JSON
                if raw_text.strip().startswith("```") and "```" in raw_text:
                    start_marker = raw_text.find("```") + 3
                    if raw_text[start_marker:].lstrip().startswith("json"):
                        start_marker = raw_text.find("json", start_marker) + 4
                    end_marker = raw_text.find("```", start_marker)
                    if end_marker > start_marker:
                        raw_text = raw_text[start_marker:end_marker].strip()
                
                # Now let's fix the HTML content in the summary if it has messed up quoting from a misbehaving LLM
                if '"summary":' in raw_text:
                    summary_start = raw_text.find('"summary":')
                    summary_value_start = raw_text.find('"', raw_text.find(':', summary_start) + 1) + 1
                    
                    # Find next field or end of JSON
                    next_field_pos = -1
                    for field in ['"penalty":', '"environmental_issues":', '"citation":', '"federal_law":', '}']:
                        pos = raw_text.find(field, summary_value_start)
                        if pos > 0 and (next_field_pos == -1 or pos < next_field_pos):
                            next_field_pos = pos
                    
                    if summary_value_start > 0 and next_field_pos > summary_value_start:
                        # Find the closing quote of the summary field
                        # Go backwards from next field to find the last quote
                        closing_quote_pos = raw_text.rfind('"', summary_value_start, next_field_pos)
                        
                        if closing_quote_pos > summary_value_start:
                            # Extract the HTML content (between the quotes)
                            html_content = raw_text[summary_value_start:closing_quote_pos]
                            
                            # Apply our simple fix to escape all quotes except the last
                            # (which isn't part of html_content since we're only extracting between quotes)
                            fixed_html = html_content.replace('"', '\\"')
                            
                            # Rebuild the JSON with the fixed HTML
                            fixed_json = (
                                raw_text[:summary_value_start] + 
                                fixed_html + 
                                raw_text[closing_quote_pos:]
                            )
                            
                            # Try to parse the fixed JSON
                            try:
                                parsed = json.loads(fixed_json)
                                print("Successfully fixed HTML quotes in JSON!")
                                return response_model.model_validate(parsed)
                            except json.JSONDecodeError as e:
                                print(f"Still having JSON issues after fixing HTML quotes: {e}")
            except Exception as e:
                print(f"Error in JSON fixing attempt: {e}")
        
        # If we got here, either we're not using Gemini or our fixes failed
        # Fall back to the standard approach
        return self.client.chat.completions.create(**completion_params)
