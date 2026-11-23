import ctypes
import os
import re
import time
import unicodedata
from datetime import date
from pathlib import Path
from typing import Callable

import win32gui
from pywinauto import Desktop
from pywinauto.keyboard import send_keys

from collectors.models import CollectionResult, ReportResult
from periods import (
    calculate_month_to_yesterday_period,
    calculate_report_period,
)
from settings import HotelProfile, default_desktop_path, default_downloads_path


QUEOPS_SHORTCUT_NAME = "PontalMundai.lnk"
QUEOPS_LOGIN_WINDOW_SIZE = (510, 315)
QUEOPS_LOGIN_TIMEOUT = 60
QUEOPS_REPORT_TIMEOUT = 30
QUEOPS_REPORT_GENERATION_TIMEOUT = 120
QUEOPS_RDS_GENERATION_TIMEOUT = 300
QUEOPS_MENU_OPEN_DELAY = 0.8
QUEOPS_HOSPITALITY_ICON_COORDS = (343, 555)
QUEOPS_OPERATIONAL_REPORTS_MENU_COORDS = (279, 32)
QUEOPS_EXPECTED_CHECKINS_MENU_COORDS = (267, 92)
QUEOPS_OCCUPANCY_FORECAST_MENU_COORDS = (267, 263)
QUEOPS_MANAGEMENT_REPORTS_MENU_COORDS = (351, 31)
QUEOPS_RDS_MENU_COORDS = (390, 131)
QUEOPS_MANAGEMENT_OCCUPANCY_MENU_COORDS = (416, 262)
QUEOPS_SUMMARY_OCCUPANCY_MENU_COORDS = (700, 263)
QUEOPS_REPORT_FINAL_DATE_DAY_COORDS = (304, 54)
QUEOPS_REPORT_FINAL_DATE_MONTH_COORDS = (323, 54)
QUEOPS_REPORT_FINAL_DATE_YEAR_COORDS = (345, 54)
QUEOPS_REPORT_CLOSED_FILTER_COORDS = (134, 114)
QUEOPS_REPORT_DAILY_FILTER_COORDS = (256, 114)
QUEOPS_REPORT_TOTAL_DAILY_OPTION_COORDS = (132, 135)
QUEOPS_REPORT_CANCEL_COORDS = (334, 469)
QUEOPS_OCCUPANCY_CANCEL_COORDS = (275, 295)
QUEOPS_SUMMARY_CANCEL_COORDS = (352, 434)
QUEOPS_RDS_CANCEL_COORDS = (352, 436)
QUEOPS_REPORT_CONFIRM_COORDS = (191, 468)
QUEOPS_REPORT_DIALOG_CANCEL_COORDS = (
    ("Check-in's esperados", QUEOPS_REPORT_CANCEL_COORDS),
    ("Resumo de ocupação", QUEOPS_SUMMARY_CANCEL_COORDS),
    ("Previsão de Ocupação", QUEOPS_OCCUPANCY_CANCEL_COORDS),
    ("Relatório diário de situação - RDS", QUEOPS_RDS_CANCEL_COORDS),
)
QUEOPS_REPORT_VIEWER_EXPORT_COORDS = (281, 50)
QUEOPS_REPORT_VIEWER_EXIT_COORDS = (961, 50)
QUEOPS_SAVE_TYPE_DROPDOWN_COORDS = (675, 529)
QUEOPS_SAVE_FILENAME_COORDS = (430, 494)
QUEOPS_SAVE_BUTTON_COORDS = (753, 494)
QUEOPS_OCCUPANCY_FINAL_DATE_DROPDOWN_COORDS = (389, 70)
QUEOPS_OCCUPANCY_COMPANY_FILTER_COORDS = (195, 165)
QUEOPS_OCCUPANCY_CALENDAR_DISMISS_COORDS = (20, 100)
QUEOPS_OCCUPANCY_CONFIRM_COORDS = (131, 295)
QUEOPS_SUMMARY_START_DATE_DROPDOWN_COORDS = (202, 52)
QUEOPS_SUMMARY_END_DATE_DROPDOWN_COORDS = (465, 52)
QUEOPS_SUMMARY_COMPANY_FILTER_COORDS = (19, 125)
QUEOPS_SUMMARY_CONFIRM_COORDS = (163, 434)
QUEOPS_SUMMARY_START_CALENDAR_DAY_ONE_COORDS = (122, 150)
QUEOPS_SUMMARY_END_CALENDAR_DAY_ONE_COORDS = (384, 150)
QUEOPS_RDS_END_DATE_DROPDOWN_COORDS = (355, 98)
QUEOPS_RDS_REFERENCE_DATE_DROPDOWN_COORDS = (355, 56)
QUEOPS_RDS_END_CALENDAR_DAY_ONE_COORDS = (267, 197)
QUEOPS_RDS_REFERENCE_CALENDAR_DAY_ONE_COORDS = (258, 157)
QUEOPS_RDS_CONFIRM_COORDS = (205, 436)
QUEOPS_CCQ_NOTICE_CLOSE_TIMEOUT = 5
QUEOPS_CALENDAR_COLUMN_STEP = 28
QUEOPS_CALENDAR_ROW_STEP = 18
QUEOPS_EXPECTED_REPORT_COUNT = 4
QUEOPS_NOTICE_TITLE_FRAGMENTS = (
    "aviso",
    "erro",
    "error",
    "atencao",
    "mensagem",
    "alerta",
    "falha",
    "notificacao",
    "informacao",
)


class QueopsLoginError(RuntimeError):
    pass


class QueopsNavigationError(RuntimeError):
    pass


class QueopsExportError(RuntimeError):
    pass


def _find_window(desktop, title_fragment):
    if not hasattr(desktop, "windows"):
        return None
    try:
        windows = desktop.windows(visible_only=True)
    except Exception:
        return None
    if not isinstance(windows, list):
        return None
    normalized_fragment = _normalize_window_title(title_fragment)
    return next(
        (
            window
            for window in windows
            if normalized_fragment
            in _normalize_window_title(window.window_text())
        ),
        None,
    )


def _normalize_window_title(title):
    decomposed = unicodedata.normalize("NFKD", title.casefold())
    return "".join(
        character
        for character in decomposed
        if not unicodedata.combining(character)
    )


def _find_login_window(desktop):
    for window in desktop.windows(visible_only=True):
        try:
            rect = window.rectangle()
            if (
                window.class_name() == "RAIL_WINDOW"
                and (rect.width(), rect.height()) == QUEOPS_LOGIN_WINDOW_SIZE
            ):
                return window
        except Exception:
            continue
    return None


def _foreground_window_handle():
    return ctypes.windll.user32.GetForegroundWindow()


def _replace_login_field(login_window, coords, value):
    login_window.click_input(coords=coords)
    send_keys("^a")
    send_keys("{BACKSPACE}")
    send_keys(value)


def login_queops(
    username: str,
    password: str,
    shortcut_path: str | Path | None = None,
    desktop=None,
    timeout: int = QUEOPS_LOGIN_TIMEOUT,
):
    if not username.strip() or not password:
        raise QueopsLoginError("Informe o usuário e a senha do Queops.")

    desktop = desktop or Desktop(backend="win32")
    if _find_window(desktop, "Sistema Queóps") or _find_window(
        desktop,
        "Sistema Queops",
    ):
        return

    login_window = _find_login_window(desktop)
    if login_window is None:
        shortcut = Path(shortcut_path or default_desktop_path() / QUEOPS_SHORTCUT_NAME)
        if not shortcut.is_file():
            raise QueopsLoginError(
                f"O atalho do Queops não foi encontrado: {shortcut}"
            )
        os.startfile(str(shortcut))

        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if dismiss_queops_ccq_notice(desktop):
                continue
            login_window = _find_login_window(desktop)
            if login_window is not None:
                break
            if _find_window(desktop, "Sistema Queóps") or _find_window(
                desktop,
                "Sistema Queops",
            ):
                return
            time.sleep(0.5)

    if login_window is None:
        raise QueopsLoginError(
            "A tela de login do Queops não apareceu após abrir o atalho."
        )

    login_window.set_focus()
    if _foreground_window_handle() != login_window.handle:
        raise QueopsLoginError(
            "Não foi possível ativar a janela de login do Queops com segurança."
        )
    _replace_login_field(login_window, (365, 166), username)
    _replace_login_field(login_window, (365, 200), password)
    login_window.click_input(coords=(310, 240))

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not login_window.is_visible():
            if _find_window(desktop, "OPERACIONAL - RESERVA/HOSPEDAGEM"):
                return
            if _find_window(desktop, "Sistema Queóps") or _find_window(
                desktop,
                "Sistema Queops",
            ):
                return
        else:
            if _find_window(desktop, "OPERACIONAL - RESERVA/HOSPEDAGEM") or _find_window(
                desktop,
                "Sistema Queóps",
            ) or _find_window(
                desktop,
                "Sistema Queops",
            ):
                return
        dismiss_queops_notice(desktop)
        time.sleep(0.5)

    raise QueopsLoginError(
        "O Queops não confirmou o login. Verifique a janela do sistema."
    )


def _wait_for_window(desktop, title_fragment, timeout):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        window = _find_window(desktop, title_fragment)
        if window is not None:
            return window
        time.sleep(0.5)
    return None


def _focus_queops_window(window):
    window.set_focus()
    if _foreground_window_handle() != window.handle:
        raise QueopsNavigationError(
            "Não foi possível ativar a janela do Queops com segurança."
        )


def _find_notice_window(desktop):
    for fragment in QUEOPS_NOTICE_TITLE_FRAGMENTS:
        window = _find_window(desktop, fragment)
        if window is not None:
            return window

    if hasattr(desktop, "windows"):
        try:
            windows = desktop.windows(visible_only=True)
            if isinstance(windows, list):
                for window in windows:
                    try:
                        title = _normalize_window_title(window.window_text())
                        rect = window.rectangle()
                        if "sistema queops" in title and rect.width() > 600 and rect.height() > 400:
                            continue
                        if "operacional - reserva/hospedagem" in title:
                            continue
                        if (
                            "check-in" in title
                            or "previsao de ocupacao" in title
                            or "resumo de ocupacao" in title
                            or "rds" in title
                            or "visualizador de relatorios" in title
                        ):
                            continue
                        if (rect.width(), rect.height()) == QUEOPS_LOGIN_WINDOW_SIZE:
                            continue

                        for control in window.descendants():
                            try:
                                if re.fullmatch(r"\s*OK\s*", control.window_text(), flags=re.IGNORECASE):
                                    return window
                            except Exception:
                                continue
                    except Exception:
                        continue
        except Exception:
            pass

    return None


def dismiss_queops_notice(desktop=None, title_fragment: str | None = None) -> bool:
    desktop = desktop or Desktop(backend="win32")
    if title_fragment is not None:
        notice_window = _find_window(desktop, title_fragment)
    else:
        notice_window = _find_notice_window(desktop)

    if notice_window is None:
        return False

    try:
        _focus_queops_window(notice_window)
    except Exception:
        try:
            notice_window.set_focus()
        except Exception:
            pass

    ok_button = None
    try:
        ok_button = next(
            (
                control
                for control in notice_window.descendants()
                if control.class_name() == "Button"
                and re.fullmatch(
                    r"\s*OK\s*",
                    control.window_text(),
                    flags=re.IGNORECASE,
                )
            ),
            None,
        )
        if ok_button is None:
            ok_button = next(
                (
                    control
                    for control in notice_window.descendants()
                    if re.fullmatch(
                        r"\s*OK\s*",
                        control.window_text(),
                        flags=re.IGNORECASE,
                    )
                ),
                None,
            )
    except Exception:
        pass

    if ok_button is not None:
        ok_button.click_input()
    else:
        try:
            client_rect = notice_window.client_rect()
            notice_window.click_input(
                coords=(
                    client_rect.width() // 2,
                    int(client_rect.height() * 0.9),
                ),
            )
        except Exception:
            pass

    deadline = time.monotonic() + QUEOPS_CCQ_NOTICE_CLOSE_TIMEOUT
    while time.monotonic() < deadline:
        if title_fragment is not None:
            if _find_window(desktop, title_fragment) is None:
                return True
        else:
            try:
                if not notice_window.is_visible():
                    return True
            except Exception:
                return True
            if _find_notice_window(desktop) is None:
                return True
        time.sleep(0.2)

    return True


def dismiss_queops_ccq_notice(desktop):
    notice_window = _find_window(desktop, "Aviso")
    if notice_window is None:
        return dismiss_queops_notice(desktop)

    _focus_queops_window(notice_window)
    ok_button = next(
        (
            control
            for control in notice_window.descendants()
            if control.class_name() == "Button"
            and re.fullmatch(
                r"\s*OK\s*",
                control.window_text(),
                flags=re.IGNORECASE,
            )
        ),
        None,
    )
    if ok_button is not None:
        ok_button.click_input()
    else:
        client_rect = notice_window.client_rect()
        notice_window.click_input(
            coords=(
                client_rect.width() // 2,
                int(client_rect.height() * 0.9),
            ),
        )

    deadline = time.monotonic() + QUEOPS_CCQ_NOTICE_CLOSE_TIMEOUT
    while time.monotonic() < deadline:
        if _find_window(desktop, "Aviso") is None:
            return True
        time.sleep(0.2)

    raise QueopsNavigationError(
        "O aviso de conexão com o CCQ permaneceu aberto após confirmar OK."
    )


def open_expected_checkin_report(
    desktop=None,
    timeout: int = QUEOPS_REPORT_TIMEOUT,
):
    desktop = desktop or Desktop(backend="win32")
    report_window = _find_window(desktop, "Check-in's esperados")
    if report_window is not None:
        return report_window

    operational_window = _find_window(
        desktop,
        "OPERACIONAL - RESERVA/HOSPEDAGEM",
    )
    if operational_window is None:
        home_window = _find_window(desktop, "Sistema Queóps") or _find_window(
            desktop,
            "Sistema Queops",
        )
        if home_window is None:
            raise QueopsNavigationError(
                "A tela inicial do Queops não foi encontrada."
            )
        _focus_queops_window(home_window)
        home_window.click_input(
            coords=QUEOPS_HOSPITALITY_ICON_COORDS,
            double=True,
        )
        operational_window = _wait_for_window(
            desktop,
            "OPERACIONAL - RESERVA/HOSPEDAGEM",
            timeout,
        )
        if operational_window is None:
            raise QueopsNavigationError(
                "O módulo Hospedagem do Queops não abriu."
            )

    _focus_queops_window(operational_window)
    operational_window.click_input(
        coords=QUEOPS_OPERATIONAL_REPORTS_MENU_COORDS,
    )
    time.sleep(QUEOPS_MENU_OPEN_DELAY)
    operational_window.click_input(
        coords=QUEOPS_EXPECTED_CHECKINS_MENU_COORDS,
    )
    report_window = _wait_for_window(
        desktop,
        "Check-in's esperados",
        timeout,
    )
    if report_window is None:
        raise QueopsNavigationError(
            "A janela Check-in's esperados não abriu."
        )
    return report_window


def open_occupancy_forecast_report(
    desktop=None,
    timeout: int = QUEOPS_REPORT_TIMEOUT,
):
    desktop = desktop or Desktop(backend="win32")
    report_window = _find_window(desktop, "Previsão de Ocupação")
    if report_window is not None:
        return report_window

    home_window = _find_window(desktop, "Sistema Queóps") or _find_window(
        desktop,
        "Sistema Queops",
    )
    if home_window is not None:
        _focus_queops_window(home_window)
        home_window.click_input(
            coords=QUEOPS_HOSPITALITY_ICON_COORDS,
            double=True,
        )
        time.sleep(QUEOPS_MENU_OPEN_DELAY)
        operational_window = _wait_for_window(
            desktop,
            "OPERACIONAL - RESERVA/HOSPEDAGEM",
            timeout,
        )
    else:
        operational_window = _find_window(
            desktop,
            "OPERACIONAL - RESERVA/HOSPEDAGEM",
        )
    if operational_window is None:
        raise QueopsNavigationError(
            "A tela do módulo Hospedagem não foi encontrada."
        )

    _focus_queops_window(operational_window)
    operational_window.click_input(
        coords=QUEOPS_OPERATIONAL_REPORTS_MENU_COORDS,
    )
    time.sleep(QUEOPS_MENU_OPEN_DELAY)
    operational_window.click_input(
        coords=QUEOPS_OCCUPANCY_FORECAST_MENU_COORDS,
    )
    report_window = _wait_for_window(
        desktop,
        "Previsão de Ocupação",
        timeout,
    )
    if report_window is None:
        raise QueopsNavigationError(
            "A janela Previsão de Ocupação não abriu."
        )
    return report_window


def _management_operational_window(desktop, timeout):
    operational_window = _find_window(
        desktop,
        "OPERACIONAL - RESERVA/HOSPEDAGEM",
    )
    if operational_window is not None:
        return operational_window

    home_window = _find_window(desktop, "Sistema Queóps") or _find_window(
        desktop,
        "Sistema Queops",
    )
    if home_window is None:
        raise QueopsNavigationError(
            "A tela do módulo Hospedagem não foi encontrada."
        )

    _focus_queops_window(home_window)
    home_window.click_input(
        coords=QUEOPS_HOSPITALITY_ICON_COORDS,
        double=True,
    )
    operational_window = _wait_for_window(
        desktop,
        "OPERACIONAL - RESERVA/HOSPEDAGEM",
        timeout,
    )
    if operational_window is None:
        raise QueopsNavigationError(
            "O módulo Hospedagem do Queops não abriu."
        )
    return operational_window


def _open_management_report(desktop, report_title, menu_path, timeout):
    report_window = _find_window(desktop, report_title)
    if report_window is not None:
        return report_window

    operational_window = _management_operational_window(desktop, timeout)
    _focus_queops_window(operational_window)
    for coordinates in menu_path:
        operational_window.click_input(coords=coordinates)
        time.sleep(QUEOPS_MENU_OPEN_DELAY)

    report_window = _wait_for_window(desktop, report_title, timeout)
    if report_window is None:
        raise QueopsNavigationError(
            f"A janela {report_title} não abriu."
        )
    return report_window


def open_summary_occupancy_report(
    desktop=None,
    timeout: int = QUEOPS_REPORT_TIMEOUT,
):
    desktop = desktop or Desktop(backend="win32")
    return _open_management_report(
        desktop,
        "Resumo de ocupação",
        (
            QUEOPS_MANAGEMENT_REPORTS_MENU_COORDS,
            QUEOPS_MANAGEMENT_OCCUPANCY_MENU_COORDS,
            QUEOPS_SUMMARY_OCCUPANCY_MENU_COORDS,
        ),
        timeout,
    )


def open_rds_report(
    desktop=None,
    timeout: int = QUEOPS_REPORT_TIMEOUT,
):
    desktop = desktop or Desktop(backend="win32")
    return _open_management_report(
        desktop,
        "Relatório diário de situação - RDS",
        (
            QUEOPS_MANAGEMENT_REPORTS_MENU_COORDS,
            QUEOPS_RDS_MENU_COORDS,
        ),
        timeout,
    )


def _checkbox_is_checked(report_window, coordinates):
    window_handle = report_window.handle
    device_context = win32gui.GetWindowDC(window_handle)
    if not device_context:
        raise QueopsNavigationError(
            "Não foi possível ler o estado dos filtros do relatório."
        )

    try:
        x, y = coordinates
        dark_pixels = 0
        for offset_x in range(-2, 3):
            for offset_y in range(-2, 3):
                pixel = win32gui.GetPixel(
                    device_context,
                    x + offset_x,
                    y + offset_y,
                )
                if pixel in (-1, 0xFFFFFFFF):
                    raise QueopsNavigationError(
                        "Não foi possível ler o estado dos filtros do relatório."
                    )
                rgb = (
                    pixel & 0xFF,
                    (pixel >> 8) & 0xFF,
                    (pixel >> 16) & 0xFF,
                )
                if max(rgb) < 128:
                    dark_pixels += 1
        return dark_pixels >= 2
    finally:
        win32gui.ReleaseDC(window_handle, device_context)


def _ensure_expected_checkin_filters_checked(report_window):
    filters = (
        ("Fechado", QUEOPS_REPORT_CLOSED_FILTER_COORDS),
        ("Diária", QUEOPS_REPORT_DAILY_FILTER_COORDS),
    )
    unchecked_filters = [
        (label, coordinates)
        for label, coordinates in filters
        if not _checkbox_is_checked(report_window, coordinates)
    ]

    for _, coordinates in unchecked_filters:
        report_window.click_input(coords=coordinates)

    if unchecked_filters:
        still_unchecked = [
            label
            for label, coordinates in unchecked_filters
            if not _checkbox_is_checked(report_window, coordinates)
        ]
        if still_unchecked:
            raise QueopsNavigationError(
                "Não foi possível marcar os filtros "
                f"{' e '.join(still_unchecked)}."
            )


def configure_and_generate_expected_checkin_report(
    report_window,
    desktop=None,
    reference_date: date | None = None,
):
    desktop = desktop or Desktop(backend="win32")
    reference_date = reference_date or date.today()
    try:
        report_end_date = reference_date.replace(year=reference_date.year + 1)
    except ValueError as error:
        raise QueopsNavigationError(
            "A data final não existe no ano seguinte."
        ) from error

    _focus_queops_window(report_window)
    _ensure_expected_checkin_filters_checked(report_window)
    for coordinates, value in (
        (QUEOPS_REPORT_FINAL_DATE_DAY_COORDS, f"{report_end_date.day:02d}"),
        (QUEOPS_REPORT_FINAL_DATE_MONTH_COORDS, f"{report_end_date.month:02d}"),
        (QUEOPS_REPORT_FINAL_DATE_YEAR_COORDS, f"{report_end_date.year:04d}"),
    ):
        report_window.click_input(coords=coordinates)
        send_keys(value)
    report_window.click_input(
        coords=QUEOPS_REPORT_TOTAL_DAILY_OPTION_COORDS,
    )
    report_window.click_input(coords=QUEOPS_REPORT_CONFIRM_COORDS)
    report_viewer = _wait_for_window(
        desktop,
        "Visualizador de relatórios",
        QUEOPS_REPORT_GENERATION_TIMEOUT,
    )
    if report_viewer is None:
        raise QueopsNavigationError(
            "O Visualizador de relatórios não abriu após a confirmação."
        )
    return report_viewer


def _collect_queops_report_step(
    result: CollectionResult,
    report_name: str,
    previous_viewer,
    progress,
    progress_messages: tuple[str, str, str],
    open_report: Callable[[], object],
    configure_report: Callable[[object], object],
    export_report: Callable[[object], Path],
):
    active_viewer = previous_viewer
    report_window = None
    report_path = None
    try:
        if active_viewer is not None:
            close_queops_report_viewer(active_viewer)
            active_viewer = None
        if progress:
            progress(progress_messages[0])
        report_window = open_report()
        if progress:
            progress(progress_messages[1])
        active_viewer = configure_report(report_window)
        if progress:
            progress(progress_messages[2])
        report_path = export_report(active_viewer)
        close_queops_report_viewer(active_viewer)
        active_viewer = None
        close_queops_report_window(report_window)
    except Exception as error:
        message = str(error)
        result.reports.append(
            ReportResult(
                report=report_name,
                status="failed",
                path=report_path,
                message=message,
            )
        )
        failure = f"{report_name}: {message}"
        result.error = (
            f"{result.error}\n{failure}" if result.error else failure
        )
        return active_viewer

    result.reports.append(
        ReportResult(
            report=report_name,
            status="success",
            path=report_path,
        )
    )
    return active_viewer


def configure_and_generate_occupancy_forecast_report(
    report_window,
    desktop=None,
    reference_date: date | None = None,
):
    desktop = desktop or Desktop(backend="win32")
    reference_date = reference_date or date.today()
    try:
        report_end_date = reference_date.replace(year=reference_date.year + 1)
    except ValueError as error:
        raise QueopsNavigationError(
            "A data final não existe no ano seguinte."
        ) from error

    _focus_queops_window(report_window)
    report_window.click_input(
        coords=QUEOPS_OCCUPANCY_FINAL_DATE_DROPDOWN_COORDS,
    )
    time.sleep(0.2)
    send_keys("^{PGDN}")
    report_window.click_input(
        coords=QUEOPS_OCCUPANCY_COMPANY_FILTER_COORDS,
    )
    report_window.click_input(
        coords=QUEOPS_OCCUPANCY_CALENDAR_DISMISS_COORDS,
    )
    report_window.click_input(coords=QUEOPS_OCCUPANCY_CONFIRM_COORDS)

    report_viewer = _wait_for_window(
        desktop,
        "Visualizador de relatórios",
        QUEOPS_REPORT_GENERATION_TIMEOUT,
    )
    if report_viewer is None:
        raise QueopsNavigationError(
            "O Visualizador de relatórios não abriu após a confirmação."
        )
    return report_viewer


def _calendar_date_coordinates(target_date, day_one_coordinates):
    first_weekday = (target_date.replace(day=1).weekday() + 1) % 7
    calendar_index = first_weekday + target_date.day - 1
    row, column = divmod(calendar_index, 7)
    return (
        day_one_coordinates[0] + column * QUEOPS_CALENDAR_COLUMN_STEP,
        day_one_coordinates[1] + row * QUEOPS_CALENDAR_ROW_STEP,
    )


def _select_calendar_date(
    report_window,
    dropdown_coordinates,
    target_date,
    day_one_coordinates,
):
    report_window.click_input(coords=dropdown_coordinates)
    time.sleep(0.2)
    report_window.click_input(
        coords=_calendar_date_coordinates(
            target_date,
            day_one_coordinates,
        ),
    )


def configure_and_generate_summary_occupancy_report(
    report_window,
    desktop=None,
    reference_date: date | None = None,
):
    desktop = desktop or Desktop(backend="win32")
    reference_date = reference_date or date.today()
    try:
        period = calculate_month_to_yesterday_period(reference_date)
    except ValueError as error:
        raise QueopsNavigationError(str(error)) from error

    _focus_queops_window(report_window)
    _select_calendar_date(
        report_window,
        QUEOPS_SUMMARY_START_DATE_DROPDOWN_COORDS,
        period.start,
        QUEOPS_SUMMARY_START_CALENDAR_DAY_ONE_COORDS,
    )
    _select_calendar_date(
        report_window,
        QUEOPS_SUMMARY_END_DATE_DROPDOWN_COORDS,
        period.end,
        QUEOPS_SUMMARY_END_CALENDAR_DAY_ONE_COORDS,
    )
    report_window.click_input(
        coords=QUEOPS_SUMMARY_COMPANY_FILTER_COORDS,
    )
    report_window.click_input(coords=QUEOPS_SUMMARY_CONFIRM_COORDS)

    report_viewer = _wait_for_window(
        desktop,
        "Visualizador de relatórios",
        QUEOPS_REPORT_GENERATION_TIMEOUT,
    )
    if report_viewer is None:
        raise QueopsNavigationError(
            "O Visualizador de relatórios não abriu após a confirmação."
        )
    return report_viewer


def configure_and_generate_rds_report(
    report_window,
    desktop=None,
    reference_date: date | None = None,
):
    desktop = desktop or Desktop(backend="win32")
    reference_date = reference_date or date.today()
    try:
        period = calculate_month_to_yesterday_period(reference_date)
    except ValueError as error:
        raise QueopsNavigationError(str(error)) from error

    _focus_queops_window(report_window)
    _select_calendar_date(
        report_window,
        QUEOPS_RDS_END_DATE_DROPDOWN_COORDS,
        period.end,
        QUEOPS_RDS_END_CALENDAR_DAY_ONE_COORDS,
    )
    _select_calendar_date(
        report_window,
        QUEOPS_RDS_REFERENCE_DATE_DROPDOWN_COORDS,
        period.end,
        QUEOPS_RDS_REFERENCE_CALENDAR_DAY_ONE_COORDS,
    )
    report_window.click_input(coords=QUEOPS_RDS_CONFIRM_COORDS)

    report_viewer = _wait_for_window(
        desktop,
        "Visualizador de relatórios",
        QUEOPS_RDS_GENERATION_TIMEOUT,
    )
    if report_viewer is None:
        raise QueopsNavigationError(
            "O Visualizador de relatórios não abriu após gerar o RDS."
        )
    return report_viewer


def _available_report_destination(directory, filename, file_extension):
    base_filename = filename
    destination = directory / f"{filename}{file_extension}"
    suffix = 2
    while destination.exists():
        filename = f"{base_filename} {suffix}"
        destination = directory / f"{filename}{file_extension}"
        suffix += 1
    return filename, destination


def export_queops_report(
    report_viewer,
    hotel_name: str,
    filename_prefix: str,
    desktop=None,
    downloads_directory: str | Path | None = None,
    reference_date: date | None = None,
    timeout: int = 60,
    use_short_hotel_name: bool = True,
    prefix_separator: str = " ",
    file_extension: str = ".xls",
    file_type_key: str | None = "M",
):
    desktop = desktop or Desktop(backend="win32")
    reference_date = reference_date or date.today()
    if file_extension not in {".xls", ".pdf"}:
        raise QueopsExportError(
            "O formato de exportação aceito é .xls ou .pdf."
        )
    hotel_name_parts = hotel_name.strip().split(maxsplit=1)
    hotel_short_name = hotel_name_parts[0] if hotel_name_parts else ""
    filename_hotel_name = (
        hotel_short_name if use_short_hotel_name else hotel_name.strip()
    )
    safe_hotel_name = re.sub(
        r'[<>:"/\\|?*]',
        "_",
        filename_hotel_name,
    ).strip(" .")
    if not safe_hotel_name:
        raise QueopsExportError("O nome do hotel não pode formar um arquivo.")

    safe_prefix = re.sub(r'[<>:"/\\|?*]', "_", filename_prefix).strip(" .")
    if not safe_prefix:
        raise QueopsExportError("O prefixo do relatório não pode formar um arquivo.")

    downloads_path = Path(downloads_directory or default_downloads_path())
    filename = (
        f"{safe_prefix}{prefix_separator}{safe_hotel_name} "
        f"{reference_date:%d-%m}"
    )
    filename, destination = _available_report_destination(
        downloads_path,
        filename,
        file_extension,
    )
    if not downloads_path.is_dir():
        raise QueopsExportError(
            f"A pasta Downloads não foi encontrada: {downloads_path}"
        )

    current_viewer = _find_window(desktop, "Visualizador de relatórios")
    if current_viewer is None:
        raise QueopsExportError(
            "A janela do Visualizador de relatórios não está mais aberta."
        )
    report_viewer = current_viewer
    _focus_queops_window(report_viewer)
    report_viewer.click_input(coords=QUEOPS_REPORT_VIEWER_EXPORT_COORDS)
    save_dialog = _wait_for_window(desktop, "Salvar como", timeout)
    if save_dialog is None:
        raise QueopsExportError(
            "A janela Salvar como não abriu para exportar o relatório."
        )

    _focus_queops_window(save_dialog)
    if file_type_key:
        save_dialog.click_input(coords=QUEOPS_SAVE_TYPE_DROPDOWN_COORDS)
        send_keys(file_type_key)
        send_keys("{ENTER}")
    save_dialog.click_input(coords=QUEOPS_SAVE_FILENAME_COORDS)
    send_keys("^a")
    send_keys("{BACKSPACE}")
    send_keys(filename, with_spaces=True)
    save_dialog.click_input(coords=QUEOPS_SAVE_BUTTON_COORDS)

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if destination.is_file() and destination.stat().st_size > 0:
            return destination
        time.sleep(0.5)
    raise QueopsExportError(
        f"O arquivo não apareceu em Downloads após salvar: {destination.name}"
    )


def export_expected_checkin_report(
    report_viewer,
    hotel_name: str,
    desktop=None,
    downloads_directory: str | Path | None = None,
    reference_date: date | None = None,
    timeout: int = 60,
):
    return export_queops_report(
        report_viewer,
        hotel_name,
        "C-FUT",
        desktop=desktop,
        downloads_directory=downloads_directory,
        reference_date=reference_date,
        timeout=timeout,
    )


def export_past_occupancy_report(
    report_viewer,
    hotel_name: str,
    desktop=None,
    downloads_directory: str | Path | None = None,
    reference_date: date | None = None,
    timeout: int = 60,
):
    return export_queops_report(
        report_viewer,
        hotel_name,
        "C-PAST",
        desktop=desktop,
        downloads_directory=downloads_directory,
        reference_date=reference_date,
        timeout=timeout,
    )


def export_rds_report(
    report_viewer,
    hotel_name: str,
    desktop=None,
    downloads_directory: str | Path | None = None,
    reference_date: date | None = None,
    timeout: int = 60,
):
    return export_queops_report(
        report_viewer,
        hotel_name.casefold(),
        "rds",
        desktop=desktop,
        downloads_directory=downloads_directory,
        reference_date=reference_date,
        timeout=timeout,
        prefix_separator="-",
        file_extension=".pdf",
        file_type_key="A",
    )


def close_queops_report_viewer(report_viewer):
    if report_viewer is None:
        return

    desktop = Desktop(backend="win32")
    current_viewer = _find_window(desktop, "Visualizador de relatórios")
    if current_viewer is None:
        return

    _focus_queops_window(current_viewer)
    current_viewer.click_input(coords=QUEOPS_REPORT_VIEWER_EXIT_COORDS)


def close_queops_report_window(report_window):
    if report_window is None:
        return

    title = report_window.window_text()
    cancel_coordinates = next(
        (
            coordinates
            for title_fragment, coordinates in QUEOPS_REPORT_DIALOG_CANCEL_COORDS
            if title_fragment.casefold() in title.casefold()
        ),
        None,
    )
    if cancel_coordinates is None:
        raise QueopsNavigationError(
            f"Não há posição de Cancelar configurada para {title}."
        )

    _focus_queops_window(report_window)
    report_window.click_input(coords=cancel_coordinates)
    time.sleep(0.2)


def collect_queops_report(
    hotel: HotelProfile,
    password: str,
    output_directory: str | Path,
    progress=None,
    reference_date: date | None = None,
) -> CollectionResult:
    del output_directory
    reference_date = reference_date or date.today()
    period = calculate_report_period(reference_date)
    result = CollectionResult(
        hotel_name=hotel.name,
        period_start=period.start_text,
        period_end=period.end_text,
        expected_report_count=QUEOPS_EXPECTED_REPORT_COUNT,
        logout_required=False,
    )
    try:
        past_period = calculate_month_to_yesterday_period(reference_date)
    except ValueError as error:
        result.error = str(error)
        return result

    if progress:
        progress("Acessando o Queops instalado...")
    desktop = Desktop(backend="win32")
    try:
        login_queops(hotel.username, password, desktop=desktop)
        dismiss_queops_ccq_notice(desktop)
    except Exception as error:
        result.error = str(error)
        return result

    report_viewer = _collect_queops_report_step(
        result,
        "Check-in's esperados",
        None,
        progress,
        (
            "Abrindo Hospedagem > Rel. Operacionais > Check-in's esperados...",
            "Configurando as datas e filtros do relatório...",
            "Exportando o relatório para Downloads como Microsoft Excel...",
        ),
        open_report=lambda: open_expected_checkin_report(desktop=desktop),
        configure_report=lambda report_window: (
            configure_and_generate_expected_checkin_report(
                report_window,
                desktop=desktop,
                reference_date=reference_date,
            )
        ),
        export_report=lambda report_viewer: export_expected_checkin_report(
            report_viewer,
            hotel.name,
            desktop=desktop,
            reference_date=reference_date,
        ),
    )
    report_viewer = _collect_queops_report_step(
        result,
        "Resumo de Ocupação (C-PAST)",
        report_viewer,
        progress,
        (
            "Abrindo Rel. Gerenciais > Relatório de Ocupação > Resumo de Ocupação...",
            "Configurando o período do mês até ontem e Empresa...",
            "Exportando C-PAST para Downloads como Microsoft Excel...",
        ),
        open_report=lambda: open_summary_occupancy_report(desktop=desktop),
        configure_report=lambda report_window: (
            configure_and_generate_summary_occupancy_report(
                report_window,
                desktop=desktop,
                reference_date=reference_date,
            )
        ),
        export_report=lambda report_viewer: export_past_occupancy_report(
            report_viewer,
            hotel.name,
            desktop=desktop,
            reference_date=reference_date,
        ),
    )
    report_viewer = _collect_queops_report_step(
        result,
        "Previsão de Ocupação",
        report_viewer,
        progress,
        (
            "Abrindo Hospedagem > Rel. Operacionais > Previsão de Ocupação...",
            "Configurando Previsão de Ocupação para Empresa e diárias fechadas...",
            "Exportando Previsão de Ocupação para Downloads como Microsoft Excel...",
        ),
        open_report=lambda: open_occupancy_forecast_report(desktop=desktop),
        configure_report=lambda report_window: (
            configure_and_generate_occupancy_forecast_report(
                report_window,
                desktop=desktop,
                reference_date=reference_date,
            )
        ),
        export_report=lambda report_viewer: export_queops_report(
            report_viewer,
            hotel.name,
            "R",
            desktop=desktop,
            reference_date=reference_date,
            use_short_hotel_name=False,
            prefix_separator="-",
        ),
    )
    _collect_queops_report_step(
        result,
        "Diário de situação (RDS)",
        report_viewer,
        progress,
        (
            "Abrindo Rel. Gerenciais > Diário de situação - RDS...",
            "Configurando o RDS de 01 do mês até ontem, sem filtros...",
            "Exportando o RDS para Downloads como PDF...",
        ),
        open_report=lambda: open_rds_report(desktop=desktop),
        configure_report=lambda report_window: (
            configure_and_generate_rds_report(
                report_window,
                desktop=desktop,
                reference_date=reference_date,
            )
        ),
        export_report=lambda report_viewer: export_rds_report(
            report_viewer,
            hotel.name,
            desktop=desktop,
            reference_date=past_period.end,
            timeout=QUEOPS_RDS_GENERATION_TIMEOUT,
        ),
    )
    return result
