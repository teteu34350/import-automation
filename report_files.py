import csv
import codecs
import math
import re
import shutil
import unicodedata
import uuid
from datetime import date, datetime, timedelta
from pathlib import Path

from periods import ReportPeriod


XLS_FILE_FORMAT = 56
XLS_SIGNATURE = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
EXCEL_EPOCH = datetime(1899, 12, 30)


class ReportFileError(RuntimeError):
    pass


def detect_excel_text_origin(csv_path):
    with Path(csv_path).open("rb") as source:
        if source.read(3) == b"\xef\xbb\xbf":
            return 65001
    try:
        decoder = codecs.getincrementaldecoder("utf-8")()
        with Path(csv_path).open("rb") as source:
            for chunk in iter(lambda: source.read(65536), b""):
                decoder.decode(chunk)
            decoder.decode(b"", final=True)
    except UnicodeDecodeError:
        return 1252
    return 65001


def _csv_field_info(csv_path, report_kind):
    if report_kind == "R":
        return ((1, 4),)

    encoding = "utf-8-sig" if detect_excel_text_origin(csv_path) == 65001 else "cp1252"
    with Path(csv_path).open(
        "r",
        encoding=encoding,
        newline="",
    ) as source:
        headers = next(csv.reader(source, delimiter=";"), [])
    date_fields = {"in", "out", "data de bloqueio", "realizada em"}
    return tuple(
        (index, 4)
        for index, value in enumerate(headers, start=1)
        if _normalize_header(value) in date_fields
    )


def expected_year(month: int, period: ReportPeriod) -> int:
    return period.start.year if month >= period.start.month else period.end.year


def correct_date(value, period: ReportPeriod):
    parsed = parse_excel_date(value)
    if parsed is None:
        return None

    year = expected_year(parsed.month, period)
    if parsed.year == year:
        return parsed

    try:
        return parsed.replace(year=year)
    except ValueError as error:
        raise ReportFileError(
            f"A data {parsed:%d/%m/%Y} não existe no ano de referência {year}."
        ) from error


def parse_excel_date(value):
    if isinstance(value, datetime):
        return value
    if isinstance(value, date):
        return datetime.combine(value, datetime.min.time())
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        if not math.isfinite(value) or value <= 0 or value >= 2958466:
            return None
        return EXCEL_EPOCH + timedelta(days=value)
    if not isinstance(value, str):
        return None

    text = value.strip()
    if not text or text == "-":
        return None

    for pattern in (
        "%d/%m/%Y %H:%M:%S",
        "%d/%m/%Y %H:%M",
        "%d/%m/%Y",
        "%d/%m",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M",
        "%Y-%m-%d",
    ):
        if pattern == "%d/%m":
            try:
                day, month = (int(part) for part in text.split("/"))
                return datetime(2000, month, day)
            except (ValueError, TypeError):
                continue
        try:
            parsed = datetime.strptime(text, pattern)
            return parsed
        except ValueError:
            continue
    return None


def _normalize_header(value):
    text = str(value or "")
    if "Ã" in text:
        try:
            text = text.encode("latin-1").decode("utf-8")
        except UnicodeError:
            pass
    text = unicodedata.normalize("NFKD", text)
    text = "".join(char for char in text if not unicodedata.combining(char))
    return re.sub(r"\s+", " ", text).strip().lower()


def _excel_value_for(cell):
    value = cell.Value
    if value is not None:
        return value
    raw_value = cell.Value2
    if isinstance(raw_value, (int, float)) and "d" in str(cell.NumberFormat).lower():
        return raw_value
    return None


def _set_corrected_cell(cell, value, period: ReportPeriod):
    parsed = parse_excel_date(value)
    if parsed is None:
        return False
    corrected = correct_date(parsed, period)
    if corrected is None:
        return False
    if corrected.year == parsed.year:
        return False

    raw_value = cell.Value2
    if isinstance(raw_value, (int, float)) and not isinstance(raw_value, bool):
        day_difference = (corrected.date() - parsed.date()).days
        cell.Value2 = raw_value + day_difference
        return True

    if isinstance(value, str):
        year_match = re.search(r"(?<!\d)\d{4}(?!\d)", value)
        if year_match and int(year_match.group()) == parsed.year:
            cell.Value = (
                value[:year_match.start()]
                + str(corrected.year)
                + value[year_match.end():]
            )
            return True

    raise ReportFileError(
        f"Não foi possível alterar somente o ano da data na célula "
        f"{cell.Address}."
    )


def _correct_reservation_dates(sheet, period):
    used = sheet.UsedRange
    first_row = used.Row
    first_column = used.Column
    last_column = first_column + used.Columns.Count - 1
    last_row = first_row + used.Rows.Count - 1
    header_columns = {}

    for column in range(first_column, last_column + 1):
        header = _normalize_header(sheet.Cells(first_row, column).Value)
        if header in {"in", "out", "data de bloqueio"}:
            header_columns[column] = header

    if not header_columns:
        raise ReportFileError(
            "Não encontrei as colunas de datas de hospedagem no relatório C."
        )

    corrected = 0
    checked = 0
    for row in range(first_row + 1, last_row + 1):
        for column in header_columns:
            cell = sheet.Cells(row, column)
            value = _excel_value_for(cell)
            parsed = parse_excel_date(value)
            if parsed is None:
                continue
            checked += 1
            corrected += _set_corrected_cell(cell, value, period)

    for column in header_columns:
        sheet.Columns(column).AutoFit()

    if checked == 0:
        raise ReportFileError(
            "As colunas de datas do relatório C não contêm datas válidas."
        )
    return corrected


def _verify_reservation_dates(sheet, period):
    used = sheet.UsedRange
    first_row = used.Row
    first_column = used.Column
    last_column = first_column + used.Columns.Count - 1
    last_row = first_row + used.Rows.Count - 1
    date_columns = [
        column
        for column in range(first_column, last_column + 1)
        if _normalize_header(sheet.Cells(first_row, column).Value)
        in {"in", "out", "data de bloqueio"}
    ]
    checked = 0

    for row in range(first_row + 1, last_row + 1):
        for column in date_columns:
            cell = sheet.Cells(row, column)
            value = _excel_value_for(cell)
            parsed = parse_excel_date(value)
            if parsed is None:
                continue
            checked += 1
            if parsed.year != expected_year(parsed.month, period):
                raise ReportFileError(
                    f"A data da célula {cell.Address} não foi corrigida "
                    "para o ano esperado."
                )

    if checked == 0:
        raise ReportFileError(
            "Não foi possível validar datas de hospedagem no arquivo XLS."
        )


def _correct_movement_dates(sheet, period):
    used = sheet.UsedRange
    first_row = used.Row
    last_row = first_row + used.Rows.Count - 1
    first_column = used.Column
    movement_section_row = None

    for row in range(first_row, last_row + 1):
        value = sheet.Cells(row, first_column).Value
        if _normalize_header(value) == "movimentacoes":
            movement_section_row = row
            break

    if movement_section_row is None:
        raise ReportFileError(
            "Não encontrei a seção 'Movimentações' no relatório R."
        )

    corrected = 0
    checked = 0
    for row in range(movement_section_row + 1, last_row + 1):
        cell = sheet.Cells(row, first_column)
        value = _excel_value_for(cell)
        parsed = parse_excel_date(value)
        if parsed is None:
            continue
        checked += 1
        corrected += _set_corrected_cell(cell, value, period)

    sheet.Columns(first_column).AutoFit()

    if checked == 0:
        raise ReportFileError(
            "Não encontrei datas diárias após a seção 'Movimentações'."
        )
    return corrected


def _verify_movement_dates(sheet, period):
    used = sheet.UsedRange
    first_row = used.Row
    last_row = first_row + used.Rows.Count - 1
    first_column = used.Column
    movement_section_row = None

    for row in range(first_row, last_row + 1):
        if _normalize_header(sheet.Cells(row, first_column).Value) == "movimentacoes":
            movement_section_row = row
            break

    if movement_section_row is None:
        raise ReportFileError(
            "Não encontrei a seção 'Movimentações' no arquivo XLS."
        )

    checked = 0
    for row in range(movement_section_row + 1, last_row + 1):
        cell = sheet.Cells(row, first_column)
        value = _excel_value_for(cell)
        parsed = parse_excel_date(value)
        if parsed is None:
            continue
        checked += 1
        if parsed.year != expected_year(parsed.month, period):
            raise ReportFileError(
                f"A data da célula {cell.Address} não foi corrigida "
                "para o ano esperado."
            )
    if checked == 0:
        raise ReportFileError(
            "Não foi possível validar as datas diárias no arquivo XLS."
        )


def convert_csv_to_xls(csv_path, xls_path, report_kind, period):
    try:
        import pythoncom
        import win32com.client
    except ImportError as error:
        raise ReportFileError(
            "A conversão para XLS requer pywin32 e o Microsoft Excel "
            "instalado neste Windows."
        ) from error

    source = Path(csv_path)
    destination = Path(xls_path)
    if not source.is_file() or source.stat().st_size == 0:
        raise ReportFileError("O CSV exportado não existe ou está vazio.")
    if destination.exists():
        raise FileExistsError(
            f"Não vou substituir o arquivo existente: {destination}"
        )
    if report_kind not in {"R", "C"}:
        raise ValueError(f"Tipo de relatório desconhecido: {report_kind!r}.")

    destination.parent.mkdir(parents=True, exist_ok=True)
    staging_destination = source.with_name(
        f".{source.stem}-{uuid.uuid4().hex}.staging.xls"
    )
    application = None
    workbook = None
    created_destination = False
    succeeded = False
    operation = "inicializar Excel"
    pythoncom.CoInitialize()
    try:
        application = win32com.client.DispatchEx("Excel.Application")
        application.Visible = False
        application.DisplayAlerts = False
        application.ScreenUpdating = False
        operation = "abrir o CSV no Excel"
        application.Workbooks.OpenText(
            str(source.resolve()),
            detect_excel_text_origin(source),
            1,
            1,
            1,
            False,
            False,
            True,
            False,
            False,
            False,
            "",
            _csv_field_info(source, report_kind),
        )
        workbook = application.ActiveWorkbook
        sheet = workbook.Worksheets(1)
        used = sheet.UsedRange
        if used.Rows.Count > 65536 or used.Columns.Count > 256:
            raise ReportFileError(
                "O relatório excede os limites de linhas ou colunas do XLS."
            )

        operation = "salvar o XLS temporário"
        workbook.SaveAs(
            Filename=str(staging_destination.resolve()),
            FileFormat=XLS_FILE_FORMAT,
            Local=True,
        )
        workbook.Close(SaveChanges=False)
        workbook = None

        if (
            not staging_destination.is_file()
            or staging_destination.stat().st_size == 0
        ):
            raise ReportFileError("O Excel não salvou um arquivo XLS válido.")
        with staging_destination.open("rb") as saved_file:
            signature = saved_file.read(8)
        if signature != XLS_SIGNATURE:
            raise ReportFileError(
                "O arquivo salvo não possui a assinatura binária XLS 97-2003."
            )

        operation = "reabrir o XLS temporário para corrigir as datas"
        workbook = application.Workbooks.Open(
            str(staging_destination.resolve()),
            ReadOnly=False,
            UpdateLinks=0,
        )
        sheet = workbook.Worksheets(1)
        if workbook.Worksheets.Count < 1:
            raise ReportFileError("O arquivo XLS não contém planilhas.")
        if sheet.UsedRange.Rows.Count < 2 or sheet.UsedRange.Columns.Count < 2:
            raise ReportFileError("O arquivo XLS está vazio ou incompleto.")
        if report_kind == "C":
            correction_count = _correct_reservation_dates(sheet, period)
            validator = _verify_reservation_dates
        else:
            correction_count = _correct_movement_dates(sheet, period)
            validator = _verify_movement_dates

        operation = "salvar as datas corrigidas"
        workbook.Save()
        workbook.Close(SaveChanges=False)
        workbook = None

        operation = "validar as datas no XLS temporário"
        workbook = application.Workbooks.Open(
            str(staging_destination.resolve()),
            ReadOnly=True,
            UpdateLinks=0,
        )
        sheet = workbook.Worksheets(1)
        validator(sheet, period)
        workbook.Close(SaveChanges=False)
        workbook = None

        operation = "publicar o XLS validado na pasta de saída"
        with destination.open("xb") as output_file:
            created_destination = True
            with staging_destination.open("rb") as staging_file:
                shutil.copyfileobj(staging_file, output_file)

        if not destination.is_file() or destination.stat().st_size == 0:
            raise ReportFileError("O arquivo XLS final está vazio.")
        with destination.open("rb") as saved_file:
            signature = saved_file.read(8)
        if signature != XLS_SIGNATURE:
            raise ReportFileError(
                "O arquivo XLS final não possui a assinatura binária "
                "XLS 97-2003."
            )
        succeeded = True
        return {
            "path": destination,
            "bytes": destination.stat().st_size,
            "corrected_dates": correction_count,
        }
    except ReportFileError:
        raise
    except Exception as error:
        raise ReportFileError(
            f"Falha ao converter, corrigir ou validar o relatório "
            f"{report_kind}. Etapa: {operation}. "
            f"Detalhe: {type(error).__name__}: {error}"
        ) from error
    finally:
        try:
            if workbook is not None:
                workbook.Close(SaveChanges=False)
        finally:
            try:
                if application is not None:
                    application.Quit()
            finally:
                pythoncom.CoUninitialize()
                if created_destination and not succeeded and destination.exists():
                    destination.unlink()
                if staging_destination.exists():
                    staging_destination.unlink()
