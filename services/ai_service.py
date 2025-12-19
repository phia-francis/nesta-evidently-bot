import json
import logging
import google.generativeai as genai
from config import Config

class EvidenceAI:
    def __init__(self):
        genai.configure(api_key=Config.GOOGLE_API_KEY)
import google.generativeai as genai
from config import Config

_GEMINI_MODEL_NAME = 'gemini-1.5-flash'

class EvidenceAI:
    def __init__(self):
        genai.configure(api_key=Config.GOOGLE_API_KEY)
        self.model = genai.GenerativeModel(_GEMINI_MODEL_NAME)

    def analyze_thread_structured(self, conversation_text: str) -> dict:
        """
        Analyzes a thread and extracts structured OCP data.
        """
        prompt = f"""
        You are a Senior Innovation Consultant at Nesta. Analyze this Slack thread.
        
        Extract the following in JSON format:
        1. "summary": A concise "So What?" summary (British English).
        2. "decisions": List of agreed actions.
        3. "assumptions": A list of objects with:
            - "text": The assumption statement.
            - "category": One of "Opportunity", "Capability", "Progress".
            - "confidence": Integer 0-100 based on evidence mentioned.
            - "status": "stale" if no recent evidence, else "active".

        Conversation:
        {conversation_text}
        """
        
        try:
            response = self.model.generate_content(prompt)
            response_text = response.text
            return json.loads(response_text)
        except json.JSONDecodeError as e:
            logging.error(f"AI Analysis - Failed to parse JSON: {e}. Response text: '{response_text}'", exc_info=True)
            return {"error": "Could not analyze thread due to invalid format."}
        except Exception as e:
            logging.error(f"AI Analysis - General failure: {e}", exc_info=True)
            return {"error": "Could not analyze thread."}

    def generate_experiment_suggestions(self, assumption: str) -> str:
        """
        Suggests an experiment method for a given assumption.
        """
        prompt = f"Given the assumption: '{assumption}', suggest 3 rapid test methods (e.g., Interviews, Fake Door, Prototype) to validate it within 2 weeks."
        try:
            response = self.model.generate_content(prompt)
            return response.text
        except Exception as e:
            logging.error(f"Failed to generate experiment suggestions: {e}", exc_info=True)
            return "Could not generate experiments."
