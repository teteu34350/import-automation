"""Script para executar a importação dos relatórios do Pontal do Mundaí (Queops)."""

import sys
from pathlib import Path

from batch import run_import_batch
from settings import AppSettings, QUEOPS_DESKTOP


def main():
    settings = AppSettings.load()
    hotel = next(
        (
            h
            for h in settings.hotels
            if h.active
            and h.system == QUEOPS_DESKTOP
            and "pontal" in h.name.strip().casefold()
        ),
        None,
    )
    if not hotel:
        print("Erro: Hotel Pontal do Mundaí não encontrado ou inativo em hotels.json.")
        sys.exit(1)

    print(f"Iniciando importação para: {hotel.name} (Usuário: {hotel.username})")

    def progress_callback(event, h, message):
        print(f"[{event}] {message}")

    output_dir = settings.output_directory or str(Path.cwd())
    results = run_import_batch(
        [hotel],
        output_dir,
        progress_callback=progress_callback,
    )
    result = results[0]
    print(f"\nStatus final da importação: {result.status}")
    if result.error:
        print(f"Erro detalhado: {result.error}")

    if result.collection and result.collection.reports:
        print("\nResumo dos relatórios:")
        for rep in result.collection.reports:
            status_symbol = "✓" if rep.status == "success" else "✗"
            print(f" [{status_symbol}] {rep.report}: {rep.status} -> {rep.path or rep.message}")


if __name__ == "__main__":
    main()
