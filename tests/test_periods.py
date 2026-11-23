import unittest
from datetime import date, timedelta

from periods import (
    calculate_month_to_yesterday_period,
    calculate_report_period,
)


class ReportPeriodTests(unittest.TestCase):
    def test_default_period_starts_in_the_current_month(self):
        today = date.today()
        period = calculate_report_period()

        expected_start = today.replace(day=1)
        expected_end = expected_start.replace(year=expected_start.year + 1) - timedelta(days=1)
        self.assertEqual(period.start, expected_start)
        self.assertEqual(period.end, expected_end)

    def test_period_starts_this_month_and_ends_before_next_year_month(self):
        period = calculate_report_period(date(2026, 10, 17))

        self.assertEqual(period.start, date(2026, 10, 1))
        self.assertEqual(period.end, date(2027, 9, 30))
        self.assertEqual(period.start_text, "01/10/2026")
        self.assertEqual(period.end_text, "30/09/2027")

    def test_period_starts_in_november_when_reference_date_is_in_november(self):
        period = calculate_report_period(date(2026, 11, 4))

        self.assertEqual(period.start, date(2026, 11, 1))
        self.assertEqual(period.end, date(2027, 10, 31))

    def test_period_handles_leap_year(self):
        period = calculate_report_period(date(2023, 3, 1))

        self.assertEqual(period.start, date(2023, 3, 1))
        self.assertEqual(period.end, date(2024, 2, 29))

    def test_period_handles_december(self):
        period = calculate_report_period(date(2025, 12, 31))

        self.assertEqual(period.start, date(2025, 12, 1))
        self.assertEqual(period.end, date(2026, 11, 30))


class MonthToYesterdayPeriodTests(unittest.TestCase):
    def test_period_starts_this_month_and_ends_yesterday(self):
        period = calculate_month_to_yesterday_period(date(2026, 11, 17))

        self.assertEqual(period.start, date(2026, 11, 1))
        self.assertEqual(period.end, date(2026, 11, 16))
        self.assertEqual(period.start_text, "01/11/2026")
        self.assertEqual(period.end_text, "16/11/2026")

    def test_period_handles_month_and_year_boundary(self):
        period = calculate_month_to_yesterday_period(date(2027, 1, 2))

        self.assertEqual(period.start, date(2027, 1, 1))
        self.assertEqual(period.end, date(2027, 1, 1))

    def test_period_fails_when_reference_date_is_first_day_of_month(self):
        with self.assertRaisesRegex(ValueError, "Não há dias concluídos"):
            calculate_month_to_yesterday_period(date(2026, 11, 1))


if __name__ == "__main__":
    unittest.main()
