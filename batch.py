from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from collectors.desbravador_web import collect_reports
from collectors.models import CollectionResult
from credentials import read_password
from settings import (
    AMERISCONNECT,
    DESBRAVADOR_WEB,
    QUEOPS_DESKTOP,
    HotelProfile,
)


@dataclass
class HotelImportResult:
    hotel: HotelProfile
    status: str
    collection: CollectionResult | None = None
    error: str = ""


def select_active_hotels(
    hotels: list[HotelProfile],
    selected_ids: set[str] | None = None,
) -> list[HotelProfile]:
    return [
        hotel
        for hotel in hotels
        if hotel.active and (selected_ids is None or hotel.id in selected_ids)
    ]


def _result_status(
    collection: CollectionResult,
    logout_required: bool = True,
) -> str:
    if not collection.error and collection.all_reports_succeeded and (
        not logout_required or collection.logout_confirmed
    ):
        return "success"
    if collection.succeeded:
        return "partial"
    return "failed"


def run_import_batch(
    hotels: list[HotelProfile],
    output_directory: str | Path,
    progress_callback: Callable[[str, HotelProfile, str], None] | None = None,
    collection_runner=None,
    credential_reader=read_password,
    queops_runner=None,
) -> list[HotelImportResult]:
    results = []
    for hotel in hotels:
        if not hotel.active:
            continue
        if progress_callback:
            progress_callback("hotel_started", hotel, "Iniciando importação.")
        password = None
        try:
            report_progress = None
            if progress_callback:
                report_progress = (
                    lambda message, current_hotel=hotel: progress_callback(
                        "progress",
                        current_hotel,
                        message,
                    )
                )
            if hotel.system == DESBRAVADOR_WEB:
                password = credential_reader(hotel.credential_target)
                if not password:
                    raise RuntimeError(
                        "Não há senha salva no Gerenciador de Credenciais "
                        "do Windows."
                    )
                runner = collection_runner or collect_reports
                collection = runner(
                    hotel,
                    password,
                    output_directory,
                    progress=report_progress,
                )
                logout_required = True
            elif hotel.system == QUEOPS_DESKTOP:
                password = credential_reader(hotel.credential_target)
                if not password:
                    raise RuntimeError(
                        "Não há senha salva no Gerenciador de Credenciais "
                        "do Windows."
                    )
                if queops_runner is None:
                    from collectors.queops_desktop import collect_queops_report

                    queops_runner = collect_queops_report
                collection = queops_runner(
                    hotel,
                    password,
                    output_directory,
                    progress=report_progress,
                )
                logout_required = collection.logout_required
            elif hotel.system == AMERISCONNECT:
                raise RuntimeError(
                    "A importação do AmerisConnect ainda não está disponível."
                )
            else:
                raise ValueError(
                    f"O sistema do hotel '{hotel.name}' não é reconhecido."
                )
            error = collection.error
            if error:
                error = error.replace(hotel.username, "[redacted]")
                if password:
                    error = error.replace(password, "[redacted]")
            result = HotelImportResult(
                hotel=hotel,
                status=_result_status(collection, logout_required),
                collection=collection,
                error=error,
            )
        except Exception as error:
            message = str(error).replace(hotel.username, "[redacted]")
            if password:
                message = message.replace(password, "[redacted]")
            result = HotelImportResult(
                hotel=hotel,
                status="failed",
                error=message,
            )
        results.append(result)
        if progress_callback:
            progress_callback(
                "hotel_finished",
                hotel,
                result.status,
            )
    return results
