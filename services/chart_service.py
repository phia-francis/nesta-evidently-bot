from quickchart import QuickChart

from config import Brand


class ChartService:
    _WIDTH = 320
    _HEIGHT = 320
    _QUICKCHART_VERSION = "2.9.4"
    _INACTIVE_COLOR = "#D9D9D9"
    _CUTOUT_PERCENTAGE = 78
    _PERCENTAGE_FONT_SIZE = 42
    _LABEL_FONT_SIZE = 18

    @staticmethod
    def generate_progress_ring(percentage: int, label: str) -> str:
        """Generates a Nesta-branded confidence ring image."""
        qc = QuickChart()
        qc.width = ChartService._WIDTH
        qc.height = ChartService._HEIGHT
        qc.version = ChartService._QUICKCHART_VERSION

        qc.config = {
            "type": "doughnut",
            "data": {
                "datasets": [
                    {
                        "data": [percentage, max(0, 100 - percentage)],
                        "backgroundColor": [Brand.NESTA_TEAL, ChartService._INACTIVE_COLOR],
                        "borderWidth": 0,
                    }
                ]
            },
            "options": {
                "cutoutPercentage": ChartService._CUTOUT_PERCENTAGE,
                "plugins": {
                    "doughnutlabel": {
                        "labels": [
                            {
                                "text": f"{percentage}%",
                                "font": {
                                    "size": ChartService._PERCENTAGE_FONT_SIZE,
                                    "weight": "bold",
                                    "family": Brand.FONT_HEADLINE,
                                },
                                "color": Brand.NESTA_NAVY,
                            },
                            {
                                "text": label,
                                "font": {"size": ChartService._LABEL_FONT_SIZE, "family": Brand.FONT_BODY},
                                "color": Brand.NESTA_NAVY,
                            },
                        ]
                    }
                },
                "legend": {"display": False},
            },
        }
        return qc.get_url()

    @staticmethod
    def gateway_motif(url: str) -> str:
        """Approximate the Nesta gateway fold motif using angled masks."""
        qc = QuickChart()
        qc.width = 600
        qc.height = 240
        qc.version = ChartService._QUICKCHART_VERSION
        qc.config = {
            "type": "bar",
            "data": {"labels": ["", ""], "datasets": [{"data": [0, 0]}]},
            "options": {
                "responsive": True,
                "legend": {"display": False},
                "scales": {"xAxes": [{"display": False}], "yAxes": [{"display": False}]},
                "plugins": {
                    "annotation": {
                        "annotations": [
                            {
                                "type": "box",
                                "xScaleID": "x-axis-0",
                                "yScaleID": "y-axis-0",
                                "xMin": -0.5,
                                "xMax": 0.75,
                                "yMin": -0.5,
                                "yMax": 0.5,
                                "backgroundColor": Brand.NESTA_AQUA,
                            },
                            {
                                "type": "line",
                                "mode": "custom",
                                "scaleID": "x-axis-0",
                                "borderColor": Brand.NESTA_PURPLE,
                                "borderWidth": 12,
                                "label": {"enabled": False},
                                "drawTime": "afterDatasetsDraw",
                                "points": [[0.7, -0.5], [1.1, 0.5]],
                            },
                        ]
                    },
                    "backgroundImageUrl": url,
                },
            },
        }
        return qc.get_url()

    @staticmethod
    def generate_decision_heatmap(votes: list[dict]) -> str:
        """Scatter plot of impact vs uncertainty to reveal consensus visually."""
        qc = QuickChart()
        qc.width = 480
        qc.height = 320
        qc.version = ChartService._QUICKCHART_VERSION

        points = [{"x": vote.get("impact", 0), "y": vote.get("uncertainty", 0)} for vote in votes] or [
            {"x": 0, "y": 0}
        ]

        qc.config = {
            "type": "scatter",
            "data": {
                "datasets": [
                    {
                        "label": "Votes",
                        "data": points,
                        "backgroundColor": Brand.NESTA_TEAL,
                    }
                ]
            },
            "options": {
                "legend": {"display": False},
                "scales": {
                    "xAxes": [
                        {
                            "scaleLabel": {"display": True, "labelString": "Impact (1-5)"},
                            "ticks": {"min": 0, "max": 5, "stepSize": 1},
                        }
                    ],
                    "yAxes": [
                        {
                            "scaleLabel": {"display": True, "labelString": "Uncertainty (1-5)"},
                            "ticks": {"min": 0, "max": 5, "stepSize": 1},
                        }
                    ],
                },
                "title": {"display": True, "text": "Impact vs Uncertainty"},
            },
        }
        return qc.get_url()
