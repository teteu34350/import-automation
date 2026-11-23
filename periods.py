from dataclasses import dataclass
from datetime import date, datetime, timedelta


@dataclass(frozen=True)
class ReportPeriod:
    start: date
    end: date

    @property
    def start_text(self):
        return self.start.strftime("%d/%m/%Y")

    @property
    def end_text(self):
        return self.end.strftime("%d/%m/%Y")

    @property
    def filename_period(self):
        return f"{self.start:%Y%m%d}-{self.end:%Y%m%d}"


def calculate_report_period(reference_date=None):
    period_anchor = reference_date if reference_date is not None else date.today()
    if isinstance(period_anchor, datetime):
        period_anchor = period_anchor.date()

    first_day = period_anchor.replace(day=1)
    last_day = first_day.replace(year=first_day.year + 1) - timedelta(days=1)
    return ReportPeriod(first_day, last_day)


def calculate_month_to_yesterday_period(reference_date=None):
    period_anchor = reference_date if reference_date is not None else date.today()
    if isinstance(period_anchor, datetime):
        period_anchor = period_anchor.date()

    first_day = period_anchor.replace(day=1)
    last_day = period_anchor - timedelta(days=1)
    if last_day < first_day:
        raise ValueError(
            "Não há dias concluídos neste mês para gerar o relatório."
        )
    return ReportPeriod(first_day, last_day)
