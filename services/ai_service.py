import google.generativeai as genai
from config import Config

class EvidenceAI:
    def __init__(self):
        genai.configure(api_key=Config.GOOGLE_API_KEY)
        self.model = genai.GenerativeModel('gemini-1.5-flash')

    def analyze_thread(self, conversation_text: str) -> str:
        """
        Analyzes a Slack thread to extract insights based on the OCP framework.
        """
        prompt = f"""
        You are an expert Innovation Consultant for Nesta. Analyze the following Slack conversation.
        
        Your Goal: Answer the "So What?".
        
        Output Structure:
        1. **Summary**: A 1-sentence summary of the discussion.
        2. **Key Decisions**: Bullet points of what was agreed.
        3. **OCP Extraction**: Identify any assumptions mentioned and map them to:
           - Opportunity (Value/Market)
           - Capability (Feasibility/Resources)
           - Progress (Metrics/Sustainability)
        
        Conversation:
        {conversation_text}
        """
        
        try:
            response = self.model.generate_content(prompt)
            return response.text
        except Exception as e:
            return f":warning: AI Analysis failed: {str(e)}"

    def generate_experiment_suggestions(self, assumption: str) -> str:
        """
        Suggests an experiment method for a given assumption.
        """
        prompt = f"Given the assumption: '{assumption}', suggest 3 rapid test methods (e.g., Interviews, Fake Door, Prototype) to validate it within 2 weeks."
        try:
            response = self.model.generate_content(prompt)
            return response.text
        except Exception as e:
            return "Could not generate experiments."
