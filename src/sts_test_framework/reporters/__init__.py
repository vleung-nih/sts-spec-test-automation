"""Re-export JSON aggregation/HTML writers for CLI and tooling."""

from .report import aggregate_results, write_json_report
from .html_report import write_html_report

__all__ = ["aggregate_results", "write_json_report", "write_html_report"]
