import base64
import hashlib
import os
import re
import sys
import tempfile
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

from playwright.sync_api import BrowserContext, Page
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright

from collectors.models import CollectionResult, ReportResult
from periods import ReportPeriod, calculate_report_period
from report_files import convert_csv_to_xls
from settings import HotelProfile, MOVEMENT_OPTIONS, RESERVATION_FILTERS


RESERVATION_REPORT = {
    "kind": "C",
    "label": "Reservas",
    "route": "relatorioListagemReservas",
    "path": "/#/relatorios/relatorioListagemReservas/",
}
MOVEMENT_REPORT = {
    "kind": "R",
    "label": "Movimentação com diária",
    "route": "relatorioPrevisaoMovimentacaoComDiaria",
    "path": "/#/relatorios/relatorioPrevisaoMovimentacaoComDiaria/",
}


def _safe_filename(value):
    cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", value).strip(" .")
    if not cleaned:
        raise ValueError("O nome do hotel não gera um nome de arquivo válido.")
    return cleaned


def _browser_profile_directory(profile: HotelProfile) -> Path:
    app_data = os.getenv("LOCALAPPDATA")
    root = (
        Path(app_data)
        if app_data
        else Path.home() / "AppData" / "Local"
    )
    profile_key = hashlib.sha256(profile.id.encode("utf-8")).hexdigest()
    return root / "PMSReportAutomation" / "browser-profiles" / profile_key


def _ensure_browser_profile_directory(profile_directory: Path) -> Path:
    try:
        profile_directory.mkdir(parents=True, exist_ok=True)
    except PermissionError as primary_error:
        fallback_directory = (
            Path(tempfile.gettempdir())
            / "PMSReportAutomation"
            / "browser-profiles"
            / profile_directory.name
        )
        try:
            fallback_directory.mkdir(parents=True, exist_ok=True)
        except OSError as fallback_error:
            raise OSError(
                "Não foi possível criar o perfil do Chrome em "
                f"'{profile_directory}' ({primary_error}) nem em "
                f"'{fallback_directory}' ({fallback_error})."
            ) from fallback_error
        return fallback_directory
    return profile_directory


@contextmanager
def _playwright_with_temp_directory(temp_directory: Path):
    temp_directory.mkdir(parents=True, exist_ok=True)
    previous_values = {
        name: os.environ.get(name)
        for name in ("TEMP", "TMP")
    }
    os.environ["TEMP"] = str(temp_directory)
    os.environ["TMP"] = str(temp_directory)
    try:
        playwright_context = sync_playwright()
        playwright = playwright_context.__enter__()
    finally:
        for name, value in previous_values.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value

    try:
        yield playwright
    except BaseException:
        if not playwright_context.__exit__(*sys.exc_info()):
            raise
    else:
        playwright_context.__exit__(None, None, None)


def _notify(progress, message):
    if progress:
        progress(message)


def _redact(message, profile, password):
    for secret in (password, profile.username):
        if secret:
            message = message.replace(secret, "[redacted]")
    return message


def _session_in_use(body_text):
    return bool(
        re.search(
            r"sess[aã]o em uso|j[aá] est[aá] conectado|desconect[aá]-lo",
            re.sub(r"\s+", " ", body_text),
            re.IGNORECASE,
        )
    )


def _login_failure_message(body_text):
    normalized_text = re.sub(r"\s+", " ", body_text)
    if _session_in_use(normalized_text):
        return (
            "O sistema informou que este usuário já está conectado em outra "
            "sessão. A automação parou sem tentar desconectar essa sessão."
        )

    error_lines = [
        line.strip()
        for line in body_text.splitlines()
        if re.search(
            r"erro|inválid|incorret|não cadastrad|não autorizado|falha|bloquead",
            line,
            re.IGNORECASE,
        )
    ]
    detail = " ".join(error_lines)[:300]
    message = (
        "Não foi possível confirmar o login. Verifique a URL, o usuário "
        "e a senha cadastrados."
    )
    if detail:
        message = f"{message} Mensagem exibida pelo sistema: {detail}"
    return message


def _login(page: Page, profile: HotelProfile, password: str):
    page.goto(profile.url, wait_until="domcontentloaded", timeout=60000)
    username_field = page.locator(
        'input[type="email"], input[name="email"]'
    )
    password_field = page.locator('input[type="password"]')
    if username_field.count() != 1 or password_field.count() != 1:
        raise RuntimeError(
            "Não foi possível localizar os campos de usuário e senha "
            "na tela de acesso."
        )
    username_field.wait_for(state="visible", timeout=20000)
    username_field.fill(profile.username)
    password_field.fill(password)
    page.get_by_role(
        "button",
        name=re.compile(r"^Entrar$", re.IGNORECASE),
    ).click()
    try:
        username_field.wait_for(state="hidden", timeout=30000)
    except PlaywrightTimeoutError as error:
        body_text = page.locator("body").inner_text()
        raise RuntimeError(_login_failure_message(body_text)) from error


def _dismiss_optional_notices(page: Page):
    notice = page.get_by_text(
        re.compile(r"responder mais tarde", re.IGNORECASE),
    ).first
    try:
        notice.wait_for(state="visible", timeout=2500)
    except PlaywrightTimeoutError:
        pass
    else:
        notice.click()
        notice.wait_for(state="hidden", timeout=10000)

    tax_dialog = page.get_by_role("dialog").filter(
        has_text=re.compile(
            r"informar a alíquota do Simples Nacional deste mês",
            re.IGNORECASE,
        ),
    )
    try:
        tax_dialog.wait_for(state="visible", timeout=2500)
    except PlaywrightTimeoutError:
        return
    tax_dialog.get_by_role(
        "button",
        name=re.compile(r"^Ok", re.IGNORECASE),
    ).click()
    tax_dialog.wait_for(state="hidden", timeout=10000)


def _select_hotel_unit(page: Page, current_unit: str, target_unit: str):
    if current_unit.strip().casefold() == target_unit.strip().casefold():
        return

    selector = page.locator("button.dropdown-toggle.abrevia-texto")
    selector.wait_for(state="visible", timeout=20000)
    if selector.count() != 1:
        raise RuntimeError(
            "Não foi possível localizar de forma única o seletor de hotéis."
        )
    selected_unit = re.sub(r"\s+", " ", selector.inner_text()).strip()
    if selected_unit.casefold() != current_unit.strip().casefold():
        raise RuntimeError(
            f"O seletor mostra '{selected_unit}', mas era esperada a unidade "
            f"'{current_unit}'."
        )
    selector.click()

    target_option = page.locator("#estabelecimentosUl").get_by_text(
        target_unit,
        exact=True,
    )
    target_option.wait_for(state="visible", timeout=20000)
    if target_option.count() != 1:
        raise RuntimeError(
            f"A unidade '{target_unit}' não foi encontrada de forma única "
            "no seletor de hotéis."
        )
    target_option.click()
    display_target = re.sub(r"\s*\([^()]*\)\s*$", "", target_unit).strip()
    page.wait_for_function(
        """({selector, target, displayTarget}) => {
            const element = document.querySelector(selector);
            if (!element) return false;
            const displayed = element.innerText.replace(/\\s+/g, " ").trim();
            return displayed === target || displayed === displayTarget;
        }""",
        arg={
            "selector": "button.dropdown-toggle.abrevia-texto",
            "target": target_unit,
            "displayTarget": display_target,
        },
        timeout=20000,
    )
    page.wait_for_load_state("networkidle", timeout=30000)


def _set_checkbox(page: Page, label: str, enabled: bool):
    checkbox = page.get_by_role(
        "checkbox",
        name=re.compile(rf"{re.escape(label)}$"),
    )
    if checkbox.count() != 1:
        raise RuntimeError(
            f"Esperado encontrar um único filtro '{label}', "
            f"mas foram encontrados {checkbox.count()}."
        )
    if checkbox.is_checked() != enabled:
        checkbox.evaluate("(element) => element.click()")
    if checkbox.is_checked() != enabled:
        raise RuntimeError(f"Não foi possível aplicar o filtro '{label}'.")


def _set_date(page: Page, label: str, value: str):
    field = page.get_by_label(re.compile(label, re.IGNORECASE))
    field.wait_for(state="visible", timeout=20000)
    field_type = field.get_attribute("type")
    expected = datetime.strptime(value, "%d/%m/%Y").strftime(
        "%Y-%m-%d" if field_type == "date" else "%d/%m/%Y"
    )
    if field_type == "date":
        field.fill(expected)
    else:
        try:
            field.click()
        except PlaywrightTimeoutError as error:
            dialog = page.locator(".bootbox.modal.in").last
            if dialog.is_visible():
                dialog_text = re.sub(
                    r"\s+",
                    " ",
                    dialog.inner_text(),
                ).strip()
                if dialog_text:
                    raise RuntimeError(
                        f"Não foi possível interagir com a data '{label}': "
                        "o sistema exibiu uma janela que bloqueia o formulário: "
                        f"{dialog_text[:300]}"
                    ) from error
            raise
        field.press("Control+A")
        field.press("Backspace")
        field.type(value, delay=35)
    field.press("Tab")
    if field.input_value() != expected and field_type != "date":
        field.fill(value)
        field.press("Tab")
    if field.input_value() != expected:
        raise RuntimeError(
            f"O sistema não aceitou a data configurada no campo '{label}' "
            f"(tipo={field_type!r}, valor atual={field.input_value()!r}, "
            f"esperado={expected!r}, placeholder="
            f"{field.get_attribute('placeholder')!r})."
        )


def _prepare_report(
    page: Page,
    report: dict[str, str],
    profile: HotelProfile,
    period: ReportPeriod,
) -> str:
    parsed = urlparse(profile.url)
    base_url = f"{parsed.scheme}://{parsed.netloc}"
    page.goto(
        f"{base_url}{report['path']}",
        wait_until="domcontentloaded",
        timeout=60000,
    )

    if report["kind"] == "C":
        _set_date(page, "Data Início", period.start_text)
        _set_date(page, "Data Fim", period.end_text)
        for key, label in RESERVATION_FILTERS.items():
            state = profile.reservation_filter_overrides.get(key)
            if state is None and key in profile.disabled_reservation_filters:
                state = False
            if state is not None:
                _set_checkbox(page, label, state)
        return base_url

    _set_date(page, "Data inicial", period.start_text)
    _set_date(page, "Data final", period.end_text)
    for key, label in MOVEMENT_OPTIONS.items():
        if key in profile.movement_options:
            _set_checkbox(page, label, profile.movement_options[key])
    return base_url


def _fetch_csv(page: Page, base_url: str, route: str) -> bytes:
    response = page.evaluate(
        """async ({baseUrl, route}) => {
            const form = document.querySelector("form");
            if (!form) {
                throw new Error("O formulário do relatório não foi encontrado.");
            }
            const params = new URLSearchParams(
                Array.from(new FormData(form).entries())
            );
            const response = await fetch(
                `${baseUrl}/relatorios/${route}/download/csv?${params}&rel=true`,
                {credentials: "include"}
            );
            const bytes = new Uint8Array(await response.arrayBuffer());
            let binary = "";
            for (let offset = 0; offset < bytes.length; offset += 32768) {
                binary += String.fromCharCode(
                    ...bytes.subarray(offset, offset + 32768)
                );
            }
            return {
                status: response.status,
                contentType: response.headers.get("content-type") || "",
                body: btoa(binary)
            };
        }""",
        {"baseUrl": base_url, "route": route},
    )
    if response["status"] < 200 or response["status"] >= 300:
        raise RuntimeError(
            f"A exportação CSV retornou HTTP {response['status']}."
        )
    if "csv" not in response["contentType"].lower():
        raise RuntimeError(
            "O sistema não retornou um arquivo CSV para o relatório."
        )
    content = base64.b64decode(response["body"], validate=True)
    if not content.strip():
        raise RuntimeError("O sistema retornou um arquivo CSV vazio.")
    return content


def _logout(page: Page):
    user_menu = page.get_by_role(
        "link",
        name=re.compile(r"^[A-Z]$", re.IGNORECASE),
    )
    if user_menu.count() != 1:
        user_menu = page.get_by_role(
            "button",
            name=re.compile(r"^[A-Z]$", re.IGNORECASE),
        )
    if user_menu.count() != 1:
        raise RuntimeError(
            "Não foi possível localizar o menu do usuário para fazer logout."
        )
    user_menu.click()
    logout_link = page.get_by_role(
        "link",
        name=re.compile(r"\bSair\b", re.IGNORECASE),
    )
    logout_button = page.get_by_role(
        "button",
        name=re.compile(r"\bSair\b", re.IGNORECASE),
    )
    logout_text = page.get_by_text(
        re.compile(r"^Sair$", re.IGNORECASE),
    )
    if logout_link.count() == 1:
        logout_link.click()
    elif logout_button.count() == 1:
        logout_button.click()
    elif logout_text.count() == 1:
        logout_text.click()
    else:
        raise RuntimeError(
            "O menu do usuário foi aberto, mas a opção Sair não foi encontrada."
        )
    page.locator('input[type="email"]').wait_for(
        state="visible",
        timeout=30000,
    )


def collect_reports(
    profile: HotelProfile,
    password: str,
    output_directory: str | Path,
    progress=None,
    report_kinds: tuple[str, ...] = ("C", "R"),
) -> CollectionResult:
    period = calculate_report_period()
    result = CollectionResult(
        hotel_name=profile.name,
        period_start=period.start_text,
        period_end=period.end_text,
    )
    output_dir = Path(output_directory)
    run_date = datetime.now().strftime("%d-%m-%Y")
    authenticated = False

    with tempfile.TemporaryDirectory(prefix="pms-report-") as temp_dir:
        preferred_profile_directory = _browser_profile_directory(profile)
        try:
            profile_directory = _ensure_browser_profile_directory(
                preferred_profile_directory,
            )
            playwright_temp_directory = (
                profile_directory.parent / "playwright-temp"
            )
            playwright_temp_directory.mkdir(parents=True, exist_ok=True)
        except Exception as error:
            result.error = _redact(str(error), profile, password)
            return result

        if profile_directory != preferred_profile_directory:
            _notify(
                progress,
                "Sem permissão para gravar o perfil do Chrome no local "
                f"padrão; usando '{profile_directory}'.",
            )

        with _playwright_with_temp_directory(
            playwright_temp_directory,
        ) as playwright:
            context: BrowserContext | None = None
            page: Page | None = None
            try:
                context = playwright.chromium.launch_persistent_context(
                    str(profile_directory),
                    channel="chrome",
                    headless=False,
                    args=["--no-first-run", "--no-default-browser-check"],
                    accept_downloads=False,
                )
                page = context.pages[0] if context.pages else context.new_page()
                _notify(progress, f"Acessando o hotel {profile.name}...")
                _login(page, profile, password)
                authenticated = True
                _dismiss_optional_notices(page)

                report_by_kind = {
                    "C": RESERVATION_REPORT,
                    "R": MOVEMENT_REPORT,
                }
                unknown_reports = set(report_kinds) - set(report_by_kind)
                if unknown_reports:
                    raise ValueError(
                        f"Tipos de relatório desconhecidos: "
                        f"{', '.join(sorted(unknown_reports))}."
                    )
                reports = tuple(
                    report_by_kind[kind] for kind in report_kinds
                )
                unit_names = [profile.name]
                if profile.additional_unit.strip():
                    unit_names.append(profile.additional_unit.strip())

                current_unit = (
                    profile.unit_selector_name.strip()
                    or profile.name
                )
                for unit_index, unit_name in enumerate(unit_names):
                    if unit_index:
                        _notify(
                            progress,
                            f"Trocando unidade de {current_unit} para "
                            f"{unit_name}...",
                        )
                        try:
                            parsed_url = urlparse(profile.url)
                            base_url = (
                                f"{parsed_url.scheme}://{parsed_url.netloc}"
                            )
                            page.goto(
                                f"{base_url}/#/",
                                wait_until="domcontentloaded",
                                timeout=60000,
                            )
                            _select_hotel_unit(page, current_unit, unit_name)
                        except Exception as error:
                            message = _redact(
                                str(error),
                                profile,
                                password,
                            )
                            result.error = (
                                f"Não foi possível trocar para a unidade "
                                f"'{unit_name}': {message}"
                            )
                            for report in reports:
                                result.reports.append(
                                    ReportResult(
                                        report=report["label"],
                                        status="failed",
                                        message=result.error,
                                        unit_name=unit_name,
                                    )
                                )
                            break
                        current_unit = unit_name

                    filename_unit_name = (
                        "AMIZADE"
                        if "ponte da amizade" in unit_name.casefold()
                        else unit_name
                    )
                    file_prefix = _safe_filename(filename_unit_name)
                    for report in reports:
                        csv_path = (
                            Path(temp_dir)
                            / f"{unit_index}-{report['kind']}.csv"
                        )
                        destination = (
                            output_dir
                            / f"{report['kind']}-{file_prefix} {run_date}.xls"
                        )
                        try:
                            _notify(
                                progress,
                                f"Coletando e convertendo o relatório "
                                f"{report['label']} na unidade {unit_name}...",
                            )
                            base_url = _prepare_report(
                                page,
                                report,
                                profile,
                                period,
                            )
                            csv_path.write_bytes(
                                _fetch_csv(page, base_url, report["route"])
                            )
                            conversion = convert_csv_to_xls(
                                csv_path,
                                destination,
                                report["kind"],
                                period,
                            )
                            report_result = ReportResult(
                                report=report["label"],
                                status="success",
                                path=destination,
                                message=(
                                    "Coleta, conversão e validação concluídas."
                                ),
                                corrected_dates=conversion["corrected_dates"],
                                unit_name=unit_name,
                            )
                        except Exception as error:
                            report_result = ReportResult(
                                report=report["label"],
                                status="failed",
                                message=_redact(
                                    str(error),
                                    profile,
                                    password,
                                ),
                                unit_name=unit_name,
                            )
                        result.reports.append(report_result)
                        _notify(
                            progress,
                            f"{report['label']} · {unit_name}: "
                            f"{'concluído' if report_result.status == 'success' else 'falhou'}"
                            + (
                                f" ({report_result.path})"
                                if report_result.path
                                else f" — {report_result.message}"
                            ),
                        )
            except Exception as error:
                result.error = _redact(str(error), profile, password)
            finally:
                if authenticated and page is not None:
                    try:
                        _notify(progress, "Fazendo logout pelo menu do sistema...")
                        _logout(page)
                        result.logout_confirmed = True
                        _notify(progress, "Logout confirmado na tela de acesso.")
                    except Exception as error:
                        result.error = (
                            f"{result.error + ' ' if result.error else ''}"
                            "Falha ao confirmar o logout: "
                            f"{_redact(str(error), profile, password)}"
                        )
                if context is not None:
                    context.close()

    return result
