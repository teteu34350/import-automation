from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class ReportResult:
    report: str
    status: str
    path: Path | None = None
    message: str = ""
    corrected_dates: int = 0
    unit_name: str = ""


@dataclass
class CollectionResult:
    hotel_name: str
    period_start: str
    period_end: str
    reports: list[ReportResult] = field(default_factory=list)
    logout_confirmed: bool = False
    logout_required: bool = True
    error: str = ""
    expected_report_count: int | None = None

    @property
    def succeeded(self):
        return any(report.status == "success" for report in self.reports)

    @property
    def all_reports_succeeded(self):
        return (
            bool(self.reports)
            and (
                self.expected_report_count is None
                or len(self.reports) == self.expected_report_count
            )
            and all(report.status == "success" for report in self.reports)
        )
