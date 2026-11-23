"""Temporary one-shot setup: register Iracema Travel (AmerisConnect).

Registers the hotel in %APPDATA%\PMSReportAutomation\hotels.json and stores
the password in the Windows Credential Manager (target PMSReportAutomation/{id}),
matching the project convention. This file is deleted after use.
"""
from credentials import save_password
from settings import AMERISCONNECT, AppSettings, new_hotel_profile

NAME = "Iracema Travel"
URL = "https://amerisconnect.autosky.cloud/"
USERNAME = "miguel@sistemaio.com.br"
PASSWORD = "IOameris_2026_nov!"


def main():
    settings = AppSettings.load()
    existing = next(
        (
            hotel
            for hotel in settings.hotels
            if hotel.name.strip().casefold() == NAME.casefold()
        ),
        None,
    )
    if existing is None:
        hotel = new_hotel_profile(NAME, URL, USERNAME, system=AMERISCONNECT)
        settings.hotels.append(hotel)
    else:
        hotel = existing
        hotel.name = NAME
        hotel.url = URL
        hotel.username = USERNAME
        hotel.system = AMERISCONNECT
        hotel.active = True
    settings.save()
    save_password(hotel.credential_target, hotel.username, PASSWORD)
    print(f"HOTEL_ID={hotel.id}")
    print(f"CREDENTIAL_TARGET={hotel.credential_target}")
    print("DONE")


if __name__ == "__main__":
    main()
