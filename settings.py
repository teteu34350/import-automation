import ctypes
import json
import os
import tempfile
import time
import uuid
from dataclasses import asdict, dataclass, field
from ctypes import wintypes
from pathlib import Path
from urllib.parse import urlparse


RESERVATION_FILTERS = {
    "cancelled": "Canceladas",
    "blocked": "Listar reservas bloqueio",
}

MOVEMENT_OPTIONS = {
    "maintenance": (
        "Considerar UHs em 'Manutenção' no cálculo do percentual de ocupação",
    ),
    "house_use": (
        "Considerar UHs em 'Uso da casa' no cálculo do percentual de ocupação",
    ),
    "meals_after_checkout": "Considerar refeições após o Check-out do dia",
}

PORTINARI_CENTER_NAME = "HOTEL PORTINARI CENTRO"
PORTINARI_ADDITIONAL_UNIT = "HOTEL PORTINARI PONTE DA AMIZADE (1860)"
DESBRAVADOR_WEB = "desbravador_web"
QUEOPS_DESKTOP = "queops_desktop"
AMERISCONNECT = "amerisconnect"
HOTEL_SYSTEMS = {DESBRAVADOR_WEB, QUEOPS_DESKTOP, AMERISCONNECT}
WEB_SYSTEMS = {DESBRAVADOR_WEB, AMERISCONNECT}


def default_config_path():
    local_config = Path(__file__).resolve().parent / "hotels.json"
    if local_config.exists():
        return local_config

    app_data = os.getenv("APPDATA")
    root = Path(app_data) if app_data else Path.home() / "AppData" / "Roaming"
    return root / "PMSReportAutomation" / "hotels.json"


def default_desktop_path():
    if os.name == "nt":
        shell32 = ctypes.WinDLL("shell32", use_last_error=True)
        get_folder_path = shell32.SHGetFolderPathW
        get_folder_path.argtypes = (
            wintypes.HWND,
            ctypes.c_int,
            wintypes.HANDLE,
            wintypes.DWORD,
            wintypes.LPWSTR,
        )
        get_folder_path.restype = wintypes.HRESULT
        buffer = ctypes.create_unicode_buffer(32768)
        result = get_folder_path(None, 0, None, 0, buffer)
        if result != 0:
            raise ctypes.WinError(result)

        return Path(buffer.value)

    return Path.home() / "Desktop"


def default_downloads_path():
    return Path.home() / "Downloads"


def _default_additional_unit(name, url=""):
    if (
        isinstance(name, str)
        and name.strip().casefold() == PORTINARI_CENTER_NAME.casefold()
    ):
        return PORTINARI_ADDITIONAL_UNIT
    if isinstance(url, str):
        parsed_url = urlparse(url)
        if (
            parsed_url.netloc.casefold() == "desbravadorweb.com.br"
            and parsed_url.path.rstrip("/") == "/acesso/4846"
        ):
            return PORTINARI_ADDITIONAL_UNIT
    return ""


def _default_unit_selector_name(name, url=""):
    if isinstance(url, str):
        parsed_url = urlparse(url)
        if (
            parsed_url.netloc.casefold() == "desbravadorweb.com.br"
            and parsed_url.path.rstrip("/") == "/acesso/4846"
        ):
            return PORTINARI_CENTER_NAME
    return name if isinstance(name, str) else ""


@dataclass
class HotelProfile:
    id: str
    name: str
    url: str = ""
    username: str = ""
    system: str = DESBRAVADOR_WEB
    active: bool = True
    additional_unit: str = ""
    unit_selector_name: str = ""
    disabled_reservation_filters: list[str] = field(default_factory=list)
    reservation_filter_overrides: dict[str, bool] = field(default_factory=dict)
    movement_options: dict[str, bool] = field(default_factory=dict)

    @property
    def credential_target(self):
        return f"PMSReportAutomation/{self.id}"


@dataclass
class AppSettings:
    hotels: list[HotelProfile] = field(default_factory=list)
    output_directory: str = field(
        default_factory=lambda: str(default_desktop_path()),
    )
    output_format: str = "xls"

    @classmethod
    def load(cls, path=None):
        config_path = Path(path or default_config_path())
        if not config_path.exists():
            return cls()

        read_error = None
        for attempt in range(5):
            try:
                data = json.loads(config_path.read_text(encoding="utf-8"))
                read_error = None
                break
            except (OSError, json.JSONDecodeError) as error:
                read_error = error
                if isinstance(error, PermissionError) and attempt < 4:
                    time.sleep(0.2)
                    continue
                break

        if read_error is not None:
            raise ValueError(
                f"Não foi possível ler as configurações em "
                f"{config_path}: {read_error}"
            ) from read_error

        try:
            hotels = []
            for hotel_data in data.get("hotels", []):
                profile_data = dict(hotel_data)
                profile_data.setdefault(
                    "additional_unit",
                    _default_additional_unit(
                        profile_data.get("name", ""),
                        profile_data.get("url", ""),
                    ),
                )
                profile_data.setdefault(
                    "unit_selector_name",
                    _default_unit_selector_name(
                        profile_data.get("name", ""),
                        profile_data.get("url", ""),
                    ),
                )
                hotels.append(HotelProfile(**profile_data))
            settings = cls(
                hotels=hotels,
                output_directory=data.get(
                    "output_directory",
                    str(default_desktop_path()),
                ),
                output_format=data.get("output_format", "xls"),
            )
        except (OSError, json.JSONDecodeError, TypeError, ValueError) as error:
            raise ValueError(
                f"Não foi possível ler as configurações em {config_path}."
            ) from error

        settings.validate()
        return settings

    def save(self, path=None):
        self.validate()
        config_path = Path(path or default_config_path())
        config_path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "hotels": [asdict(hotel) for hotel in self.hotels],
            "output_directory": self.output_directory,
            "output_format": self.output_format,
        }

        temporary_path = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=config_path.parent,
                delete=False,
                suffix=".tmp",
            ) as temporary_file:
                temporary_path = Path(temporary_file.name)
                json.dump(data, temporary_file, ensure_ascii=False, indent=2)
                temporary_file.write("\n")
            temporary_path.replace(config_path)
        finally:
            if temporary_path and temporary_path.exists():
                temporary_path.unlink()

    def validate(self):
        if self.output_format != "xls":
            raise ValueError(
                "O formato de saída suportado é Excel 97-2003 (.xls)."
            )

        ids = set()
        for hotel in self.hotels:
            if not hotel.id or hotel.id in ids:
                raise ValueError("Cada hotel precisa ter um identificador único.")
            ids.add(hotel.id)
            if not hotel.name.strip():
                raise ValueError("Informe um nome para cada hotel.")
            if hotel.system not in HOTEL_SYSTEMS:
                raise ValueError(
                    f"O sistema do hotel '{hotel.name}' não é reconhecido."
                )
            if hotel.system in WEB_SYSTEMS:
                parsed_url = urlparse(hotel.url)
                if parsed_url.scheme != "https" or not parsed_url.netloc:
                    raise ValueError(
                        f"A URL do hotel '{hotel.name}' precisa começar com https://."
                    )
            if not hotel.username.strip():
                raise ValueError(
                    f"Informe o usuário do hotel '{hotel.name}'."
                )
            if not isinstance(hotel.active, bool):
                raise ValueError(
                    f"O status do hotel '{hotel.name}' precisa ser ativo ou inativo."
                )
            if not isinstance(hotel.additional_unit, str):
                raise ValueError(
                    f"A unidade adicional de '{hotel.name}' precisa ser um texto."
                )
            if not isinstance(hotel.unit_selector_name, str):
                raise ValueError(
                    f"O nome no seletor de '{hotel.name}' precisa ser um texto."
                )
            if hotel.additional_unit.strip().casefold() == hotel.name.strip().casefold():
                raise ValueError(
                    f"A unidade adicional de '{hotel.name}' precisa ser diferente "
                    "do hotel principal."
                )
            unknown_filters = (
                set(hotel.disabled_reservation_filters)
                - set(RESERVATION_FILTERS)
            )
            unknown_movement = set(hotel.movement_options) - set(MOVEMENT_OPTIONS)
            unknown_overrides = (
                set(hotel.reservation_filter_overrides) - set(RESERVATION_FILTERS)
            )
            invalid_filter_values = any(
                not isinstance(value, bool)
                for value in hotel.reservation_filter_overrides.values()
            )
            invalid_movement_values = any(
                not isinstance(value, bool)
                for value in hotel.movement_options.values()
            )
            if (
                unknown_filters
                or unknown_movement
                or unknown_overrides
                or invalid_filter_values
                or invalid_movement_values
            ):
                raise ValueError(
                    f"Há filtros desconhecidos configurados para "
                    f"'{hotel.name}'."
                )


def new_hotel_profile(
    name="",
    url="",
    username="",
    system=DESBRAVADOR_WEB,
):
    return HotelProfile(
        id=str(uuid.uuid4()),
        name=name,
        url=url,
        username=username,
        system=system,
        additional_unit=_default_additional_unit(name, url),
        unit_selector_name=_default_unit_selector_name(name, url),
        disabled_reservation_filters=[],
        reservation_filter_overrides={},
        movement_options={},
    )
