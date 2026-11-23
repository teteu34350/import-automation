import unittest
from datetime import date
from pathlib import Path
import tempfile
from unittest import mock

from collectors import queops_desktop
from collectors.queops_desktop import (
    QueopsExportError,
    QueopsLoginError,
    QueopsNavigationError,
)


class QueopsWindowLookupTests(unittest.TestCase):
    def test_finds_window_when_accents_differ(self):
        desktop = mock.Mock()
        window = mock.Mock()
        window.window_text.return_value = "Visualizador de Relatorios"
        desktop.windows.return_value = [window]

        result = queops_desktop._find_window(
            desktop,
            "Visualizador de relatórios",
        )

        self.assertIs(result, window)

    def test_window_lookup_remains_case_insensitive(self):
        desktop = mock.Mock()
        window = mock.Mock()
        window.window_text.return_value = "RESUMO DE OCUPACAO"
        desktop.windows.return_value = [window]

        result = queops_desktop._find_window(
            desktop,
            "Resumo de ocupação",
        )

        self.assertIs(result, window)


class QueopsLoginTests(unittest.TestCase):
    def test_dismisses_startup_notice_before_waiting_for_login_window(self):
        login_window = mock.Mock()
        login_window.handle = 123
        login_window.is_visible.return_value = False

        with (
            mock.patch.object(
                queops_desktop,
                "_find_window",
                side_effect=[None, None, None, None, object()],
            ),
            mock.patch.object(
                queops_desktop,
                "_find_login_window",
                side_effect=[None, None, login_window],
            ),
            mock.patch.object(
                queops_desktop.Path,
                "is_file",
                return_value=True,
            ),
            mock.patch.object(queops_desktop.os, "startfile"),
            mock.patch.object(
                queops_desktop,
                "dismiss_queops_ccq_notice",
                side_effect=[True, False, False],
            ) as dismiss_notice,
            mock.patch.object(
                queops_desktop,
                "_foreground_window_handle",
                return_value=123,
            ),
            mock.patch.object(queops_desktop, "send_keys"),
        ):
            queops_desktop.login_queops(
                "user",
                "password",
                desktop=object(),
            )

        self.assertEqual(dismiss_notice.call_count, 3)
        self.assertEqual(
            login_window.click_input.call_args_list,
            [
                mock.call(coords=(365, 166)),
                mock.call(coords=(365, 200)),
                mock.call(coords=(310, 240)),
            ],
        )

    def test_dismisses_error_notification_during_login_and_succeeds(self):
        login_window = mock.Mock()
        login_window.handle = 123
        login_window.is_visible.side_effect = [True, False]
        home_window = mock.Mock()

        with (
            mock.patch.object(
                queops_desktop,
                "_find_window",
                side_effect=[None, None, None, None, None, home_window],
            ),
            mock.patch.object(
                queops_desktop,
                "_find_login_window",
                return_value=login_window,
            ),
            mock.patch.object(
                queops_desktop,
                "_foreground_window_handle",
                return_value=123,
            ),
            mock.patch.object(queops_desktop, "send_keys"),
            mock.patch.object(
                queops_desktop,
                "dismiss_queops_notice",
                return_value=True,
            ) as dismiss_notice,
        ):
            queops_desktop.login_queops(
                "io",
                "password",
                desktop=object(),
            )

        dismiss_notice.assert_called()

    def test_replaces_existing_login_field_contents(self):
        login_window = mock.Mock()

        with mock.patch.object(queops_desktop, "send_keys") as send_keys:
            queops_desktop._replace_login_field(
                login_window,
                (365, 166),
                "new-user",
            )

        login_window.click_input.assert_called_once_with(coords=(365, 166))
        self.assertEqual(
            send_keys.call_args_list,
            [
                mock.call("^a"),
                mock.call("{BACKSPACE}"),
                mock.call("new-user"),
            ],
        )

    def test_does_not_send_credentials_when_login_window_cannot_be_focused(self):
        login_window = mock.Mock()
        login_window.handle = 123

        with (
            mock.patch.object(
                queops_desktop,
                "_find_window",
                return_value=None,
            ),
            mock.patch.object(
                queops_desktop,
                "_find_login_window",
                return_value=login_window,
            ),
            mock.patch.object(
                queops_desktop,
                "_foreground_window_handle",
                return_value=456,
            ),
            mock.patch.object(queops_desktop, "send_keys") as send_keys,
        ):
            with self.assertRaisesRegex(
                QueopsLoginError,
                "ativar a janela de login",
            ):
                queops_desktop.login_queops(
                    "user",
                    "password",
                    desktop=object(),
                )

        login_window.click_input.assert_not_called()
        send_keys.assert_not_called()


class QueopsNoticeTests(unittest.TestCase):
    def test_dismisses_ccq_notice_and_waits_until_it_closes(self):
        desktop = mock.Mock()
        notice_window = mock.Mock()
        notice_window.handle = 123
        ok_button = mock.Mock()
        ok_button.class_name.return_value = "Button"
        ok_button.window_text.return_value = "OK"
        cancel_button = mock.Mock()
        cancel_button.class_name.return_value = "Button"
        cancel_button.window_text.return_value = "Cancelar"
        notice_window.descendants.return_value = [cancel_button, ok_button]

        with (
            mock.patch.object(
                queops_desktop,
                "_find_window",
                side_effect=[notice_window, None],
            ),
            mock.patch.object(
                queops_desktop,
                "_foreground_window_handle",
                return_value=123,
            ),
            mock.patch.object(
                queops_desktop.time,
                "monotonic",
                side_effect=[0, 0],
            ),
            mock.patch.object(queops_desktop.time, "sleep"),
        ):
            result = queops_desktop.dismiss_queops_ccq_notice(desktop)

        self.assertTrue(result)
        notice_window.descendants.assert_called_once_with()
        ok_button.click_input.assert_called_once_with()
        cancel_button.click_input.assert_not_called()
        notice_window.click_input.assert_not_called()

    def test_uses_notice_relative_ok_position_when_button_is_not_exposed(self):
        desktop = mock.Mock()
        notice_window = mock.Mock()
        notice_window.handle = 123
        notice_window.descendants.return_value = []
        notice_window.client_rect.return_value.width.return_value = 386
        notice_window.client_rect.return_value.height.return_value = 162

        with (
            mock.patch.object(
                queops_desktop,
                "_find_window",
                side_effect=[notice_window, None],
            ),
            mock.patch.object(
                queops_desktop,
                "_foreground_window_handle",
                return_value=123,
            ),
            mock.patch.object(
                queops_desktop.time,
                "monotonic",
                side_effect=[0, 0],
            ),
            mock.patch.object(queops_desktop.time, "sleep"),
        ):
            result = queops_desktop.dismiss_queops_ccq_notice(desktop)

        self.assertTrue(result)
        notice_window.click_input.assert_called_once_with(
            coords=(193, 145),
        )

    def test_returns_without_clicking_when_ccq_notice_is_absent(self):
        desktop = mock.Mock()

        with mock.patch.object(
            queops_desktop,
            "_find_window",
            return_value=None,
        ):
            result = queops_desktop.dismiss_queops_ccq_notice(desktop)

        self.assertFalse(result)

    def test_dismisses_error_notice_and_waits_until_it_closes(self):
        desktop = mock.Mock()
        error_window = mock.Mock()
        error_window.handle = 456
        error_window.is_visible.return_value = False
        ok_button = mock.Mock()
        ok_button.class_name.return_value = "Button"
        ok_button.window_text.return_value = "OK"
        error_window.descendants.return_value = [ok_button]

        with (
            mock.patch.object(
                queops_desktop,
                "_find_window",
                side_effect=[None, error_window],
            ),
            mock.patch.object(
                queops_desktop,
                "_foreground_window_handle",
                return_value=456,
            ),
            mock.patch.object(
                queops_desktop.time,
                "monotonic",
                side_effect=[0, 0],
            ),
            mock.patch.object(queops_desktop.time, "sleep"),
        ):
            result = queops_desktop.dismiss_queops_notice(desktop)

        self.assertTrue(result)
        ok_button.click_input.assert_called_once_with()

    def test_dismiss_queops_notice_returns_false_when_absent(self):
        desktop = mock.Mock()

        with mock.patch.object(
            queops_desktop,
            "_find_window",
            return_value=None,
        ):
            result = queops_desktop.dismiss_queops_notice(desktop)

        self.assertFalse(result)


class QueopsReportNavigationTests(unittest.TestCase):
    def test_opens_hospitality_module_from_queops_home_screen(self):
        desktop = mock.Mock()
        home_window = mock.Mock()
        operational_window = mock.Mock()
        report_window = mock.Mock()
        home_window.handle = 123
        operational_window.handle = 456

        with (
            mock.patch.object(
                queops_desktop,
                "_find_window",
                side_effect=[
                    None,
                    None,
                    home_window,
                    operational_window,
                    report_window,
                ],
            ),
            mock.patch.object(
                queops_desktop,
                "_foreground_window_handle",
                side_effect=[123, 456],
            ),
            mock.patch.object(queops_desktop.time, "sleep"),
        ):
            result = queops_desktop.open_expected_checkin_report(
                desktop=desktop,
            )

        self.assertIs(result, report_window)
        home_window.click_input.assert_called_once_with(
            coords=(343, 555),
            double=True,
        )
        self.assertEqual(operational_window.click_input.call_count, 2)

    def test_opens_expected_checkin_report_from_hospitality_module(self):
        desktop = mock.Mock()
        operational_window = mock.Mock()
        operational_window.handle = 123
        report_window = mock.Mock()

        with (
            mock.patch.object(
                queops_desktop,
                "_find_window",
                side_effect=[None, operational_window, report_window],
            ),
            mock.patch.object(
                queops_desktop,
                "_foreground_window_handle",
                return_value=123,
            ),
            mock.patch.object(queops_desktop.time, "sleep"),
        ):
            result = queops_desktop.open_expected_checkin_report(
                desktop=desktop,
            )

        self.assertIs(result, report_window)
        self.assertEqual(
            operational_window.click_input.call_args_list,
            [
                mock.call(
                    coords=queops_desktop.QUEOPS_OPERATIONAL_REPORTS_MENU_COORDS,
                ),
                mock.call(
                    coords=queops_desktop.QUEOPS_EXPECTED_CHECKINS_MENU_COORDS,
                ),
            ],
        )

    def test_reuses_existing_checkin_dialog(self):
        desktop = mock.Mock()
        existing_report_window = mock.Mock()

        with (
            mock.patch.object(
                queops_desktop,
                "_find_window",
                return_value=existing_report_window,
            ),
        ):
            result = queops_desktop.open_expected_checkin_report(
                desktop=desktop,
            )

        self.assertIs(result, existing_report_window)

    def test_opens_occupancy_forecast_report_from_hospitality_module(self):
        desktop = mock.Mock()
        operational_window = mock.Mock()
        operational_window.handle = 123
        report_window = mock.Mock()

        with (
            mock.patch.object(
                queops_desktop,
                "_find_window",
                side_effect=[
                    None,
                    None,
                    None,
                    operational_window,
                    report_window,
                ],
            ),
            mock.patch.object(
                queops_desktop,
                "_foreground_window_handle",
                return_value=123,
            ),
            mock.patch.object(queops_desktop.time, "sleep"),
        ):
            result = queops_desktop.open_occupancy_forecast_report(
                desktop=desktop,
            )

        self.assertIs(result, report_window)
        self.assertEqual(
            operational_window.click_input.call_args_list,
            [
                mock.call(
                    coords=queops_desktop.QUEOPS_OPERATIONAL_REPORTS_MENU_COORDS,
                ),
                mock.call(
                    coords=queops_desktop.QUEOPS_OCCUPANCY_FORECAST_MENU_COORDS,
                ),
            ],
        )

    def test_opens_hospitality_module_before_occupancy_report_from_home(self):
        desktop = mock.Mock()
        home_window = mock.Mock()
        home_window.handle = 123
        operational_window = mock.Mock()
        operational_window.handle = 456
        report_window = mock.Mock()

        with (
            mock.patch.object(
                queops_desktop,
                "_find_window",
                side_effect=[None, home_window],
            ),
            mock.patch.object(
                queops_desktop,
                "_wait_for_window",
                side_effect=[operational_window, report_window],
            ),
            mock.patch.object(
                queops_desktop,
                "_foreground_window_handle",
                side_effect=[123, 456],
            ),
            mock.patch.object(queops_desktop.time, "sleep"),
        ):
            result = queops_desktop.open_occupancy_forecast_report(
                desktop=desktop,
            )

        self.assertIs(result, report_window)
        home_window.click_input.assert_called_once_with(
            coords=(343, 555),
            double=True,
        )
        self.assertEqual(
            operational_window.click_input.call_args_list,
            [
                mock.call(
                    coords=queops_desktop.QUEOPS_OPERATIONAL_REPORTS_MENU_COORDS,
                ),
                mock.call(
                    coords=queops_desktop.QUEOPS_OCCUPANCY_FORECAST_MENU_COORDS,
                ),
            ],
        )

    def test_does_not_click_when_queops_window_cannot_be_focused(self):
        desktop = mock.Mock()
        operational_window = mock.Mock()
        operational_window.handle = 123

        with (
            mock.patch.object(
                queops_desktop,
                "_find_window",
                side_effect=[None, operational_window],
            ),
            mock.patch.object(
                queops_desktop,
                "_foreground_window_handle",
                return_value=456,
            ),
        ):
            with self.assertRaisesRegex(
                QueopsNavigationError,
                "ativar a janela",
            ):
                queops_desktop.open_expected_checkin_report(desktop=desktop)

        operational_window.click_input.assert_not_called()

    def test_reports_error_when_checkin_dialog_does_not_open(self):
        desktop = mock.Mock()
        operational_window = mock.Mock()
        operational_window.handle = 123

        with (
            mock.patch.object(
                queops_desktop,
                "_find_window",
                side_effect=[None, operational_window, None],
            ),
            mock.patch.object(
                queops_desktop,
                "_foreground_window_handle",
                return_value=123,
            ),
            mock.patch.object(queops_desktop.time, "sleep"),
        ):
            with self.assertRaisesRegex(
                QueopsNavigationError,
                "janela Check-in's esperados não abriu",
            ):
                queops_desktop.open_expected_checkin_report(
                    desktop=desktop,
                    timeout=0,
                )

    def test_opens_summary_occupancy_through_management_menus(self):
        desktop = mock.Mock()
        operational_window = mock.Mock()
        operational_window.handle = 123
        report_window = mock.Mock()

        with (
            mock.patch.object(
                queops_desktop,
                "_find_window",
                side_effect=[None, operational_window],
            ),
            mock.patch.object(
                queops_desktop,
                "_foreground_window_handle",
                return_value=123,
            ),
            mock.patch.object(
                queops_desktop,
                "_wait_for_window",
                return_value=report_window,
            ),
            mock.patch.object(queops_desktop.time, "sleep"),
        ):
            result = queops_desktop.open_summary_occupancy_report(
                desktop=desktop,
            )

        self.assertIs(result, report_window)
        self.assertEqual(
            operational_window.click_input.call_args_list,
            [
                mock.call(
                    coords=queops_desktop.QUEOPS_MANAGEMENT_REPORTS_MENU_COORDS,
                ),
                mock.call(
                    coords=queops_desktop.QUEOPS_MANAGEMENT_OCCUPANCY_MENU_COORDS,
                ),
                mock.call(
                    coords=queops_desktop.QUEOPS_SUMMARY_OCCUPANCY_MENU_COORDS,
                ),
            ],
        )

    def test_opens_summary_occupancy_from_home_with_double_click(self):
        desktop = mock.Mock()
        home_window = mock.Mock()
        home_window.handle = 123
        operational_window = mock.Mock()
        operational_window.handle = 456
        report_window = mock.Mock()

        with (
            mock.patch.object(
                queops_desktop,
                "_find_window",
                side_effect=[
                    None,
                    None,
                    home_window,
                    None,
                ],
            ),
            mock.patch.object(
                queops_desktop,
                "_foreground_window_handle",
                side_effect=[123, 456],
            ),
            mock.patch.object(
                queops_desktop,
                "_wait_for_window",
                side_effect=[operational_window, report_window],
            ),
            mock.patch.object(queops_desktop.time, "sleep"),
        ):
            result = queops_desktop.open_summary_occupancy_report(
                desktop=desktop,
            )

        self.assertIs(result, report_window)
        home_window.click_input.assert_called_once_with(
            coords=queops_desktop.QUEOPS_HOSPITALITY_ICON_COORDS,
            double=True,
        )

    def test_opens_rds_from_management_menu(self):
        desktop = mock.Mock()
        operational_window = mock.Mock()
        operational_window.handle = 123
        report_window = mock.Mock()

        with (
            mock.patch.object(
                queops_desktop,
                "_find_window",
                side_effect=[None, operational_window],
            ),
            mock.patch.object(
                queops_desktop,
                "_foreground_window_handle",
                return_value=123,
            ),
            mock.patch.object(
                queops_desktop,
                "_wait_for_window",
                return_value=report_window,
            ),
            mock.patch.object(queops_desktop.time, "sleep"),
        ):
            result = queops_desktop.open_rds_report(desktop=desktop)

        self.assertIs(result, report_window)
        self.assertEqual(
            operational_window.click_input.call_args_list,
            [
                mock.call(
                    coords=queops_desktop.QUEOPS_MANAGEMENT_REPORTS_MENU_COORDS,
                ),
                mock.call(coords=queops_desktop.QUEOPS_RDS_MENU_COORDS),
            ],
        )


class QueopsReportGenerationTests(unittest.TestCase):
    def test_sets_next_year_date_and_required_filters_before_confirming(self):
        desktop = mock.Mock()
        report_window = mock.Mock()
        report_window.handle = 123
        report_viewer = mock.Mock()

        with (
            mock.patch.object(
                queops_desktop,
                "_foreground_window_handle",
                return_value=123,
            ),
            mock.patch.object(
                queops_desktop,
                "_wait_for_window",
                return_value=report_viewer,
            ) as wait_for_window,
            mock.patch.object(queops_desktop, "send_keys") as send_keys,
            mock.patch.object(
                queops_desktop,
                "_checkbox_is_checked",
                side_effect=[False, True, True],
            ),
            mock.patch.object(queops_desktop.time, "sleep"),
        ):
            result = queops_desktop.configure_and_generate_expected_checkin_report(
                report_window,
                desktop=desktop,
                reference_date=date(2026, 11, 13),
            )

        self.assertIs(result, report_viewer)
        wait_for_window.assert_called_once_with(
            desktop,
            "Visualizador de relatórios",
            queops_desktop.QUEOPS_REPORT_GENERATION_TIMEOUT,
        )
        self.assertEqual(
            send_keys.call_args_list,
            [
                mock.call("13"),
                mock.call("11"),
                mock.call("2027"),
            ],
        )
        click_calls = report_window.click_input.call_args_list
        self.assertEqual(len(click_calls), 6)
        self.assertEqual(
            click_calls[:4],
            [
                mock.call(
                    coords=queops_desktop.QUEOPS_REPORT_CLOSED_FILTER_COORDS,
                ),
                mock.call(coords=queops_desktop.QUEOPS_REPORT_FINAL_DATE_DAY_COORDS),
                mock.call(
                    coords=queops_desktop.QUEOPS_REPORT_FINAL_DATE_MONTH_COORDS,
                ),
                mock.call(coords=queops_desktop.QUEOPS_REPORT_FINAL_DATE_YEAR_COORDS),
            ],
        )
        self.assertEqual(
            click_calls[4:],
            [
                mock.call(
                    coords=queops_desktop.QUEOPS_REPORT_TOTAL_DAILY_OPTION_COORDS,
                ),
                mock.call(coords=queops_desktop.QUEOPS_REPORT_CONFIRM_COORDS),
            ],
        )

    def test_errors_when_expected_checkin_filter_remains_unchecked(self):
        report_window = mock.Mock()

        with (
            mock.patch.object(
                queops_desktop,
                "_checkbox_is_checked",
                side_effect=[False, False, False, False],
            ),
            self.assertRaisesRegex(
                QueopsNavigationError,
                "Não foi possível marcar os filtros Fechado e Diária",
            ),
        ):
            queops_desktop._ensure_expected_checkin_filters_checked(report_window)

        report_window.click_input.assert_has_calls(
            [
                mock.call(
                    coords=queops_desktop.QUEOPS_REPORT_CLOSED_FILTER_COORDS,
                ),
                mock.call(
                    coords=queops_desktop.QUEOPS_REPORT_DAILY_FILTER_COORDS,
                ),
            ],
        )

    def test_reads_checked_state_from_checkbox_pixels(self):
        report_window = mock.Mock()
        report_window.handle = 123
        coordinates = queops_desktop.QUEOPS_REPORT_CLOSED_FILTER_COORDS

        for checked in (False, True):
            def get_pixel(device_context, x, y):
                is_checkmark = (
                    abs(x - coordinates[0]) <= 2
                    and abs(y - coordinates[1]) <= 2
                )
                return 0 if checked and is_checkmark else 0xFFFFFF

            with (
                mock.patch.object(
                    queops_desktop.win32gui,
                    "GetWindowDC",
                    return_value=456,
                ),
                mock.patch.object(
                    queops_desktop.win32gui,
                    "GetPixel",
                    side_effect=get_pixel,
                ),
                mock.patch.object(
                    queops_desktop.win32gui,
                    "ReleaseDC",
                ) as release_dc,
            ):
                self.assertEqual(
                    queops_desktop._checkbox_is_checked(
                        report_window,
                        coordinates,
                    ),
                    checked,
                )

            release_dc.assert_called_once_with(123, 456)

    def test_closes_report_dialog_with_cancel_button(self):
        report_window = mock.Mock()
        report_window.handle = 123
        report_window.window_text.return_value = "Check-in's esperados"

        with (
            mock.patch.object(
                queops_desktop,
                "_foreground_window_handle",
                return_value=123,
            ),
        ):
            queops_desktop.close_queops_report_window(report_window)

        report_window.click_input.assert_called_once_with(
            coords=queops_desktop.QUEOPS_REPORT_CANCEL_COORDS,
        )

    def test_reports_impossible_next_year_date(self):
        report_window = mock.Mock()

        with self.assertRaisesRegex(
            QueopsNavigationError,
            "não existe no ano seguinte",
        ):
            queops_desktop.configure_and_generate_expected_checkin_report(
                report_window,
                desktop=mock.Mock(),
                reference_date=date(2024, 2, 29),
            )

        report_window.click_input.assert_not_called()

    def test_configures_occupancy_forecast_and_confirms(self):
        desktop = mock.Mock()
        report_window = mock.Mock()
        report_window.handle = 123
        report_viewer = mock.Mock()

        with (
            mock.patch.object(
                queops_desktop,
                "_foreground_window_handle",
                return_value=123,
            ),
            mock.patch.object(
                queops_desktop,
                "_wait_for_window",
                return_value=report_viewer,
            ) as wait_for_window,
            mock.patch.object(queops_desktop, "send_keys") as send_keys,
            mock.patch.object(queops_desktop.time, "sleep"),
        ):
            result = queops_desktop.configure_and_generate_occupancy_forecast_report(
                report_window,
                desktop=desktop,
                reference_date=date(2026, 11, 13),
            )

        self.assertIs(result, report_viewer)
        send_keys.assert_called_once_with("^{PGDN}")
        self.assertEqual(
            report_window.click_input.call_args_list,
            [
                mock.call(coords=(389, 70)),
                mock.call(coords=(195, 165)),
                mock.call(coords=(20, 100)),
                mock.call(coords=(131, 295)),
            ],
        )
        wait_for_window.assert_called_once_with(
            desktop,
            "Visualizador de relatórios",
            queops_desktop.QUEOPS_REPORT_GENERATION_TIMEOUT,
        )

    def test_configures_c_past_period_and_company_filter(self):
        desktop = mock.Mock()
        report_window = mock.Mock()
        report_window.handle = 123
        report_viewer = mock.Mock()
        reference_date = date(2026, 11, 17)

        with (
            mock.patch.object(
                queops_desktop,
                "_foreground_window_handle",
                return_value=123,
            ),
            mock.patch.object(
                queops_desktop,
                "_wait_for_window",
                return_value=report_viewer,
            ) as wait_for_window,
            mock.patch.object(queops_desktop.time, "sleep"),
        ):
            result = (
                queops_desktop.configure_and_generate_summary_occupancy_report(
                    report_window,
                    desktop=desktop,
                    reference_date=reference_date,
                )
            )

        self.assertIs(result, report_viewer)
        self.assertEqual(
            report_window.click_input.call_args_list,
            [
                mock.call(
                    coords=queops_desktop.QUEOPS_SUMMARY_START_DATE_DROPDOWN_COORDS,
                ),
                mock.call(coords=(122, 150)),
                mock.call(
                    coords=queops_desktop.QUEOPS_SUMMARY_END_DATE_DROPDOWN_COORDS,
                ),
                mock.call(coords=(412, 186)),
                mock.call(
                    coords=queops_desktop.QUEOPS_SUMMARY_COMPANY_FILTER_COORDS,
                ),
                mock.call(
                    coords=queops_desktop.QUEOPS_SUMMARY_CONFIRM_COORDS,
                ),
            ],
        )
        wait_for_window.assert_called_once_with(
            desktop,
            "Visualizador de relatórios",
            queops_desktop.QUEOPS_REPORT_GENERATION_TIMEOUT,
        )

    def test_configures_rds_dates_without_changing_filters(self):
        desktop = mock.Mock()
        report_window = mock.Mock()
        report_window.handle = 123
        report_viewer = mock.Mock()
        reference_date = date(2026, 11, 17)

        with (
            mock.patch.object(
                queops_desktop,
                "_foreground_window_handle",
                return_value=123,
            ),
            mock.patch.object(
                queops_desktop,
                "_wait_for_window",
                return_value=report_viewer,
            ) as wait_for_window,
            mock.patch.object(queops_desktop.time, "sleep"),
        ):
            result = queops_desktop.configure_and_generate_rds_report(
                report_window,
                desktop=desktop,
                reference_date=reference_date,
            )

        self.assertIs(result, report_viewer)
        self.assertEqual(
            report_window.click_input.call_args_list,
            [
                mock.call(
                    coords=queops_desktop.QUEOPS_RDS_END_DATE_DROPDOWN_COORDS,
                ),
                mock.call(coords=(295, 233)),
                mock.call(
                    coords=queops_desktop.QUEOPS_RDS_REFERENCE_DATE_DROPDOWN_COORDS,
                ),
                mock.call(coords=(286, 193)),
                mock.call(coords=queops_desktop.QUEOPS_RDS_CONFIRM_COORDS),
            ],
        )
        wait_for_window.assert_called_once_with(
            desktop,
            "Visualizador de relatórios",
            queops_desktop.QUEOPS_RDS_GENERATION_TIMEOUT,
        )

    def test_month_to_yesterday_reports_fail_on_first_day_without_clicking(self):
        report_window = mock.Mock()

        with self.assertRaisesRegex(
            QueopsNavigationError,
            "Não há dias concluídos",
        ):
            queops_desktop.configure_and_generate_rds_report(
                report_window,
                desktop=mock.Mock(),
                reference_date=date(2026, 11, 1),
            )

        report_window.click_input.assert_not_called()

    def test_reports_error_when_report_viewer_does_not_open(self):
        report_window = mock.Mock()
        report_window.handle = 123
        desktop = mock.Mock()

        with (
            mock.patch.object(
                queops_desktop,
                "_foreground_window_handle",
                return_value=123,
            ),
            mock.patch.object(queops_desktop, "send_keys"),
            mock.patch.object(
                queops_desktop,
                "_checkbox_is_checked",
                return_value=True,
            ),
            mock.patch.object(
                queops_desktop,
                "_wait_for_window",
                return_value=None,
            ),
            mock.patch.object(queops_desktop.time, "sleep"),
        ):
            with self.assertRaisesRegex(
                QueopsNavigationError,
                "Visualizador de relatórios não abriu",
            ):
                queops_desktop.configure_and_generate_expected_checkin_report(
                    report_window,
                    desktop=desktop,
                    reference_date=date(2026, 11, 13),
                )

        self.assertEqual(
            report_window.click_input.call_args,
            mock.call(coords=(191, 468)),
        )


class QueopsReportExportTests(unittest.TestCase):
    def test_saves_excel_to_downloads_with_short_hotel_name_and_date(self):
        desktop = mock.Mock()
        report_viewer = mock.Mock()
        report_viewer.handle = 123
        save_dialog = mock.Mock()
        save_dialog.handle = 456
        reference_date = date(2026, 11, 13)

        with tempfile.TemporaryDirectory() as temporary_directory:
            downloads = Path(temporary_directory)
            destination = downloads / "C-FUT Pontal 13-11.xls"

            def save_file(*, coords):
                if coords == (753, 494):
                    destination.write_bytes(b"Excel report")

            save_dialog.click_input.side_effect = save_file
            with (
                mock.patch.object(
                    queops_desktop,
                    "_foreground_window_handle",
                    side_effect=[123, 456],
                ),
                mock.patch.object(
                    queops_desktop,
                    "_wait_for_window",
                    return_value=save_dialog,
                ) as wait_for_window,
                mock.patch.object(
                    queops_desktop,
                    "_find_window",
                    return_value=report_viewer,
                ),
                mock.patch.object(
                    queops_desktop,
                    "send_keys",
                ) as send_keys,
                mock.patch.object(queops_desktop.time, "sleep"),
            ):
                result = queops_desktop.export_expected_checkin_report(
                    report_viewer,
                    "Pontal do Mundai",
                    desktop=desktop,
                    downloads_directory=downloads,
                    reference_date=reference_date,
                )

        self.assertEqual(result, destination)
        report_viewer.click_input.assert_called_once_with(coords=(281, 50))
        wait_for_window.assert_called_once_with(desktop, "Salvar como", 60)
        self.assertEqual(
            save_dialog.click_input.call_args_list,
            [
                mock.call(coords=(675, 529)),
                mock.call(coords=(430, 494)),
                mock.call(coords=(753, 494)),
            ],
        )
        self.assertEqual(
            send_keys.call_args_list,
            [
                mock.call("M"),
                mock.call("{ENTER}"),
                mock.call("^a"),
                mock.call("{BACKSPACE}"),
                mock.call("C-FUT Pontal 13-11", with_spaces=True),
            ],
        )

    def test_uses_a_new_name_when_an_excel_report_already_exists(self):
        desktop = mock.Mock()
        report_viewer = mock.Mock()
        report_viewer.handle = 123
        save_dialog = mock.Mock()
        save_dialog.handle = 456

        with tempfile.TemporaryDirectory() as temporary_directory:
            downloads = Path(temporary_directory)
            original = downloads / "C-FUT Pontal 13-11.xls"
            destination = downloads / "C-FUT Pontal 13-11 2.xls"
            original.write_bytes(b"keep")

            def save_file(*, coords):
                if coords == queops_desktop.QUEOPS_SAVE_BUTTON_COORDS:
                    destination.write_bytes(b"new report")

            save_dialog.click_input.side_effect = save_file
            with (
                mock.patch.object(
                    queops_desktop,
                    "_foreground_window_handle",
                    side_effect=[123, 456],
                ),
                mock.patch.object(
                    queops_desktop,
                    "_wait_for_window",
                    return_value=save_dialog,
                ),
                mock.patch.object(
                    queops_desktop,
                    "_find_window",
                    return_value=report_viewer,
                ),
                mock.patch.object(queops_desktop, "send_keys") as send_keys,
                mock.patch.object(queops_desktop.time, "sleep"),
            ):
                result = queops_desktop.export_expected_checkin_report(
                    report_viewer,
                    "Pontal do Mundai",
                    desktop=desktop,
                    downloads_directory=downloads,
                    reference_date=date(2026, 11, 13),
                )

            self.assertEqual(original.read_bytes(), b"keep")
            self.assertEqual(destination.read_bytes(), b"new report")
            self.assertEqual(result, destination)
            self.assertIn(
                mock.call("C-FUT Pontal 13-11 2", with_spaces=True),
                send_keys.call_args_list,
            )

    def test_saves_occupancy_report_with_r_prefix(self):
        desktop = mock.Mock()
        report_viewer = mock.Mock()
        report_viewer.handle = 123
        save_dialog = mock.Mock()
        save_dialog.handle = 456
        reference_date = date(2026, 11, 13)

        with tempfile.TemporaryDirectory() as temporary_directory:
            downloads = Path(temporary_directory)
            destination = downloads / "R-Pontal do Mundai 13-11.xls"

            def save_file(*, coords):
                if coords == (753, 494):
                    destination.write_bytes(b"Excel report")

            save_dialog.click_input.side_effect = save_file
            with (
                mock.patch.object(
                    queops_desktop,
                    "_foreground_window_handle",
                    side_effect=[123, 456],
                ),
                mock.patch.object(
                    queops_desktop,
                    "_wait_for_window",
                    return_value=save_dialog,
                ),
                mock.patch.object(
                    queops_desktop,
                    "_find_window",
                    return_value=report_viewer,
                ),
                mock.patch.object(queops_desktop, "send_keys") as send_keys,
                mock.patch.object(queops_desktop.time, "sleep"),
            ):
                result = queops_desktop.export_queops_report(
                    report_viewer,
                    "Pontal do Mundai",
                    "R",
                    desktop=desktop,
                    downloads_directory=downloads,
                    reference_date=reference_date,
                    use_short_hotel_name=False,
                    prefix_separator="-",
                )

        self.assertEqual(result, destination)
        self.assertIn(
            mock.call("R-Pontal do Mundai 13-11", with_spaces=True),
            send_keys.call_args_list,
        )

    def test_saves_rds_as_pdf_with_reference_date_in_filename(self):
        desktop = mock.Mock()
        report_viewer = mock.Mock()
        report_viewer.handle = 123
        save_dialog = mock.Mock()
        save_dialog.handle = 456
        reference_date = date(2026, 11, 16)

        with tempfile.TemporaryDirectory() as temporary_directory:
            downloads = Path(temporary_directory)
            destination = downloads / "rds-pontal 16-11.pdf"

            def save_file(*, coords):
                if coords == queops_desktop.QUEOPS_SAVE_BUTTON_COORDS:
                    destination.write_bytes(b"PDF report")

            save_dialog.click_input.side_effect = save_file
            with (
                mock.patch.object(
                    queops_desktop,
                    "_foreground_window_handle",
                    side_effect=[123, 456],
                ),
                mock.patch.object(
                    queops_desktop,
                    "_wait_for_window",
                    return_value=save_dialog,
                ) as wait_for_window,
                mock.patch.object(
                    queops_desktop,
                    "_find_window",
                    return_value=report_viewer,
                ),
                mock.patch.object(queops_desktop, "send_keys") as send_keys,
                mock.patch.object(queops_desktop.time, "sleep"),
            ):
                result = queops_desktop.export_rds_report(
                    report_viewer,
                    "Pontal do Mundai",
                    desktop=desktop,
                    downloads_directory=downloads,
                    reference_date=reference_date,
                )

            self.assertEqual(result, destination)
            self.assertEqual(destination.read_bytes(), b"PDF report")
        wait_for_window.assert_called_once_with(
            desktop,
            "Salvar como",
            60,
        )
        self.assertIn(
            mock.call("A"),
            send_keys.call_args_list,
        )
        self.assertIn(
            mock.call("rds-pontal 16-11", with_spaces=True),
            send_keys.call_args_list,
        )

    def test_reports_error_if_save_dialog_does_not_open(self):
        report_viewer = mock.Mock()
        report_viewer.handle = 123

        with tempfile.TemporaryDirectory() as temporary_directory:
            with (
                mock.patch.object(
                    queops_desktop,
                    "_foreground_window_handle",
                    return_value=123,
                ),
                mock.patch.object(
                    queops_desktop,
                    "_wait_for_window",
                    return_value=None,
                ),
                mock.patch.object(
                    queops_desktop,
                    "_find_window",
                    return_value=report_viewer,
                ),
            ):
                with self.assertRaisesRegex(
                    QueopsExportError,
                    "Salvar como não abriu",
                ):
                    queops_desktop.export_expected_checkin_report(
                        report_viewer,
                        "Pontal do Mundai",
                        downloads_directory=temporary_directory,
                    )

    def test_closes_the_current_viewer_instead_of_a_stale_wrapper(self):
        desktop = mock.Mock()
        stale_viewer = mock.Mock()
        current_viewer = mock.Mock()
        current_viewer.handle = 123

        with (
            mock.patch.object(
                queops_desktop,
                "Desktop",
                return_value=desktop,
            ),
            mock.patch.object(
                queops_desktop,
                "_find_window",
                return_value=current_viewer,
            ) as find_window,
            mock.patch.object(
                queops_desktop,
                "_foreground_window_handle",
                return_value=123,
            ),
        ):
            queops_desktop.close_queops_report_viewer(stale_viewer)

        find_window.assert_called_once_with(desktop, "Visualizador de relatórios")
        current_viewer.click_input.assert_called_once_with(
            coords=queops_desktop.QUEOPS_REPORT_VIEWER_EXIT_COORDS,
        )
        stale_viewer.click_input.assert_not_called()


class QueopsCollectionTests(unittest.TestCase):
    def test_collects_all_four_reports_in_order(self):
        hotel = mock.Mock()
        hotel.name = "Pontal do Mundai"
        hotel.username = "io"
        desktop = mock.Mock()
        reference_date = date(2026, 11, 17)
        report_windows = [mock.Mock() for _ in range(4)]
        report_viewers = [mock.Mock() for _ in range(4)]
        report_paths = [
            Path("C-FUT Pontal 17-11.xls"),
            Path("C-PAST Pontal 17-11.xls"),
            Path("R-Pontal do Mundai 17-11.xls"),
            Path("rds-pontal 16-11.pdf"),
        ]
        progress_messages = []

        with (
            mock.patch.object(
                queops_desktop,
                "Desktop",
                return_value=desktop,
            ),
            mock.patch.object(queops_desktop, "login_queops") as login,
            mock.patch.object(
                queops_desktop,
                "dismiss_queops_ccq_notice",
            ) as dismiss_notice,
            mock.patch.object(
                queops_desktop,
                "open_expected_checkin_report",
                return_value=report_windows[0],
            ) as open_checkins,
            mock.patch.object(
                queops_desktop,
                "configure_and_generate_expected_checkin_report",
                return_value=report_viewers[0],
            ) as configure_checkins,
            mock.patch.object(
                queops_desktop,
                "export_expected_checkin_report",
                return_value=report_paths[0],
            ) as export_checkins,
            mock.patch.object(
                queops_desktop,
                "close_queops_report_viewer",
            ) as close_viewer,
            mock.patch.object(
                queops_desktop,
                "close_queops_report_window",
            ) as close_report_window,
            mock.patch.object(
                queops_desktop,
                "open_summary_occupancy_report",
                return_value=report_windows[1],
            ) as open_summary,
            mock.patch.object(
                queops_desktop,
                "configure_and_generate_summary_occupancy_report",
                return_value=report_viewers[1],
            ) as configure_summary,
            mock.patch.object(
                queops_desktop,
                "export_past_occupancy_report",
                return_value=report_paths[1],
            ) as export_past,
            mock.patch.object(
                queops_desktop,
                "open_occupancy_forecast_report",
                return_value=report_windows[2],
            ) as open_occupancy,
            mock.patch.object(
                queops_desktop,
                "configure_and_generate_occupancy_forecast_report",
                return_value=report_viewers[2],
            ) as configure_occupancy,
            mock.patch.object(
                queops_desktop,
                "export_queops_report",
                return_value=report_paths[2],
            ) as export_occupancy,
            mock.patch.object(
                queops_desktop,
                "open_rds_report",
                return_value=report_windows[3],
            ) as open_rds,
            mock.patch.object(
                queops_desktop,
                "configure_and_generate_rds_report",
                return_value=report_viewers[3],
            ) as configure_rds,
            mock.patch.object(
                queops_desktop,
                "export_rds_report",
                return_value=report_paths[3],
            ) as export_rds,
        ):
            result = queops_desktop.collect_queops_report(
                hotel,
                "test-password",
                "unused-output",
                progress=progress_messages.append,
                reference_date=reference_date,
            )

        self.assertFalse(result.error)
        self.assertEqual(
            [report.path for report in result.reports],
            report_paths,
        )
        self.assertEqual(
            [report.report for report in result.reports],
            [
                "Check-in's esperados",
                "Resumo de Ocupação (C-PAST)",
                "Previsão de Ocupação",
                "Diário de situação (RDS)",
            ],
        )
        login.assert_called_once_with("io", "test-password", desktop=desktop)
        dismiss_notice.assert_called_once_with(desktop)
        self.assertEqual(
            [call.args[0] for call in close_viewer.call_args_list],
            report_viewers,
        )
        self.assertEqual(
            [call.args[0] for call in close_report_window.call_args_list],
            report_windows,
        )
        for report_window in report_windows:
            report_window.close.assert_not_called()
        for configure in (
            configure_checkins,
            configure_summary,
            configure_occupancy,
            configure_rds,
        ):
            self.assertEqual(
                configure.call_args.kwargs["reference_date"],
                reference_date,
            )
        self.assertEqual(
            export_rds.call_args.kwargs["reference_date"],
            date(2026, 11, 16),
        )
        self.assertTrue(progress_messages)
        self.assertEqual(
            result.expected_report_count,
            queops_desktop.QUEOPS_EXPECTED_REPORT_COUNT,
        )
        self.assertTrue(result.all_reports_succeeded)

    def test_collection_continues_after_a_report_fails(self):
        hotel = mock.Mock()
        hotel.name = "Pontal do Mundai"
        hotel.username = "io"
        desktop = mock.Mock()
        report_windows = [mock.Mock() for _ in range(3)]
        report_viewers = [mock.Mock() for _ in range(3)]
        report_paths = [
            Path("C-FUT Pontal 17-11.xls"),
            Path("R-Pontal do Mundai 17-11.xls"),
            Path("rds-pontal 16-11.pdf"),
        ]

        with (
            mock.patch.object(
                queops_desktop,
                "Desktop",
                return_value=desktop,
            ),
            mock.patch.object(queops_desktop, "login_queops"),
            mock.patch.object(queops_desktop, "dismiss_queops_ccq_notice"),
            mock.patch.object(
                queops_desktop,
                "open_expected_checkin_report",
                return_value=report_windows[0],
            ),
            mock.patch.object(
                queops_desktop,
                "configure_and_generate_expected_checkin_report",
                return_value=report_viewers[0],
            ),
            mock.patch.object(
                queops_desktop,
                "export_expected_checkin_report",
                return_value=report_paths[0],
            ),
            mock.patch.object(queops_desktop, "close_queops_report_viewer"),
            mock.patch.object(queops_desktop, "close_queops_report_window"),
            mock.patch.object(
                queops_desktop,
                "open_summary_occupancy_report",
                side_effect=QueopsNavigationError("C-PAST indisponível"),
            ) as open_summary,
            mock.patch.object(
                queops_desktop,
                "open_occupancy_forecast_report",
                return_value=report_windows[1],
            ) as open_occupancy,
            mock.patch.object(
                queops_desktop,
                "configure_and_generate_occupancy_forecast_report",
                return_value=report_viewers[1],
            ),
            mock.patch.object(
                queops_desktop,
                "export_queops_report",
                return_value=report_paths[1],
            ),
            mock.patch.object(
                queops_desktop,
                "open_rds_report",
                return_value=report_windows[2],
            ) as open_rds,
            mock.patch.object(
                queops_desktop,
                "configure_and_generate_rds_report",
                return_value=report_viewers[2],
            ),
            mock.patch.object(
                queops_desktop,
                "export_rds_report",
                return_value=report_paths[2],
            ),
        ):
            result = queops_desktop.collect_queops_report(
                hotel,
                "test-password",
                "unused-output",
                reference_date=date(2026, 11, 17),
            )

        self.assertEqual(
            [report.status for report in result.reports],
            ["success", "failed", "success", "success"],
        )
        self.assertIn("C-PAST indisponível", result.error)
        self.assertFalse(result.all_reports_succeeded)
        open_summary.assert_called_once()
        open_occupancy.assert_called_once()
        open_rds.assert_called_once()

    def test_skips_collection_when_month_has_no_completed_day(self):
        hotel = mock.Mock()
        hotel.name = "Pontal do Mundai"
        hotel.username = "io"

        with mock.patch.object(queops_desktop, "Desktop") as desktop:
            result = queops_desktop.collect_queops_report(
                hotel,
                "test-password",
                "unused-output",
                reference_date=date(2026, 11, 1),
            )

        self.assertIn("Não há dias concluídos", result.error)
        self.assertEqual(result.reports, [])
        desktop.assert_not_called()


if __name__ == "__main__":
    unittest.main()
