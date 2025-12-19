# from supabase import create_client, Client
from config import Config
from datetime import datetime, timedelta

class ProjectDB:
    def __init__(self):
        # self.supabase: Client = create_client(Config.SUPABASE_URL, Config.SUPABASE_KEY)
        
        # MOCK STATE for demonstration
        self.mock_projects = {
            "U_DEMO": {
                "name": "Family Support Innovation",
                "assumptions": [
                    {"id": "A1", "text": "Parents prefer SMS over email", "category": "Opportunity", "status": "validated", "last_updated": "2023-10-01"},
                    {"id": "A2", "text": "Staff can adopt new triage flow in 2 days", "category": "Capability", "status": "testing", "last_updated": "2023-12-01"},
                    {"id": "A3", "text": "Digital uptake will exceed 40%", "category": "Progress", "status": "stale", "last_updated": "2023-09-01"}
                ],
                "experiments": [
                    {"id": "E1", "name": "SMS Reminder Test", "status": "running", "metric": "Response Rate", "current": 15, "target": 20}
                ]
            }
        }

    def get_user_project(self, user_id):
        # return self.supabase.table('projects').select("*").eq('owner_id', user_id).execute()
        return self.mock_projects.get("U_DEMO") # Defaulting to demo for all users

    def get_stale_assumptions(self, days=14):
        # Logic to filter assumptions older than X days
        project = self.mock_projects["U_DEMO"]
        stale = [a for a in project['assumptions'] if a['status'] == 'stale']
        return stale

    def update_assumption_status(self, assumption_id, status):
        print(f"DB Update: Assumption {assumption_id} set to {status}")
        return True
