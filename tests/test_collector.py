import os
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import ANY, MagicMock, Mock, patch

from collectors.desbravador_web import (
    RESERVATION_REPORT,
    _browser_profile_directory,
    _dismiss_optional_notices,
    _ensure_browser_profile_directory,
    _login,
    _login_failure_message,
    _prepare_report,
    _playwright_with_temp_directory,
    _redact,
    _select_hotel_unit,
    _set_date,
    collect_reports,
)
from collectors.models import CollectionResult, ReportResult
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from periods import calculate_report_period
from settings import new_hotel_profile


class CollectorMessageTests(unittest.TestCase):
    def test_dismisses_feedback_notice_after_login(self):
        page = Mock()
        notice = Mock()
        page.get_by_text.return_value.first = notice

        _dismiss_optional_notices(page)

        notice_text = page.get_by_text.call_args.args[0]
        self.assertRegex("Responder mais tarde", notice_text)
        notice.wait_for.assert_any_call(state="visible", timeout=2500)
        notice.click.assert_called_once_with()
        notice.wait_for.assert_any_call(state="hidden", timeout=10000)

    def test_optional_notice_timeout_does_not_block_login(self):
        page = Mock()
        notice = Mock()
        notice.wait_for.side_effect = PlaywrightTimeoutError("not visible")
        page.get_by_text.return_value.first = notice
        tax_dialog = Mock()
        tax_dialog.wait_for.side_effect = PlaywrightTimeoutError("not visible")
        page.get_by_role.return_value.filter.return_value = tax_dialog

        _dismiss_optional_notices(page)

        notice.click.assert_not_called()
        tax_dialog.get_by_role.assert_not_called()

    def test_session_in_use_message_prevents_takeover_attempt(self):
        message = _login_failure_message(
            "Sessão em uso! Usuário já está conectado em outra sessão. "
            "Para desconectá-lo faça o login novamente."
        )

        self.assertIn("já está conectado", message)
        self.assertIn("parou sem tentar desconectar", message)

    def test_login_errors_are_reported(self):
        message = _login_failure_message(
            "Usuário\nSenha\nE-mail não cadastrado."
        )

        self.assertIn("E-mail não cadastrado.", message)

    def test_errors_do_not_expose_credentials(self):
        profile = new_hotel_profile(
            "Hotel",
            "https://example.com/acesso/1/",
            "account@example.com",
        )

        message = _redact(
            "Falha em account@example.com com password-value.",
            profile,
            "password-value",
        )

        self.assertNotIn("account@example.com", message)
        self.assertNotIn("password-value", message)

    def test_browser_profiles_are_isolated_per_hotel(self):
        first_profile = new_hotel_profile(
            "Inasem",
            "https://example.com",
            "user@example.com",
        )
        second_profile = new_hotel_profile(
            "Another hotel",
            "https://example.com",
            "user@example.com",
        )

        with tempfile.TemporaryDirectory() as local_app_data:
            with patch.dict("os.environ", {"LOCALAPPDATA": local_app_data}):
                first_directory = _browser_profile_directory(first_profile)
                second_directory = _browser_profile_directory(second_profile)

        self.assertEqual(
            first_directory.parent,
            Path(local_app_data) / "PMSReportAutomation" / "browser-profiles",
        )
        self.assertNotEqual(first_directory, second_directory)

    def test_browser_profile_uses_temp_directory_when_default_is_denied(self):
        profile = new_hotel_profile(
            "Inasem",
            "https://example.com",
            "user@example.com",
        )

        with tempfile.TemporaryDirectory() as local_app_data:
            with tempfile.TemporaryDirectory() as temp_directory:
                with patch.dict("os.environ", {"LOCALAPPDATA": local_app_data}):
                    with patch(
                        "collectors.desbravador_web.tempfile.gettempdir",
                        return_value=temp_directory,
                    ):
                        preferred = _browser_profile_directory(profile)
                        real_mkdir = Path.mkdir

                        def deny_preferred(path, *args, **kwargs):
                            if path == preferred:
                                raise PermissionError("Acesso negado")
                            return real_mkdir(path, *args, **kwargs)

                        with patch.object(Path, "mkdir", new=deny_preferred):
                            actual = _ensure_browser_profile_directory(preferred)
                        self.assertEqual(
                            actual,
                            Path(temp_directory)
                            / "PMSReportAutomation"
                            / "browser-profiles"
                            / preferred.name,
                        )
                        self.assertTrue(actual.is_dir())

    def test_playwright_uses_and_restores_its_temp_directory(self):
        with tempfile.TemporaryDirectory() as temp_directory:
            playwright_temp = Path(temp_directory) / "playwright-temp"
            playwright = Mock()
            manager = MagicMock()
            observed_environment = {}
            manager.__enter__.side_effect = lambda: (
                observed_environment.update(
                    {
                        "TEMP": os.environ.get("TEMP"),
                        "TMP": os.environ.get("TMP"),
                    }
                )
                or playwright
            )

            with patch.dict(
                "os.environ",
                {"TEMP": "original-temp", "TMP": "original-tmp"},
            ):
                with patch(
                    "collectors.desbravador_web.sync_playwright",
                    return_value=manager,
                ):
                    with _playwright_with_temp_directory(playwright_temp) as actual:
                        self.assertIs(actual, playwright)
                        self.assertEqual(
                            observed_environment,
                            {
                                "TEMP": str(playwright_temp),
                                "TMP": str(playwright_temp),
                            },
                        )
                        self.assertEqual(os.environ["TEMP"], "original-temp")
                        self.assertEqual(os.environ["TMP"], "original-tmp")

                self.assertEqual(
                    os.environ["TEMP"],
                    "original-temp",
                )
                self.assertEqual(
                    os.environ["TMP"],
                    "original-tmp",
                )

    def test_login_opens_the_configured_portal_url(self):
        profile = new_hotel_profile(
            "Inasem",
            "https://portal.example.com/login",
            "user@example.com",
        )
        page = Mock()
        username_field = Mock()
        password_field = Mock()
        username_field.count.return_value = 1
        password_field.count.return_value = 1
        page.locator.side_effect = [username_field, password_field]

        _login(page, profile, "secret")

        page.goto.assert_called_once_with(
            profile.url,
            wait_until="domcontentloaded",
            timeout=60000,
        )
        self.assertEqual(
            [call.args[0] for call in page.locator.call_args_list],
            [
                'input[type="email"], input[name="email"]',
                'input[type="password"]',
            ],
        )
        username_field.fill.assert_called_once_with(profile.username)
        password_field.fill.assert_called_once_with("secret")

    def test_select_hotel_unit_clicks_current_and_target_labels(self):
        page = Mock()
        selector = Mock()
        menu = Mock()
        target_label = Mock()
        selector.count.return_value = 1
        selector.inner_text.return_value = " HOTEL PORTINARI CENTRO "
        target_label.count.return_value = 1
        menu.get_by_text.return_value = target_label
        page.locator.side_effect = lambda value: (
            selector
            if value == "button.dropdown-toggle.abrevia-texto"
            else menu
        )

        _select_hotel_unit(
            page,
            "HOTEL PORTINARI CENTRO",
            "HOTEL PORTINARI PONTE DA AMIZADE (1860)",
        )

        selector.click.assert_called_once_with()
        menu.get_by_text.assert_called_once_with(
            "HOTEL PORTINARI PONTE DA AMIZADE (1860)",
            exact=True,
        )
        target_label.click.assert_called_once_with()
        page.wait_for_function.assert_called_once_with(
            ANY,
            arg={
                "selector": "button.dropdown-toggle.abrevia-texto",
                "target": "HOTEL PORTINARI PONTE DA AMIZADE (1860)",
                "displayTarget": "HOTEL PORTINARI PONTE DA AMIZADE",
            },
            timeout=20000,
        )
        page.wait_for_load_state.assert_called_once_with(
            "networkidle",
            timeout=30000,
        )

    def test_select_hotel_unit_skips_when_target_is_already_selected(self):
        page = Mock()

        _select_hotel_unit(page, "Hotel", " hotel ")

        page.get_by_text.assert_not_called()

    def test_reservation_report_waits_for_fields_not_a_heading(self):
        profile = new_hotel_profile(
            "Centro",
            "https://desbravadorweb.com.br/acesso/4846",
            "user@example.com",
        )
        page = Mock()
        period = calculate_report_period()

        with patch("collectors.desbravador_web._set_date") as set_date:
            _prepare_report(page, RESERVATION_REPORT, profile, period)

        self.assertEqual(
            [call.args[1] for call in set_date.call_args_list],
            ["Data Início", "Data Fim"],
        )
        page.get_by_role.assert_not_called()

    def test_date_interaction_reports_blocking_system_dialog(self):
        page = Mock()
        field = Mock()
        field.get_attribute.return_value = "text"
        field.click.side_effect = PlaywrightTimeoutError("click timed out")
        page.get_by_label.return_value = field
        dialog = Mock()
        dialog.is_visible.return_value = True
        dialog.inner_text.return_value = (
            "Não foi possível gerar o relatório para o período."
        )
        page.locator.return_value.last = dialog

        with self.assertRaisesRegex(
            RuntimeError,
            "Não foi possível gerar o relatório para o período",
        ):
            _set_date(page, "Data Início", "01/11/2026")

    def test_collects_primary_then_additional_unit_before_logout(self):
        profile = new_hotel_profile(
            "Centro",
            "https://desbravadorweb.com.br/acesso/4846",
            "user@example.com",
        )
        profile.additional_unit = "HOTEL PORTINARI PONTE DA AMIZADE (1860)"
        events = []
        page = Mock()
        page.goto = Mock()
        context = Mock()
        context.pages = [page]
        playwright = Mock()
        playwright.chromium.launch_persistent_context.return_value = context
        playwright_context = MagicMock()
        playwright_context.__enter__.return_value = playwright
        switch_args = []

        def prepare(*args):
            report = args[1]
            events.append(f"prepare-{report['kind']}")
            return "https://desbravadorweb.com.br"

        def fetch(*args):
            route = args[2]
            events.append("fetch-C" if "Reservas" in route else "fetch-R")
            return b"csv"

        def convert(*_):
            events.append("convert")
            return {"corrected_dates": 0}

        with tempfile.TemporaryDirectory() as output_directory:
            profile_directory = Path(output_directory) / "chrome-profile"
            with (
                patch(
                    "collectors.desbravador_web.sync_playwright",
                    return_value=playwright_context,
                ),
                patch(
                    "collectors.desbravador_web._browser_profile_directory",
                    return_value=profile_directory,
                ),
                patch(
                    "collectors.desbravador_web._login",
                    side_effect=lambda *_: events.append("login"),
                ),
                patch(
                    "collectors.desbravador_web._dismiss_optional_notices",
                    side_effect=lambda *_: events.append("dismiss"),
                ),
                patch("collectors.desbravador_web._prepare_report", side_effect=prepare),
                patch("collectors.desbravador_web._fetch_csv", side_effect=fetch),
                patch("collectors.desbravador_web.convert_csv_to_xls", side_effect=convert),
                patch(
                    "collectors.desbravador_web._select_hotel_unit",
                    side_effect=lambda *args: (
                        events.append("switch"),
                        switch_args.append(args[1:]),
                    ),
                ),
                patch(
                    "collectors.desbravador_web._logout",
                    side_effect=lambda *_: events.append("logout"),
                ),
            ):
                result = collect_reports(
                    profile,
                    "secret",
                    output_directory,
                )
            self.assertTrue(profile_directory.is_dir())

        self.assertEqual(
            events,
            [
                "login",
                "dismiss",
                "prepare-C",
                "fetch-C",
                "convert",
                "prepare-R",
                "fetch-R",
                "convert",
                "switch",
                "prepare-C",
                "fetch-C",
                "convert",
                "prepare-R",
                "fetch-R",
                "convert",
                "logout",
            ],
        )
        self.assertEqual(
            [report.unit_name for report in result.reports],
            [
                profile.name,
                profile.name,
                profile.additional_unit,
                profile.additional_unit,
            ],
        )
        self.assertEqual(
            switch_args,
            [
                (
                    "HOTEL PORTINARI CENTRO",
                    profile.additional_unit,
                )
            ],
        )
        playwright.chromium.launch_persistent_context.assert_called_once_with(
            str(profile_directory),
            channel="chrome",
            headless=False,
            args=["--no-first-run", "--no-default-browser-check"],
            accept_downloads=False,
        )
        context.new_page.assert_not_called()
        context.close.assert_called_once_with()
        page.goto.assert_called_once_with(
            "https://desbravadorweb.com.br/#/",
            wait_until="domcontentloaded",
            timeout=60000,
        )
        self.assertTrue(result.logout_confirmed)
        run_date = datetime.now().strftime("%d-%m-%Y")
        self.assertEqual(
            [Path(report.path).name for report in result.reports],
            [
                f"C-Centro {run_date}.xls",
                f"R-Centro {run_date}.xls",
                f"C-AMIZADE {run_date}.xls",
                f"R-AMIZADE {run_date}.xls",
            ],
        )


if __name__ == "__main__":
    unittest.main()
