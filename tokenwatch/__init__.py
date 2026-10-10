"""TokenWatch — token/cost observability for coding agents."""

__version__ = "0.1.0"

from tokenwatch.parsers import scan_path
from tokenwatch.costs import cost_for, PRICE_TABLE
from tokenwatch.metrics import analyze
from tokenwatch.report import generate_html

__all__ = ["scan_path", "cost_for", "PRICE_TABLE", "analyze", "generate_html", "__version__"]
