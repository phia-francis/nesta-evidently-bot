import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    SLACK_BOT_TOKEN = os.environ["SLACK_BOT_TOKEN"]
    SLACK_SIGNING_SECRET = os.environ["SLACK_SIGNING_SECRET"]
    SLACK_APP_TOKEN = os.environ["SLACK_APP_TOKEN"]
    GOOGLE_API_KEY = os.environ["GOOGLE_API_KEY"]
    SUPABASE_URL = os.environ["SUPABASE_URL"]
    SUPABASE_KEY = os.environ["SUPABASE_KEY"]
    
    # Thresholds
    CONFIDENCE_THRESHOLD = float(os.environ.get("CONFIDENCE_THRESHOLD", 0.8))
    STALE_DAYS = int(os.environ.get("STALE_DAYS", 14))

class Brand:
    # Nesta Core Palette
    BLUE = "#0000FF"      # Core Blue
    TEAL = "#0FA3A4"      
    AMBER = "#FFB703"     # "Yellow/Orange" equivalent for CTAs
    NAVY = "#072033"      # "Navy" for text/headers
    WHITE = "#FFFFFF"
    
    # Semantic Mapping for OCP Framework
    COLOR_OPPORTUNITY = AMBER  # Opportunity = Discovery/Warning
    COLOR_CAPABILITY = TEAL    # Capability = Resources/Go
    COLOR_PROGRESS = BLUE      # Progress = Data/Core
