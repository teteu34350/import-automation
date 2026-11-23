import unittest

from batch import run_import_batch, select_active_hotels
from collectors.models import CollectionResult, ReportResult
from settings import AMERISCONNECT, QUEOPS_DESKTOP, new_hotel_profile


class ImportBatchTests(unittest.TestCase):
    def setUp(self):
        self.hotels = [
            new_hotel_profile(
                "Hotel Norte",
                "https://example.com/acesso/1/",
                "north@example.com",
            ),
            new_hotel_profile(
                "Hotel Sul",
                "https://example.com/acesso/2/",
                "south@example.com",
            ),
        ]

    def test_select_active_hotels_returns_only_requested_active_hotels(self):
        self.hotels[1].active = False

        selected = select_active_hotels(
            self.hotels,
            {self.hotels[0].id, self.hotels[1].id},
        )

        self.assertEqual(selected, [self.hotels[0]])

    def test_select_active_hotels_defaults_to_all_active_hotels(self):
        self.hotels[1].active = False

        selected = select_active_hotels(self.hotels)

        self.assertEqual(selected, [self.hotels[0]])

    def test_batch_continues_after_an_individual_hotel_fails(self):
        calls = []

        def credential_reader(target):
            if target == self.hotels[0].credential_target:
                raise RuntimeError("Credential access failed.")
            return "secret"

        def collector(hotel, password, output, progress=None):
            self.assertEqual(password, "secret")
            self.assertEqual(output, ".")
            self.assertIsNone(progress)
            calls.append(hotel.id)
            return CollectionResult(
                hotel_name=hotel.name,
                period_start="01/10/2026",
                period_end="30/09/2027",
                reports=[
                    ReportResult("Reservas", "success"),
                    ReportResult("Movimentação com diária", "success"),
                ],
                logout_confirmed=True,
            )

        results = run_import_batch(
            self.hotels,
            ".",
            credential_reader=credential_reader,
            collection_runner=collector,
        )

        self.assertEqual([result.status for result in results], ["failed", "success"])
        self.assertEqual(calls, [self.hotels[1].id])

    def test_progress_events_are_emitted_for_each_hotel(self):
        events = []

        def credential_reader(target):
            self.assertEqual(target, self.hotels[0].credential_target)
            return "secret"

        def collector(hotel, password, output, progress=None):
            self.assertEqual(password, "secret")
            self.assertEqual(output, ".")
            if progress:
                progress("Coletando reservas.")
            return CollectionResult(
                hotel_name=hotel.name,
                period_start="01/10/2026",
                period_end="30/09/2027",
                reports=[ReportResult("Reservas", "success")],
            )

        run_import_batch(
            self.hotels[:1],
            ".",
            progress_callback=lambda event, hotel, message: events.append(
                (event, hotel.id, message)
            ),
            credential_reader=credential_reader,
            collection_runner=collector,
        )

        self.assertEqual(
            [event[0] for event in events],
            ["hotel_started", "progress", "hotel_finished"],
        )

    def test_credentials_are_redacted_from_failures(self):
        def credential_reader(target):
            self.assertEqual(target, self.hotels[0].credential_target)
            return "secret-value"

        def collector(hotel, password, output, progress=None):
            self.assertEqual(output, ".")
            self.assertIsNone(progress)
            raise RuntimeError(
                f"Failed for {password} {hotel.username}"
            )

        results = run_import_batch(
            self.hotels[:1],
            ".",
            credential_reader=credential_reader,
            collection_runner=collector,
        )

        self.assertEqual(results[0].status, "failed")
        self.assertNotIn("secret-value", results[0].error)
        self.assertNotIn("north@example.com", results[0].error)

    def test_inactive_hotels_are_not_imported(self):
        self.hotels[0].active = False
        called_hotels = []

        def collector(hotel, password, output, progress=None):
            self.assertEqual(password, "secret")
            self.assertEqual(output, ".")
            self.assertIsNone(progress)
            called_hotels.append(hotel.id)
            return CollectionResult(
                hotel_name=hotel.name,
                period_start="01/10/2026",
                period_end="30/09/2027",
                reports=[ReportResult("Reservas", "success")],
            )

        def credential_reader(target):
            self.assertEqual(target, self.hotels[1].credential_target)
            return "secret"

        results = run_import_batch(
            self.hotels,
            ".",
            credential_reader=credential_reader,
            collection_runner=collector,
        )

        self.assertEqual(called_hotels, [self.hotels[1].id])
        self.assertEqual(len(results), 1)

    def test_amerisconnect_profile_reports_unavailable_collector(self):
        hotel = new_hotel_profile(
            name="Iracema Travel",
            url="https://amerisconnect.example.com/",
            username="user@example.com",
            system=AMERISCONNECT,
        )

        results = run_import_batch([hotel], ".")

        self.assertEqual(results[0].status, "failed")
        self.assertIn("ainda não está disponível", results[0].error)

    def test_queops_hotel_uses_desktop_runner_without_credentials(self):
        hotel = new_hotel_profile(
            name="Pontal do Mundai",
            username="io",
            system=QUEOPS_DESKTOP,
        )
        calls = []

        def queops_runner(profile, password, output, progress=None):
            self.assertEqual(password, "secret")
            calls.append((profile.id, output))
            return CollectionResult(
                hotel_name=profile.name,
                period_start="28/10/2026",
                period_end="28/10/2027",
                reports=[
                    ReportResult("Check-in's esperados", "success"),
                    ReportResult("Resumo de Ocupação (C-PAST)", "success"),
                    ReportResult("Previsão de Ocupação", "success"),
                    ReportResult("Diário de situação (RDS)", "success"),
                ],
                expected_report_count=4,
                logout_required=False,
            )

        def credential_reader(target):
            self.assertEqual(target, hotel.credential_target)
            return "secret"

        results = run_import_batch(
            [hotel],
            ".",
            credential_reader=credential_reader,
            queops_runner=queops_runner,
        )

        self.assertEqual(calls, [(hotel.id, ".")])
        self.assertEqual(results[0].status, "success")

    def test_queops_report_error_cannot_be_marked_as_completed(self):
        hotel = new_hotel_profile(
            name="Pontal do Mundai",
            username="io",
            system=QUEOPS_DESKTOP,
        )

        def queops_runner(profile, password, output, progress=None):
            return CollectionResult(
                hotel_name=profile.name,
                period_start="17/11/2026",
                period_end="17/11/2027",
                reports=[
                    ReportResult("Check-in's esperados", "success"),
                ],
                error="Resumo de Ocupação (C-PAST): janela não abriu",
                logout_required=False,
            )

        results = run_import_batch(
            [hotel],
            ".",
            credential_reader=lambda target: "secret",
            queops_runner=queops_runner,
        )

        self.assertEqual(results[0].status, "partial")


if __name__ == "__main__":
    unittest.main()
