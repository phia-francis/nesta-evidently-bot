from quickchart import QuickChart
from config import Brand

class ChartService:
    @staticmethod
    def generate_progress_ring(percentage: int, label: str) -> str:
        """Generates a URL for a Nesta-branded progress ring image."""
        qc = QuickChart()
        qc.width = 300
        qc.height = 300
        qc.version = '2.9.4'
        
        # Donut chart simulating a progress ring
        qc.config = {
            "type": "doughnut",
            "data": {
                "datasets": [{
                    "data": [percentage, 100 - percentage],
                    "backgroundColor": [Brand.TEAL, "#E0E0E0"], # [cite: 2075]
                    "borderWidth": 0
                }]
            },
            "options": {
                "cutoutPercentage": 80,
                "plugins": {
                    "doughnutlabel": {
                        "labels": [
                            {"text": f"{percentage}%", "font": {"size": 40, "weight": "bold"}},
                            {"text": label, "font": {"size": 20}}
                        ]
                    }
                },
                "legend": {"display": False}
            }
        }
        return qc.get_url()
