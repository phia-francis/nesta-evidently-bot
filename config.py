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
    GOOGLE_SERVICE_ACCOUNT_JSON = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON")
    
    # Thresholds
    CONFIDENCE_THRESHOLD = float(os.environ.get("CONFIDENCE_THRESHOLD", 0.8))
    STALE_DAYS = int(os.environ.get("STALE_DAYS", 14))

class BrandColor(str, Enum):
    """Nesta Core Palette colors."""
    BLUE = "#0000FF"
    TEAL = "#0FA3A4"
    AMBER = "#FFB703"
    NAVY = "#072033"
    WHITE = "#FFFFFF"

class BrandTheme(str, Enum):
    """Semantic color mapping for OCP Framework."""
    OPPORTUNITY = BrandColor.AMBER
    CAPABILITY = BrandColor.TEAL
    PROGRESS = BrandColor.BLUE
