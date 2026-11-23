import copy
import logging
import os
import queue
import tempfile
import threading
import tkinter as tk
from datetime import datetime
from logging.handlers import RotatingFileHandler
from tkinter import messagebox, ttk
from tkinter.scrolledtext import ScrolledText

from batch import HotelImportResult, run_import_batch, select_active_hotels
from credentials import (
    CredentialStoreError,
    delete_password,
    read_password,
    save_password,
)
from periods import calculate_report_period
from settings import (
    AppSettings,
    AMERISCONNECT,
    DESBRAVADOR_WEB,
    QUEOPS_DESKTOP,
    MOVEMENT_OPTIONS,
    RESERVATION_FILTERS,
    WEB_SYSTEMS,
    default_config_path,
    default_desktop_path,
    default_downloads_path,
    new_hotel_profile,
)


FILTER_STATE_LABELS = {
    None: "Padrão do sistema",
    True: "Marcar",
    False: "Desmarcar",
}

TREE_STATUS = {
    "success": "Concluído",
    "partial": "Parcial",
    "failed": "Falhou",
}

SYSTEM_LABELS = {
    DESBRAVADOR_WEB: "Desbravador Web",
    QUEOPS_DESKTOP: "Queops (aplicativo)",
    AMERISCONNECT: "AmerisConnect (coletor não disponível)",
}


def _filter_state_value(label):
    return next(
        (
            value
            for value, state_label in FILTER_STATE_LABELS.items()
            if state_label == label
        ),
        None,
    )



def _configure_logging():
    app_data = os.getenv("LOCALAPPDATA")
    log_dir = (
        os.path.join(app_data, "PMSReportAutomation", "logs")
        if app_data
        else os.path.join(
            os.path.expanduser("~"),
            "AppData",
            "Local",
            "PMSReportAutomation",
            "logs",
        )
    )
    logger = logging.getLogger("pms_report_automation")
    logger.setLevel(logging.INFO)
    if logger.handlers:
        return logger, ""

    log_path = os.path.join(log_dir, "automation.log")
    formatter = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    warning = ""
    try:
        os.makedirs(log_dir, exist_ok=True)
        handler = RotatingFileHandler(
            log_path,
            maxBytes=1_000_000,
            backupCount=3,
            encoding="utf-8",
        )
    except OSError as primary_error:
        fallback_dir = os.path.join(
            tempfile.gettempdir(),
            "PMSReportAutomation",
            "logs",
        )
        fallback_path = os.path.join(fallback_dir, "automation.log")
        try:
            os.makedirs(fallback_dir, exist_ok=True)
            handler = RotatingFileHandler(
                fallback_path,
                maxBytes=1_000_000,
                backupCount=3,
                encoding="utf-8",
            )
        except OSError as fallback_error:
            logger.addHandler(logging.NullHandler())
            logger.propagate = False
            return (
                logger,
                "AVISO · Não foi possível gravar logs em "
                f"{log_path} nem em {fallback_path}. "
                f"Detalhes: {fallback_error}",
            )
        warning = (
            f"AVISO · Sem acesso a {log_path}; os logs serão gravados em "
            f"{fallback_path}."
        )

    handler.setFormatter(formatter)
    logger.addHandler(handler)
    return logger, warning


class ReportAutomationApp:
    def __init__(self, root):
        self.root = root
        self.logger, logging_warning = _configure_logging()
        self.settings = AppSettings.load()
        self.settings.output_directory = str(default_desktop_path())
        self.events = queue.Queue()
        self.selected_id = None
        self.worker = None
        self.busy_widgets = []

        root.title("Importação de relatórios | Desbravador")
        root.minsize(1000, 780)
        root.geometry("1280x940")
        root.configure(background="#f3f6fb")
        root.protocol("WM_DELETE_WINDOW", self._on_close)
        self._configure_style()
        self._create_widgets()
        if logging_warning:
            self._append_status(logging_warning)
        self._refresh_hotels()
        self._set_period_text()
        self._poll_events()

    def _configure_style(self):
        style = ttk.Style(self.root)
        if "clam" in style.theme_names():
            style.theme_use("clam")
        style.configure(
            "TFrame",
            background="#f3f6fb",
        )
        style.configure(
            "Panel.TFrame",
            background="#ffffff",
        )
        style.configure(
            "TLabel",
            background="#f3f6fb",
            foreground="#233047",
            font=("Segoe UI", 10),
        )
        style.configure(
            "Panel.TLabel",
            background="#ffffff",
            foreground="#233047",
            font=("Segoe UI", 10),
        )
        style.configure(
            "Title.TLabel",
            background="#f3f6fb",
            foreground="#17263c",
            font=("Segoe UI Semibold", 22),
        )
        style.configure(
            "Subtitle.TLabel",
            background="#f3f6fb",
            foreground="#63718a",
            font=("Segoe UI", 10),
        )
        style.configure(
            "Section.TLabel",
            background="#ffffff",
            foreground="#20304a",
            font=("Segoe UI Semibold", 12),
        )
        style.configure(
            "Accent.TButton",
            background="#1769d2",
            foreground="#ffffff",
            borderwidth=0,
            padding=(18, 11),
            font=("Segoe UI Semibold", 10),
        )
        style.map(
            "Accent.TButton",
            background=[("active", "#0f55ad"), ("disabled", "#a9bedb")],
            foreground=[("disabled", "#eef3fa")],
        )
        style.configure(
            "TButton",
            padding=(10, 7),
            font=("Segoe UI", 9),
        )
        style.configure(
            "Treeview",
            background="#ffffff",
            fieldbackground="#ffffff",
            foreground="#26354a",
            rowheight=29,
            font=("Segoe UI", 9),
        )
        style.configure(
            "Treeview.Heading",
            background="#eaf0f8",
            foreground="#34445d",
            font=("Segoe UI Semibold", 9),
            padding=(8, 8),
        )
        style.map(
            "Treeview",
            background=[("selected", "#dceaff")],
            foreground=[("selected", "#142f55")],
        )
        style.configure(
            "TNotebook",
            background="#ffffff",
            borderwidth=0,
        )
        style.configure(
            "TNotebook.Tab",
            padding=(14, 8),
            font=("Segoe UI Semibold", 9),
        )
        style.configure(
            "TLabelframe",
            background="#ffffff",
            bordercolor="#e2e8f0",
            padding=10,
        )
        style.configure(
            "TLabelframe.Label",
            background="#ffffff",
            foreground="#34445d",
            font=("Segoe UI Semibold", 9),
        )

    def _create_widgets(self):
        shell = ttk.Frame(self.root, padding=(22, 18, 22, 18))
        shell.pack(fill="both", expand=True)
        shell.columnconfigure(0, weight=1)
        shell.rowconfigure(3, weight=2)
        shell.rowconfigure(5, weight=1)
        shell.rowconfigure(6, weight=1)

        header = ttk.Frame(shell)
        header.grid(row=0, column=0, sticky="ew", pady=(0, 14))
        header.columnconfigure(0, weight=1)
        ttk.Label(
            header,
            text="Central de importação",
            style="Title.TLabel",
        ).grid(row=0, column=0, sticky="w")
        ttk.Label(
            header,
            text=(
                "Gerencie os hotéis e acompanhe cada relatório durante "
                "a coleta."
            ),
            style="Subtitle.TLabel",
        ).grid(row=1, column=0, sticky="w", pady=(3, 0))
        self.run_date_label = ttk.Label(header, style="Subtitle.TLabel")
        self.run_date_label.grid(row=0, column=1, rowspan=2, sticky="e")

        command_panel = ttk.Frame(shell, style="Panel.TFrame", padding=14)
        command_panel.grid(row=1, column=0, sticky="ew", pady=(0, 12))
        command_panel.columnconfigure(0, weight=1)
        period = calculate_report_period()
        ttk.Label(
            command_panel,
            text=(
                f"Período de coleta  ·  {period.start_text} a "
                f"{period.end_text}"
            ),
            style="Section.TLabel",
        ).grid(row=0, column=0, sticky="w")
        ttk.Label(
            command_panel,
            text=(
                f"Desbravador: {default_desktop_path()}  ·  "
                f"Queops: {default_downloads_path()}"
            ),
            style="Panel.TLabel",
        ).grid(row=1, column=0, sticky="w", pady=(4, 0))
        self.import_button = ttk.Button(
            command_panel,
            text="Importar todos os hotéis ativos",
            style="Accent.TButton",
            command=self._start_import,
        )
        self.import_button.grid(row=0, column=1, rowspan=2, padx=(16, 0))
        self.busy_widgets.append(self.import_button)
        self.choose_hotels_button = ttk.Button(
            command_panel,
            text="Escolher hotéis...",
            command=self._choose_hotels_to_import,
        )
        self.choose_hotels_button.grid(
            row=0,
            column=2,
            rowspan=2,
            padx=(8, 0),
        )
        self.busy_widgets.append(self.choose_hotels_button)

        self.summary_label = ttk.Label(
            shell,
            text="0 hotéis cadastrados",
            style="Subtitle.TLabel",
        )
        self.summary_label.grid(row=2, column=0, sticky="w", pady=(0, 7))

        workspace = ttk.Panedwindow(shell, orient=tk.HORIZONTAL)
        workspace.grid(row=3, column=0, sticky="nsew", pady=(0, 12))
        hotels_panel = ttk.Frame(workspace, style="Panel.TFrame", padding=12)
        editor_panel = ttk.Frame(workspace, style="Panel.TFrame", padding=12)
        workspace.add(hotels_panel, weight=1)
        workspace.add(editor_panel, weight=3)
        hotels_panel.rowconfigure(1, weight=1)
        hotels_panel.columnconfigure(0, weight=1)
        editor_panel.rowconfigure(1, weight=1)
        editor_panel.columnconfigure(0, weight=1)

        ttk.Label(
            hotels_panel,
            text="Seus hotéis",
            style="Section.TLabel",
        ).grid(row=0, column=0, sticky="w", pady=(1, 10))
        self.hotel_tree = ttk.Treeview(
            hotels_panel,
            columns=("hotel", "active"),
            show="headings",
            selectmode="browse",
            height=12,
        )
        self.hotel_tree.heading("hotel", text="Hotel")
        self.hotel_tree.heading("active", text="Importar")
        self.hotel_tree.column("hotel", width=190, minwidth=130, stretch=True)
        self.hotel_tree.column("active", width=76, minwidth=68, stretch=False, anchor="center")
        self.hotel_tree.grid(row=1, column=0, sticky="nsew")
        self.hotel_tree.bind("<<TreeviewSelect>>", self._select_hotel)
        self._register_busy(self.hotel_tree)

        hotel_actions = ttk.Frame(hotels_panel, style="Panel.TFrame")
        hotel_actions.grid(row=2, column=0, sticky="ew", pady=(9, 0))
        new_button = ttk.Button(
            hotel_actions,
            text="+ Novo hotel",
            command=self._new_hotel,
        )
        new_button.pack(side="left")
        remove_button = ttk.Button(
            hotel_actions,
            text="Remover",
            command=self._remove_hotel,
        )
        remove_button.pack(side="left", padx=(7, 0))
        self._register_busy(new_button, remove_button)

        ttk.Label(
            editor_panel,
            text="Cadastro e filtros",
            style="Section.TLabel",
        ).grid(row=0, column=0, sticky="w", pady=(1, 10))
        self.editor_notebook = ttk.Notebook(editor_panel)
        self.editor_notebook.grid(row=1, column=0, sticky="nsew")
        self._register_busy(self.editor_notebook)
        general_tab = ttk.Frame(self.editor_notebook, style="Panel.TFrame", padding=16)
        reservation_tab = ttk.Frame(
            self.editor_notebook,
            style="Panel.TFrame",
            padding=16,
        )
        movement_tab = ttk.Frame(
            self.editor_notebook,
            style="Panel.TFrame",
            padding=16,
        )
        self.editor_notebook.add(general_tab, text="Hotel")
        self.editor_notebook.add(reservation_tab, text="Relatório C · Reservas")
        self.editor_notebook.add(
            movement_tab,
            text="Relatório R · Movimentação",
        )
        general_tab.columnconfigure(1, weight=1)

        self.name_var = tk.StringVar()
        self.system_var = tk.StringVar(value=SYSTEM_LABELS[DESBRAVADOR_WEB])
        self.url_var = tk.StringVar()
        self.username_var = tk.StringVar()
        self.password_var = tk.StringVar()
        self.additional_unit_var = tk.StringVar()
        self.unit_selector_name_var = tk.StringVar()
        self.password_status_var = tk.StringVar(
            value="A senha será salva com proteção no Windows."
        )
        self.active_var = tk.BooleanVar(value=True)

        self.name_entry = self._add_entry(
            general_tab,
            "Nome do hotel",
            self.name_var,
            0,
        )
        ttk.Label(general_tab, text="Sistema", style="Panel.TLabel").grid(
            row=1,
            column=0,
            sticky="w",
            padx=(0, 12),
            pady=7,
        )
        self.system_combo = ttk.Combobox(
            general_tab,
            textvariable=self.system_var,
            values=tuple(SYSTEM_LABELS.values()),
            state="readonly",
        )
        self.system_combo.grid(row=1, column=1, sticky="ew", pady=7)
        self.system_combo.bind(
            "<<ComboboxSelected>>",
            self._system_changed,
        )
        self._register_busy(self.system_combo)
        self.url_entry = self._add_entry(general_tab, "URL de acesso", self.url_var, 2)
        self.username_entry = self._add_entry(general_tab, "Usuário", self.username_var, 3)
        self.unit_selector_entry = self._add_entry(
            general_tab,
            "Nome atual no seletor",
            self.unit_selector_name_var,
            4,
        )
        self._system_web_controls = (
            self.url_entry,
            self.unit_selector_entry,
        )
        ttk.Label(general_tab, text="Senha", style="Panel.TLabel").grid(
            row=5,
            column=0,
            sticky="w",
            pady=7,
        )
        password_entry = ttk.Entry(
            general_tab,
            textvariable=self.password_var,
            show="*",
        )
        password_entry.grid(row=5, column=1, sticky="ew", pady=7)
        ttk.Label(
            general_tab,
            textvariable=self.password_status_var,
            style="Subtitle.TLabel",
            wraplength=560,
        ).grid(row=6, column=1, sticky="w", pady=(0, 12))
        ttk.Label(
            general_tab,
            text="Unidade adicional após esta coleta",
            style="Panel.TLabel",
        ).grid(row=7, column=0, sticky="w", padx=(0, 12), pady=7)
        additional_unit_entry = ttk.Entry(
            general_tab,
            textvariable=self.additional_unit_var,
        )
        additional_unit_entry.grid(row=7, column=1, sticky="ew", pady=7)
        self._system_web_controls += (additional_unit_entry,)
        self._system_credential_controls = (
            self.username_entry,
            password_entry,
        )
        ttk.Label(
            general_tab,
            text=(
                "Opcional. A automação coleta C e R do hotel acima, troca "
                "para esta unidade e coleta C e R dela usando o mesmo login."
            ),
            style="Subtitle.TLabel",
            wraplength=560,
        ).grid(row=8, column=1, sticky="w", pady=(0, 12))
        self.active_checkbox = ttk.Checkbutton(
            general_tab,
            text="Incluir este hotel quando importar todos os ativos",
            variable=self.active_var,
        )
        self.active_checkbox.grid(
            row=9,
            column=0,
            columnspan=2,
            sticky="w",
            pady=(4, 12),
        )
        ttk.Label(
            general_tab,
            text=(
                "A coleta segue em sequência: login, relatórios C e R, "
                "e logout antes do próximo hotel."
            ),
            style="Subtitle.TLabel",
            wraplength=560,
        ).grid(row=10, column=0, columnspan=2, sticky="w")
        self._register_busy(
            password_entry,
            additional_unit_entry,
            self.active_checkbox,
        )
        self._system_changed()

        self.reservation_vars = {
            key: tk.StringVar(value=FILTER_STATE_LABELS[None])
            for key in RESERVATION_FILTERS
        }
        reservation_tab.columnconfigure(1, weight=1)
        ttk.Label(
            reservation_tab,
            text=(
                "Escolha o estado do filtro; “Padrão do sistema” mantém "
                "a configuração original do hotel."
            ),
            style="Subtitle.TLabel",
            wraplength=620,
        ).grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 14))
        for row, (key, label) in enumerate(RESERVATION_FILTERS.items(), start=1):
            ttk.Label(
                reservation_tab,
                text=label,
                style="Panel.TLabel",
            ).grid(row=row, column=0, sticky="w", padx=(0, 12), pady=8)
            control = ttk.Combobox(
                reservation_tab,
                textvariable=self.reservation_vars[key],
                values=tuple(FILTER_STATE_LABELS.values()),
                state="readonly",
                width=22,
            )
            control.grid(row=row, column=1, sticky="ew", pady=8)
            self._register_busy(control)

        self.movement_vars = {
            key: tk.StringVar(value=FILTER_STATE_LABELS[None])
            for key in MOVEMENT_OPTIONS
        }
        movement_tab.columnconfigure(1, weight=1)
        ttk.Label(
            movement_tab,
            text=(
                "Defina os filtros específicos do relatório de "
                "Movimentação com diária."
            ),
            style="Subtitle.TLabel",
            wraplength=620,
        ).grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 14))
        for row, (key, label) in enumerate(MOVEMENT_OPTIONS.items(), start=1):
            ttk.Label(
                movement_tab,
                text=label,
                style="Panel.TLabel",
                wraplength=470,
            ).grid(row=row, column=0, sticky="w", padx=(0, 12), pady=8)
            control = ttk.Combobox(
                movement_tab,
                textvariable=self.movement_vars[key],
                values=tuple(FILTER_STATE_LABELS.values()),
                state="readonly",
                width=22,
            )
            control.grid(row=row, column=1, sticky="ew", pady=8)
            self._register_busy(control)

        editor_actions = ttk.Frame(editor_panel, style="Panel.TFrame")
        editor_actions.grid(row=2, column=0, sticky="ew", pady=(10, 0))
        save_button = ttk.Button(
            editor_actions,
            text="Salvar configuração do hotel",
            command=self._save_hotel,
        )
        save_button.pack(side="left")
        self._register_busy(save_button)
        ttk.Label(
            editor_actions,
            text="Novos dados e senha só entram na próxima importação.",
            style="Subtitle.TLabel",
        ).pack(side="left", padx=(12, 0))

        results_panel = ttk.Frame(shell, style="Panel.TFrame", padding=12)
        results_panel.grid(row=4, column=0, sticky="ew", pady=(0, 12))
        results_panel.columnconfigure(0, weight=1)
        ttk.Label(
            results_panel,
            text="Situação de cada hotel e relatório",
            style="Section.TLabel",
        ).grid(row=0, column=0, sticky="w", pady=(0, 9))
        self.status_tree = ttk.Treeview(
            results_panel,
            columns=("hotel", "status", "reservations", "movement", "logout"),
            show="headings",
            height=5,
        )
        status_columns = (
            ("hotel", "Hotel", 220, True),
            ("status", "Importação", 110, False),
            ("reservations", "Principal / C", 115, False),
            ("movement", "Secundário / R", 130, False),
            ("logout", "Logout", 120, False),
        )
        for column, heading, width, stretch in status_columns:
            self.status_tree.heading(column, text=heading)
            self.status_tree.column(
                column,
                width=width,
                minwidth=80,
                stretch=stretch,
            )
        self.status_tree.grid(row=1, column=0, sticky="ew")
        ttk.Label(
            shell,
            text="Detalhes, arquivos gerados e erros",
            style="Section.TLabel",
        ).grid(row=5, column=0, sticky="w", pady=(0, 6))
        self.status_text = ScrolledText(
            shell,
            height=7,
            wrap="word",
            state="disabled",
            background="#ffffff",
            foreground="#26354a",
            relief="flat",
            borderwidth=0,
            font=("Consolas", 9),
            padx=10,
            pady=8,
        )
        self.status_text.grid(row=6, column=0, sticky="nsew")

        self._entry_widgets = [
            widget
            for widget in general_tab.winfo_children()
            if isinstance(widget, ttk.Entry)
        ]
        self._register_busy(*self._entry_widgets)

    def _register_busy(self, *widgets):
        self.busy_widgets.extend(widgets)

    def _add_entry(self, parent, label, variable, row):
        ttk.Label(parent, text=label, style="Panel.TLabel").grid(
            row=row,
            column=0,
            sticky="w",
            padx=(0, 12),
            pady=7,
        )
        entry = ttk.Entry(parent, textvariable=variable)
        entry.grid(row=row, column=1, sticky="ew", pady=7)
        self._register_busy(entry)
        return entry

    def _set_period_text(self):
        self.run_date_label.configure(
            text=datetime.now().strftime("Execução · %d/%m/%Y")
        )

    def _system_changed(self, _event=None):
        del _event
        selected_system = next(
            (
                key
                for key, label in SYSTEM_LABELS.items()
                if label == self.system_var.get()
            ),
            None,
        )
        is_web = selected_system in WEB_SYSTEMS
        is_desbravador = selected_system == DESBRAVADOR_WEB
        for widget in self._system_web_controls:
            widget.configure(state="normal" if is_web else "disabled")
        for widget in self._system_credential_controls:
            widget.configure(state="normal")
        for tab in (1, 2):
            self.editor_notebook.tab(
                tab,
                state="normal" if is_desbravador else "disabled",
            )
        if self.selected_id:
            hotel = next(
                (
                    item
                    for item in self.settings.hotels
                    if item.id == self.selected_id
                ),
                None,
            )
            if hotel:
                self._refresh_password_status(hotel)
        else:
            self.password_status_var.set(
                "A senha será salva com proteção no Windows."
            )

    def _refresh_hotels(self, select_id=None):
        self.hotel_tree.delete(*self.hotel_tree.get_children())
        for hotel in self.settings.hotels:
            self.hotel_tree.insert(
                "",
                tk.END,
                iid=hotel.id,
                values=(
                    f"{hotel.name} · {SYSTEM_LABELS[hotel.system]}",
                    "Ativo" if hotel.active else "Inativo",
                ),
            )
        active_count = sum(hotel.active for hotel in self.settings.hotels)
        total = len(self.settings.hotels)
        self.summary_label.configure(
            text=f"{total} hotéis cadastrados  ·  {active_count} ativos para importação"
        )
        if select_id and self.hotel_tree.exists(select_id):
            self.hotel_tree.selection_set(select_id)
            self.hotel_tree.focus(select_id)
            self._load_hotel(
                next(hotel for hotel in self.settings.hotels if hotel.id == select_id)
            )
        elif not self.settings.hotels:
            self._clear_editor()

    def _select_hotel(self, _event=None):
        del _event
        selected = self.hotel_tree.selection()
        if not selected:
            return
        hotel = next(
            item for item in self.settings.hotels if item.id == selected[0]
        )
        self._load_hotel(hotel)

    def _load_hotel(self, hotel):
        self.selected_id = hotel.id
        self.name_var.set(hotel.name)
        self.system_var.set(SYSTEM_LABELS[hotel.system])
        self.url_var.set(hotel.url)
        self.username_var.set(hotel.username)
        self.password_var.set("")
        self.additional_unit_var.set(hotel.additional_unit)
        self.unit_selector_name_var.set(
            hotel.unit_selector_name or hotel.name
        )
        self._refresh_password_status(hotel)
        self.active_var.set(hotel.active)
        self._system_changed()
        for key, variable in self.reservation_vars.items():
            state = hotel.reservation_filter_overrides.get(key)
            if state is None and key in hotel.disabled_reservation_filters:
                state = False
            variable.set(FILTER_STATE_LABELS[state])
        for key, variable in self.movement_vars.items():
            variable.set(
                FILTER_STATE_LABELS.get(hotel.movement_options.get(key))
            )

    def _clear_editor(self):
        self.selected_id = None
        self.name_var.set("")
        self.system_var.set(SYSTEM_LABELS[DESBRAVADOR_WEB])
        self.url_var.set("")
        self.username_var.set("")
        self.password_var.set("")
        self.additional_unit_var.set("")
        self.unit_selector_name_var.set("")
        self.password_status_var.set(
            "A senha será salva com proteção no Windows."
        )
        self.active_var.set(True)
        self._system_changed()
        for variable in self.reservation_vars.values():
            variable.set(FILTER_STATE_LABELS[None])
        for variable in self.movement_vars.values():
            variable.set(FILTER_STATE_LABELS[None])

    def _new_hotel(self):
        self.hotel_tree.selection_remove(self.hotel_tree.selection())
        self._clear_editor()
        self.name_var.set("")
        self.editor_notebook.select(0)
        self.name_entry.focus_set()

    def _candidate_from_editor(self):
        name = self.name_var.get().strip()
        system = next(
            (
                key
                for key, label in SYSTEM_LABELS.items()
                if label == self.system_var.get()
            ),
            None,
        )
        if not name or system is None:
            raise ValueError("Informe o nome do hotel e o sistema de gestão.")
        url = self.url_var.get().strip() if system in WEB_SYSTEMS else ""
        username = self.username_var.get().strip()
        if not username:
            raise ValueError("Preencha o usuário do hotel.")
        if system == DESBRAVADOR_WEB and not url:
            raise ValueError("Preencha a URL do hotel.")

        existing = next(
            (hotel for hotel in self.settings.hotels if hotel.id == self.selected_id),
            None,
        )
        if existing:
            candidate = copy.deepcopy(existing)
            candidate.name = name
            candidate.system = system
            candidate.url = url
            candidate.username = username
        else:
            candidate = new_hotel_profile(
                name,
                url,
                username,
                system=system,
            )
        additional_unit = (
            self.additional_unit_var.get().strip()
            if system == DESBRAVADOR_WEB
            else ""
        )
        if existing is not None or additional_unit:
            candidate.additional_unit = additional_unit
        candidate.unit_selector_name = (
            self.unit_selector_name_var.get().strip() or candidate.name
            if system == DESBRAVADOR_WEB
            else ""
        )
        candidate.active = self.active_var.get()
        candidate.disabled_reservation_filters = [
            key
            for key, variable in self.reservation_vars.items()
            if variable.get() == FILTER_STATE_LABELS[False]
        ]
        candidate.reservation_filter_overrides = {
            key: _filter_state_value(variable.get())
            for key, variable in self.reservation_vars.items()
            if variable.get() != FILTER_STATE_LABELS[None]
        }
        candidate.movement_options = {
            key: _filter_state_value(variable.get())
            for key, variable in self.movement_vars.items()
            if variable.get() != FILTER_STATE_LABELS[None]
        }
        return candidate, existing

    def _save_hotel(self, show_message=True):
        try:
            candidate, existing = self._candidate_from_editor()
            password = self.password_var.get()
            if not password:
                password = read_password(candidate.credential_target)
            if not password:
                raise CredentialStoreError(
                    "Informe uma senha para este hotel. A senha será salva "
                    "no Gerenciador de Credenciais do Windows."
                )
            hotels = list(self.settings.hotels)
            if existing is None:
                hotels.append(candidate)
            else:
                hotels[hotels.index(existing)] = candidate
            updated_settings = AppSettings(
                hotels=hotels,
                output_directory=str(default_desktop_path()),
                output_format="xls",
            )
            updated_settings.validate()
            updated_settings.save()
            try:
                save_password(
                    candidate.credential_target,
                    candidate.username,
                    password,
                )
            except CredentialStoreError:
                self.settings.save()
                raise
        except (ValueError, CredentialStoreError, OSError) as error:
            self.logger.error("Falha ao salvar configuração: %s", error)
            if show_message:
                messagebox.showerror(
                    "Não foi possível salvar",
                    str(error),
                    parent=self.root,
                )
            self._append_status(f"ERRO AO SALVAR · {error}")
            return False

        self.settings = updated_settings
        self.password_var.set("")
        self._refresh_hotels(candidate.id)
        if show_message:
            self._append_status(
                f"Configuração salva · {candidate.name} "
                f"({'ativo' if candidate.active else 'inativo'})."
            )
        return True

    def _refresh_password_status(self, hotel):
        try:
            is_saved = bool(read_password(hotel.credential_target))
        except CredentialStoreError as error:
            self.password_status_var.set(
                "Não foi possível verificar a senha salva no Windows."
            )
            self.logger.error(
                "Falha ao verificar credencial do hotel %s: %s",
                hotel.name,
                error,
            )
            self._append_status(
                f"ERRO AO VERIFICAR SENHA · {hotel.name} · {error}"
            )
            return

        if is_saved:
            self.password_status_var.set(
                f"Senha do {SYSTEM_LABELS[hotel.system]} salva no Windows. "
                "Deixe o campo vazio para mantê-la ou digite outra para atualizá-la."
            )
        else:
            self.password_status_var.set(
                "Nenhuma senha salva. Digite-a; ela será protegida no Windows."
            )

    def _remove_hotel(self):
        hotel = next(
            (item for item in self.settings.hotels if item.id == self.selected_id),
            None,
        )
        if hotel is None:
            messagebox.showinfo(
                "Remover hotel",
                "Selecione um hotel antes de removê-lo.",
                parent=self.root,
            )
            return
        if not messagebox.askyesno(
            "Remover hotel",
            f"Remover “{hotel.name}” e a senha associada do Windows?",
            parent=self.root,
        ):
            return

        updated_settings = AppSettings(
            hotels=[
                item for item in self.settings.hotels if item.id != hotel.id
            ],
            output_directory=str(default_desktop_path()),
            output_format="xls",
        )
        try:
            updated_settings.save()
            delete_password(hotel.credential_target)
        except (ValueError, CredentialStoreError, OSError) as error:
            self.logger.error("Falha ao remover hotel: %s", error)
            messagebox.showerror(
                "Não foi possível remover",
                str(error),
                parent=self.root,
            )
            return
        self.settings = updated_settings
        self._refresh_hotels()
        self._append_status(f"Hotel removido · {hotel.name}")

    def _save_current_hotel_before_import(self):
        if self.selected_id and not self._save_hotel(show_message=False):
            messagebox.showerror(
                "Configuração inválida",
                "Corrija os dados do hotel selecionado antes de importar.",
                parent=self.root,
            )
            return False
        return True

    def _choose_hotels_to_import(self):
        if self.worker and self.worker.is_alive():
            return
        if not self._save_current_hotel_before_import():
            return

        active_hotels = select_active_hotels(self.settings.hotels)
        if not active_hotels:
            messagebox.showwarning(
                "Nenhum hotel ativo",
                "Ative pelo menos um hotel na aba Hotel e salve a configuração.",
                parent=self.root,
            )
            return

        dialog = tk.Toplevel(self.root)
        dialog.title("Escolher hotéis para importar")
        dialog.transient(self.root)
        dialog.resizable(False, False)
        dialog.grab_set()

        ttk.Label(
            dialog,
            text="Marque os hotéis ativos que deseja importar:",
            padding=(16, 14, 16, 8),
        ).pack(anchor="w")
        selection_vars = {}
        options = ttk.Frame(dialog, padding=(16, 0, 16, 8))
        options.pack(fill="both", expand=True)
        for hotel in active_hotels:
            selected = tk.BooleanVar(master=dialog, value=True)
            selection_vars[hotel.id] = selected
            ttk.Checkbutton(
                options,
                text=hotel.name,
                variable=selected,
            ).pack(anchor="w", pady=2)

        actions = ttk.Frame(dialog, padding=(16, 4, 16, 14))
        actions.pack(fill="x")

        def set_all_selected(value):
            for selected in selection_vars.values():
                selected.set(value)

        ttk.Button(
            actions,
            text="Todos",
            command=lambda: set_all_selected(True),
        ).pack(side="left")
        ttk.Button(
            actions,
            text="Nenhum",
            command=lambda: set_all_selected(False),
        ).pack(side="left", padx=(6, 0))

        def start_selected_import():
            selected_ids = {
                hotel_id
                for hotel_id, selected in selection_vars.items()
                if selected.get()
            }
            if not selected_ids:
                messagebox.showwarning(
                    "Nenhum hotel selecionado",
                    "Marque pelo menos um hotel para importar.",
                    parent=dialog,
                )
                return
            dialog.destroy()
            self._start_import(selected_ids)

        ttk.Button(
            actions,
            text="Importar selecionados",
            style="Accent.TButton",
            command=start_selected_import,
        ).pack(side="right")
        ttk.Button(
            actions,
            text="Cancelar",
            command=dialog.destroy,
        ).pack(side="right", padx=(0, 6))

    def _start_import(self, selected_ids=None):
        if self.worker and self.worker.is_alive():
            return
        if not self._save_current_hotel_before_import():
            return

        active_hotels = [
            copy.deepcopy(hotel)
            for hotel in select_active_hotels(
                self.settings.hotels,
                selected_ids,
            )
        ]
        if not active_hotels:
            messagebox.showwarning(
                "Nenhum hotel para importar",
                "Ative ou selecione pelo menos um hotel para importar.",
                parent=self.root,
            )
            return

        self.status_tree.delete(*self.status_tree.get_children())
        for hotel in active_hotels:
            self.status_tree.insert(
                "",
                tk.END,
                iid=hotel.id,
                values=(
                    hotel.name,
                    "Aguardando",
                    "Aguardando",
                    "Aguardando",
                    "—",
                ),
            )
        self._append_status(
            f"IMPORTAÇÃO INICIADA · {len(active_hotels)} hotel(is)."
        )
        self._set_busy(True)
        self.worker = threading.Thread(
            target=self._import_worker,
            args=(active_hotels,),
            daemon=True,
        )
        self.worker.start()

    def _import_worker(self, hotels):
        try:
            results = run_import_batch(
                hotels,
                default_desktop_path(),
                progress_callback=lambda event, hotel, message: self.events.put(
                    (event, hotel, message)
                ),
            )
            for result in results:
                self.events.put(("hotel_result", result, ""))
        except Exception as error:
            self.events.put(("batch_error", None, str(error)))
        finally:
            self.events.put(("batch_finished", None, ""))

    def _set_busy(self, busy):
        self.import_button.configure(
            state="disabled" if busy else "normal",
        )
        for widget in self.busy_widgets:
            if widget is self.import_button:
                continue
            try:
                widget.state(["disabled"] if busy else ["!disabled"])
            except tk.TclError:
                try:
                    widget.configure(state="disabled" if busy else "normal")
                except tk.TclError:
                    pass

    def _poll_events(self):
        while True:
            try:
                event, hotel, message = self.events.get_nowait()
            except queue.Empty:
                break

            if event == "hotel_started":
                self._set_hotel_status(hotel.id, status="Conectando")
                self._append_status(f"[{hotel.name}] Iniciando importação.")
            elif event == "progress":
                self._update_progress_status(hotel, message)
                self._append_status(f"[{hotel.name}] {message}")
                self.logger.info("[%s] %s", hotel.name, message)
            elif event == "hotel_finished":
                self._append_status(
                    f"[{hotel.name}] Etapa finalizada: {TREE_STATUS.get(message, message)}."
                )
            elif event == "hotel_result":
                self._show_hotel_result(hotel)
            elif event == "batch_error":
                self._append_status(f"ERRO GERAL · {message}")
                self.logger.error("Falha geral na importação: %s", message)
                for hotel_id in self.status_tree.get_children():
                    self._set_hotel_status(
                        hotel_id,
                        status="Falhou",
                        reservations="Não executado",
                        movement="Não executado",
                    )
            elif event == "batch_finished":
                self._set_busy(False)
                self._show_batch_summary()
        self.root.after(150, self._poll_events)

    def _set_hotel_status(
        self,
        hotel_id,
        status=None,
        reservations=None,
        movement=None,
        logout=None,
    ):
        if not self.status_tree.exists(hotel_id):
            return
        current = list(self.status_tree.item(hotel_id, "values"))
        if status is not None:
            current[1] = status
        if reservations is not None:
            current[2] = reservations
        if movement is not None:
            current[3] = movement
        if logout is not None:
            current[4] = logout
        self.status_tree.item(hotel_id, values=current)

    def _update_progress_status(self, hotel, message):
        if message.startswith("Acessando"):
            self._set_hotel_status(hotel.id, status="Conectando")
        elif message.startswith("Trocando unidade"):
            self._set_hotel_status(hotel.id, status="Trocando unidade")
        elif message.startswith("Coletando e convertendo"):
            if "Reservas" in message:
                self._set_hotel_status(
                    hotel.id,
                    status="Importando C",
                    reservations="Em andamento",
                )
            else:
                self._set_hotel_status(
                    hotel.id,
                    status="Importando R",
                    movement="Em andamento",
                )
        elif message.startswith("Gerando") or message.startswith("Exportando"):
            self._set_hotel_status(
                hotel.id,
                status="Importando principal",
                reservations="Em andamento",
            )
        elif message.startswith("Fazendo logout"):
            self._set_hotel_status(hotel.id, status="Logout")
        elif message.startswith("Logout confirmado"):
            self._set_hotel_status(hotel.id, logout="Confirmado")

    def _show_hotel_result(self, result: HotelImportResult):
        collection = result.collection
        report_status = collection.reports if collection else []
        reservations = [
            report for report in report_status if report.report == "Reservas"
        ]
        movement_reports = [
            report
            for report in report_status
            if report.report == "Movimentação com diária"
        ]
        if result.hotel.system == QUEOPS_DESKTOP:
            reservations = report_status
            movement_reports = []
        self._set_hotel_status(
            result.hotel.id,
            status=TREE_STATUS.get(result.status, result.status),
            reservations=self._report_state(reservations),
            movement=self._report_state(movement_reports),
            logout=(
                "Confirmado"
                if collection and collection.logout_confirmed
                else "Não confirmado"
                if collection and collection.logout_required
                else "Não necessário"
                if collection
                else "—"
            ),
        )
        if result.error:
            self._append_status(f"[{result.hotel.name}] ERRO · {result.error}")
            self.logger.error("[%s] %s", result.hotel.name, result.error)
        if collection:
            for report in collection.reports:
                unit = f" ({report.unit_name})" if report.unit_name else ""
                if report.status == "success":
                    corrected_dates = (
                        f" · {report.corrected_dates} data(s) ajustada(s)."
                        if result.hotel.system == DESBRAVADOR_WEB
                        else "."
                    )
                    self._append_status(
                        f"[{result.hotel.name}{unit}] {report.report} · "
                        f"OK · {report.path}{corrected_dates}"
                    )
                else:
                    self._append_status(
                        f"[{result.hotel.name}{unit}] ERRO em {report.report} · "
                        f"{report.message}"
                    )
                    self.logger.error(
                        "[%s%s] Falha em %s: %s",
                        result.hotel.name,
                        unit,
                        report.report,
                        report.message,
                    )

    @staticmethod
    def _report_state(reports):
        if not reports:
            return "—"
        succeeded = sum(report.status == "success" for report in reports)
        if succeeded == len(reports):
            return "OK" if len(reports) == 1 else f"OK ({succeeded}/{len(reports)})"
        if succeeded:
            return f"Parcial ({succeeded}/{len(reports)})"
        return "Falhou" if len(reports) == 1 else f"Falhou (0/{len(reports)})"

    def _show_batch_summary(self):
        rows = [
            self.status_tree.item(item, "values")
            for item in self.status_tree.get_children()
        ]
        succeeded = sum(row[1] == "Concluído" for row in rows)
        partial = sum(row[1] == "Parcial" for row in rows)
        failed = sum(row[1] == "Falhou" for row in rows)
        summary = (
            f"Importação encerrada · {succeeded} concluído(s), "
            f"{partial} parcial(is), {failed} falha(s)."
        )
        self._append_status(summary)
        if failed or partial:
            failures = []
            for row in rows:
                if row[1] != "Concluído":
                    failures.append(
                        f"• {row[0]} — {row[1]} "
                        f"(C: {row[2]}, R: {row[3]}, logout: {row[4]})"
                    )
            details = "\n".join(failures)
            messagebox.showwarning(
                "Importação finalizada com problemas",
                f"{summary}\n\n{details}\n\nConsulte a área de detalhes "
                "para as causas e ações tomadas.",
                parent=self.root,
            )
        else:
            messagebox.showinfo(
                "Importação concluída",
                f"{summary}\nConsulte os detalhes para ver os arquivos gerados.",
                parent=self.root,
            )

    def _append_status(self, message):
        self.status_text.configure(state="normal")
        self.status_text.insert(tk.END, f"{message}\n")
        self.status_text.see(tk.END)
        self.status_text.configure(state="disabled")

    def _on_close(self):
        if self.worker and self.worker.is_alive():
            messagebox.showwarning(
                "Importação em andamento",
                "Aguarde a conclusão dos hotéis e a confirmação dos logouts "
                "antes de fechar o aplicativo.",
                parent=self.root,
            )
            return
        self.root.destroy()


def main():
    root = tk.Tk()
    try:
        ReportAutomationApp(root)
    except (OSError, ValueError, CredentialStoreError) as error:
        messagebox.showerror(
            "Erro ao iniciar",
            f"Não foi possível carregar as configurações "
            f"({default_config_path()}): {error}",
            parent=root,
        )
        root.destroy()
        return
    root.mainloop()


if __name__ == "__main__":
    main()
