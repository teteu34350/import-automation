import json
import tempfile
import unittest
from pathlib import Path

from settings import (
    AppSettings,
    DESBRAVADOR_WEB,
    QUEOPS_DESKTOP,
    new_hotel_profile,
)


class AppSettingsTests(unittest.TestCase):
    def test_multiple_hotels_persist_without_passwords(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "hotels.json"
            first = new_hotel_profile(
                "Hotel Norte",
                "https://desbravadorweb.com.br/acesso/1/",
                "user1@example.com",
            )
            second = new_hotel_profile(
                "Hotel Sul",
                "https://desbravadorweb.com.br/acesso/2/",
                "user2@example.com",
            )
            first.disabled_reservation_filters = ["cancelled"]
            first.reservation_filter_overrides = {"cancelled": False}
            first.additional_unit = "Hotel Norte Anexo"
            second.movement_options["house_use"] = True
            settings = AppSettings(hotels=[first, second])

            settings.save(path)
            loaded = AppSettings.load(path)

            self.assertEqual(len(loaded.hotels), 2)
            self.assertEqual(loaded.hotels[0].name, "Hotel Norte")
            self.assertTrue(loaded.hotels[0].active)
            self.assertEqual(
                loaded.hotels[0].additional_unit,
                "Hotel Norte Anexo",
            )
            self.assertEqual(
                loaded.hotels[0].disabled_reservation_filters,
                ["cancelled"],
            )
            self.assertEqual(
                loaded.hotels[0].reservation_filter_overrides,
                {"cancelled": False},
            )
            self.assertTrue(loaded.hotels[1].movement_options["house_use"])
            stored_data = json.loads(path.read_text(encoding="utf-8"))
            self.assertNotIn("password", stored_data["hotels"][0])

    def test_inactive_hotel_state_persists(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "hotels.json"
            hotel = new_hotel_profile(
                "Hotel Pausado",
                "https://example.com/acesso/1/",
                "user@example.com",
            )
            hotel.active = False

            AppSettings(hotels=[hotel]).save(path)

            self.assertFalse(AppSettings.load(path).hotels[0].active)

    def test_queops_profile_requires_user_but_not_web_url(self):
        hotel = new_hotel_profile(
            name="Pontal do Mundai",
            username="io",
            system=QUEOPS_DESKTOP,
        )

        AppSettings(hotels=[hotel]).validate()
        self.assertEqual(hotel.system, QUEOPS_DESKTOP)

    def test_queops_profile_without_user_is_rejected(self):
        hotel = new_hotel_profile(
            name="Pontal do Mundai",
            system=QUEOPS_DESKTOP,
        )

        with self.assertRaisesRegex(ValueError, "usuário"):
            AppSettings(hotels=[hotel]).validate()

    def test_existing_profiles_default_to_desbravador_web(self):
        hotel = new_hotel_profile(
            "Hotel",
            "https://example.com/acesso/1/",
            "user@example.com",
        )

        self.assertEqual(hotel.system, DESBRAVADOR_WEB)

    def test_unknown_hotel_system_is_rejected(self):
        hotel = new_hotel_profile(
            name="Hotel",
            system="unknown",
        )

        with self.assertRaisesRegex(ValueError, "sistema"):
            AppSettings(hotels=[hotel]).validate()

    def test_non_https_hotel_url_is_rejected(self):
        settings = AppSettings(
            hotels=[
                new_hotel_profile(
                    "Hotel",
                    "http://example.com/acesso/1/",
                    "user@example.com",
                )
            ]
        )

        with self.assertRaises(ValueError):
            settings.validate()

    def test_additional_unit_must_differ_from_primary_hotel(self):
        hotel = new_hotel_profile(
            "Hotel",
            "https://example.com/acesso/1/",
            "user@example.com",
        )
        hotel.additional_unit = " hotel "

        with self.assertRaisesRegex(ValueError, "diferente"):
            AppSettings(hotels=[hotel]).validate()

    def test_portinari_center_defaults_to_its_linked_unit(self):
        hotel = new_hotel_profile(
            "HOTEL PORTINARI CENTRO",
            "https://desbravadorweb.com.br/acesso/4846",
            "user@example.com",
        )
        self.assertEqual(
            hotel.additional_unit,
            "HOTEL PORTINARI PONTE DA AMIZADE (1860)",
        )
        self.assertEqual(
            hotel.unit_selector_name,
            "HOTEL PORTINARI CENTRO",
        )

    def test_portinari_access_url_defaults_to_its_linked_unit(self):
        hotel = new_hotel_profile(
            "Centro",
            "https://desbravadorweb.com.br/acesso/4846",
            "user@example.com",
        )

        self.assertEqual(
            hotel.additional_unit,
            "HOTEL PORTINARI PONTE DA AMIZADE (1860)",
        )
        self.assertEqual(
            hotel.unit_selector_name,
            "HOTEL PORTINARI CENTRO",
        )

    def test_legacy_portinari_configuration_migrates_linked_unit(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "hotels.json"
            path.write_text(
                json.dumps(
                    {
                        "hotels": [
                            {
                                "id": "portinari",
                                "name": "Centro",
                                "url": (
                                    "https://desbravadorweb.com.br/acesso/4846"
                                ),
                                "username": "user@example.com",
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )

            hotel = AppSettings.load(path).hotels[0]

            self.assertEqual(
                hotel.additional_unit,
                "HOTEL PORTINARI PONTE DA AMIZADE (1860)",
            )
            self.assertEqual(
                hotel.unit_selector_name,
                "HOTEL PORTINARI CENTRO",
            )


if __name__ == "__main__":
    unittest.main()
