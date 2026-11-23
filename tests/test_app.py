import logging
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import app
from app import SYSTEM_LABELS
from settings import HOTEL_SYSTEMS


class AppSystemLabelTests(unittest.TestCase):
    def test_every_configured_hotel_system_has_a_display_label(self):
        self.assertTrue(HOTEL_SYSTEMS.issubset(SYSTEM_LABELS))

    def test_logging_uses_temp_directory_when_app_data_is_not_writable(self):
        logger = logging.Logger("test_pms_report_automation")
        actual_handler = app.RotatingFileHandler

        with tempfile.TemporaryDirectory() as temporary_directory:
            local_app_data = Path(temporary_directory) / "local"
            fallback_directory = Path(temporary_directory) / "temp"

            def deny_primary_log_then_open_fallback(*args, **kwargs):
                primary_log_directory = (
                    local_app_data / "PMSReportAutomation" / "logs"
                )
                if Path(args[0]).parent == primary_log_directory:
                    raise PermissionError("access denied")
                return actual_handler(*args, **kwargs)

            with (
                patch("app.logging.getLogger", return_value=logger),
                patch.dict(os.environ, {"LOCALAPPDATA": str(local_app_data)}),
                patch(
                    "app.tempfile.gettempdir",
                    return_value=str(fallback_directory),
                ),
                patch(
                    "app.RotatingFileHandler",
                    side_effect=deny_primary_log_then_open_fallback,
                ),
            ):
                configured_logger, warning = app._configure_logging()

            try:
                self.assertIs(configured_logger, logger)
                self.assertIn("os logs serão gravados", warning)
                self.assertEqual(
                    Path(logger.handlers[0].baseFilename),
                    fallback_directory
                    / "PMSReportAutomation"
                    / "logs"
                    / "automation.log",
                )
            finally:
                for handler in logger.handlers:
                    handler.close()


if __name__ == "__main__":
    unittest.main()
