import os
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from periods import ReportPeriod
from report_files import (
    ReportFileError,
    _normalize_header,
    convert_csv_to_xls,
    correct_date,
    parse_excel_date,
)


PERIOD = ReportPeriod(
    start=datetime(2026, 10, 1).date(),
    end=datetime(2027, 9, 30).date(),
)


class ReportDateTests(unittest.TestCase):
    def test_correct_date_maps_months_to_the_period_years(self):
        self.assertEqual(
            correct_date("30/09/2026", PERIOD),
            datetime(2027, 9, 30),
        )
        self.assertEqual(
            correct_date("01/10/2025", PERIOD),
            datetime(2026, 10, 1),
        )

    def test_correct_date_preserves_time(self):
        self.assertEqual(
            correct_date("01/01/2026 14:25", PERIOD),
            datetime(2027, 1, 1, 14, 25),
        )

    def test_date_only_and_empty_values(self):
        self.assertEqual(
            parse_excel_date("01/10"),
            datetime(2000, 10, 1),
        )
        self.assertIsNone(parse_excel_date("-"))
        self.assertIsNone(parse_excel_date(None))

    def test_header_normalization_handles_mojibake(self):
        self.assertEqual(
            _normalize_header("MovimentaÃ§Ãµes"),
            "movimentacoes",
        )

    def test_invalid_leap_day_reports_error(self):
        period = ReportPeriod(
            start=datetime(2024, 10, 1).date(),
            end=datetime(2025, 9, 30).date(),
        )
        with self.assertRaises(ReportFileError):
            correct_date("29/02/2024", period)


@unittest.skipUnless(os.name == "nt", "A conversão COM exige Windows.")
class ExcelConversionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            import pythoncom
            import win32com.client
        except ImportError as error:
            raise unittest.SkipTest("pywin32 não está instalado.") from error

        pythoncom.CoInitialize()
        try:
            excel = win32com.client.DispatchEx("Excel.Application")
            excel.Quit()
        except Exception as error:
            raise unittest.SkipTest("Microsoft Excel não está disponível.") from error
        finally:
            pythoncom.CoUninitialize()

    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.directory = Path(self.temporary_directory.name)

    def tearDown(self):
        self.temporary_directory.cleanup()

    def _open_workbook(self, path):
        import pythoncom
        import win32com.client

        pythoncom.CoInitialize()
        application = win32com.client.DispatchEx("Excel.Application")
        application.Visible = False
        workbook = application.Workbooks.Open(str(path), ReadOnly=True)
        return pythoncom, application, workbook

    def test_reservation_csv_becomes_corrected_xls(self):
        source = self.directory / "reservations.csv"
        destination = self.directory / "reservations.xls"
        source.write_text(
            "Realizada em;In;Out;Data de bloqueio;Nome\n"
            "10/03/2026 09:55;30/09/2026;02/10/2026;01/01/2026;Reserva\n",
            encoding="utf-8-sig",
        )

        result = convert_csv_to_xls(source, destination, "C", PERIOD)

        self.assertTrue(destination.is_file())
        self.assertEqual(result["corrected_dates"], 2)
        self.assertEqual(
            destination.read_bytes()[:8],
            b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1",
        )
        pythoncom, application, workbook = self._open_workbook(destination)
        try:
            sheet = workbook.Worksheets(1)
            self.assertEqual(sheet.Cells(2, 1).Value.year, 2026)
            self.assertEqual(sheet.Cells(2, 2).Value.year, 2027)
            self.assertEqual(sheet.Cells(2, 3).Value.year, 2026)
            self.assertEqual(sheet.Cells(2, 4).Value.year, 2027)
            self.assertEqual(sheet.Cells(2, 2).Text, "30/09/2027")
        finally:
            workbook.Close(SaveChanges=False)
            application.Quit()
            pythoncom.CoUninitialize()

    def test_movement_csv_becomes_corrected_xls(self):
        source = self.directory / "movement.csv"
        destination = self.directory / "movement.xls"
        source.write_text(
            "Movimentações;Quantidade\n"
            "01/10/2026;10\n"
            "01/01/2026 14:25;20\n",
            encoding="utf-8-sig",
        )

        result = convert_csv_to_xls(source, destination, "R", PERIOD)

        self.assertTrue(destination.is_file())
        self.assertEqual(result["corrected_dates"], 1)
        pythoncom, application, workbook = self._open_workbook(destination)
        try:
            sheet = workbook.Worksheets(1)
            self.assertEqual(sheet.Cells(2, 1).Value.year, 2026)
            self.assertEqual(sheet.Cells(3, 1).Value.year, 2027)
            self.assertEqual(sheet.Cells(3, 1).Value.hour, 14)
            self.assertEqual(sheet.Cells(3, 1).Value.minute, 25)
            self.assertEqual(sheet.Cells(2, 1).Text, "01/10/2026")
            self.assertEqual(sheet.Cells(3, 1).Text, "01/01/2027 14:25")
            self.assertEqual(
                sheet.Cells(3, 1).NumberFormatLocal,
                "dd/mm/aaaa hh:mm",
            )
            self.assertEqual(sheet.Cells(3, 2).Value, 20)
        finally:
            workbook.Close(SaveChanges=False)
            application.Quit()
            pythoncom.CoUninitialize()

    def test_existing_destination_is_not_overwritten(self):
        source = self.directory / "reservations.csv"
        destination = self.directory / "reservations.xls"
        source.write_text("a;b\n1;2\n", encoding="utf-8")
        destination.write_bytes(b"keep")

        with self.assertRaises(FileExistsError):
            convert_csv_to_xls(source, destination, "C", PERIOD)

        self.assertEqual(destination.read_bytes(), b"keep")

    def test_conversion_error_includes_the_underlying_com_error(self):
        source = self.directory / "reservations.csv"
        destination = self.directory / "reservations.xls"
        source.write_text("a;b\n1;2\n", encoding="utf-8")

        with patch(
            "win32com.client.DispatchEx",
            side_effect=RuntimeError("Excel refused to open the CSV"),
        ):
            with self.assertRaisesRegex(
                ReportFileError,
                "RuntimeError: Excel refused to open the CSV",
            ):
                convert_csv_to_xls(source, destination, "C", PERIOD)


if __name__ == "__main__":
    unittest.main()
