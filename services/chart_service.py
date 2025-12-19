from quickchart import QuickChart
from config import Brand

class ChartService:
    _WIDTH = 300
    _HEIGHT = 300
    _QUICKCHART_VERSION = '2.9.4'
    _INACTIVE_COLOR = "#E0E0E0"
    _CUTOUT_PERCENTAGE = 80
    _PERCENTAGE_FONT_SIZE = 40
    _LABEL_FONT_SIZE = 20

    @staticmethod
    def generate_progress_ring(percentage: int, label: str) -> str:
        """Generates a URL for a Nesta-branded progress ring image."""
        qc = QuickChart()
        qc.width = ChartService._WIDTH
        qc.height = ChartService._HEIGHT
        qc.version = ChartService._QUICKCHART_VERSION
        
        # Donut chart simulating a progress ring
        qc.config = {
            "type": "doughnut",
            "data": {
                "datasets": [{
                    "data": [percentage, 100 - percentage],
                    "backgroundColor": [Brand.TEAL, ChartService._INACTIVE_COLOR], # [cite: 2075]
                    "borderWidth": 0
                }]
            },
            "options": {
                "cutoutPercentage": ChartService._CUTOUT_PERCENTAGE,
                "plugins": {
                    "doughnutlabel": {
                        "labels": [
                            {"text": f"{percentage}%", "font": {"size": ChartService._PERCENTAGE_FONT_SIZE, "weight": "bold"}},
                            {"text": label, "font": {"size": ChartService._LABEL_FONT_SIZE}}
                        ]
                    }
                },
                "legend": {"display": False}
            }
        }
        return qc.get_url()
