import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    SLACK_BOT_TOKEN = os.environ.get("SLACK_BOT_TOKEN")
    SLACK_SIGNING_SECRET = os.environ.get("SLACK_SIGNING_SECRET")
    SLACK_APP_TOKEN = os.environ.get("SLACK_APP_TOKEN")
    GOOGLE_API_KEY = os.environ.get("GOOGLE_API_KEY")
    SUPABASE_URL = os.environ.get("SUPABASE_URL")
    SUPABASE_KEY = os.environ.get("SUPABASE_KEY")
    
    # Thresholds
    CONFIDENCE_THRESHOLD = 0.8
    STALE_DAYS = 14
