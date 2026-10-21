from __future__ import annotations

import sys
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from backup_manager import create_backup
from client_scanner import ClientInstallation, discover_clients
from config_patcher import patch_plain_ini
from encrypted_patcher import patch_encrypted_config

APP_TITLE = "L2C6 Universal Patcher"
DEFAULT_SERVER = "ujuko1bg.pwrp.cc"


def _find_l2encdec() -> Path:
    bases = [
        Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent)),
        Path(__file__).resolve().parent.parent / "vendor" / "bin",
    ]
    for base in bases:
        for name in ("l2encdec.exe", "l2encdec"):
            candidate = base / name
            if candidate.is_file():
                return candidate.resolve()
    raise FileNotFoundError(
        "Не найден l2encdec. Проверьте комплектность Windows-сборки."
    )


class PatcherApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(APP_TITLE)
        self.geometry("820x620")
        self.minsize(700, 540)
        self.configure(padx=0, pady=0)

        self.folder = tk.StringVar()
        self.server_address = tk.StringVar(value=DEFAULT_SERVER)
        self.status = tk.StringVar(value="Выберите папку клиента Lineage 2.")
        self.client_choice = tk.StringVar()
        self.clients: list[ClientInstallation] = []
        self.selected_client: ClientInstallation | None = None
        self._build_ui()
        self._set_actions(False)

    def _build_ui(self):
        outer = ttk.Frame(self, padding=20)
        outer.pack(fill="both", expand=True)

        ttk.Label(
            outer, text="L2C6 Universal Patcher",
            font=("Segoe UI", 20, "bold")
        ).pack(anchor="w")
        ttk.Label(
            outer,
            text="Lineage 2 Interlude C6  •  безопасная настройка клиента",
        ).pack(anchor="w", pady=(3, 18))

        folder_box = ttk.LabelFrame(outer, text="1. Папка игры", padding=12)
        folder_box.pack(fill="x")
        row = ttk.Frame(folder_box)
        row.pack(fill="x")
        ttk.Entry(row, textvariable=self.folder).pack(
            side="left", fill="x", expand=True
        )
        ttk.Button(row, text="Обзор…", command=self.choose_folder).pack(
            side="left", padx=(8, 0)
        )
        ttk.Label(
            folder_box,
            text="После выбора папки программа автоматически найдёт установки.",
        ).pack(anchor="w", pady=(8, 0))

        client_box = ttk.LabelFrame(outer, text="2. Найденный клиент", padding=12)
        client_box.pack(fill="x", pady=(12, 0))
        self.client_combo = ttk.Combobox(
            client_box, textvariable=self.client_choice,
            state="disabled", width=70
        )
        self.client_combo.pack(fill="x")
        self.client_combo.bind("<<ComboboxSelected>>", self._on_client_selected)

        self.result = tk.Text(
            outer, height=10, wrap="word", state="disabled",
            font=("Consolas", 10), relief="solid", borderwidth=1
        )
        self.result.pack(fill="both", expand=True, pady=12)

        server_box = ttk.LabelFrame(
            outer, text="3. Подключение к серверу", padding=12
        )
        server_box.pack(fill="x")
        ttk.Label(server_box, text="Адрес сервера:").grid(
            row=0, column=0, sticky="w"
        )
        ttk.Entry(
            server_box, textvariable=self.server_address
        ).grid(row=0, column=1, sticky="ew", padx=8)
        self.patch_button = ttk.Button(
            server_box, text="Применить настройки подключения",
            command=self.patch_config
        )
        self.patch_button.grid(row=0, column=2, sticky="e")
        server_box.columnconfigure(1, weight=1)

        action_row = ttk.Frame(outer)
        action_row.pack(fill="x", pady=(12, 0))
        self.backup_button = ttk.Button(
            action_row, text="Создать резервную копию",
            command=self.make_backup
        )
        self.backup_button.pack(side="left")
        self.update_button = ttk.Button(
            action_row, text="Обновление: пакет не готов", state="disabled"
        )
        self.update_button.pack(side="left", padx=(8, 0))
        ttk.Label(
            action_row, textvariable=self.status, wraplength=520
        ).pack(side="left", fill="x", expand=True, padx=(12, 0))

    def _set_actions(self, enabled: bool):
        state = "normal" if enabled else "disabled"
        self.backup_button.configure(state=state)
        self.patch_button.configure(state=state)

    def _show_result(self, text: str):
        self.result.configure(state="normal")
        self.result.delete("1.0", "end")
        self.result.insert("1.0", text)
        self.result.configure(state="disabled")

    def choose_folder(self):
        folder = filedialog.askdirectory(title="Выберите папку Lineage 2")
        if folder:
            self.folder.set(folder)
            self.scan_folder()

    def scan_folder(self):
        folder = self.folder.get().strip()
        if not folder:
            messagebox.showinfo(APP_TITLE, "Сначала выберите папку игры.")
            return
        self.selected_client = None
        self.clients = []
        self.client_choice.set("")
        self.client_combo.configure(state="disabled", values=())
        self._set_actions(False)
        try:
            self.clients = discover_clients(Path(folder), max_depth=3)
        except Exception as exc:
            self._show_result(f"Ошибка поиска клиента:\n{exc}")
            self.status.set("Поиск не завершён.")
            return

        if not self.clients:
            self._show_result(
                "Совместимый клиент не найден.\n\n"
                "Ожидается L2.exe внутри папки system, system2, "
                "system_* или system-*.\n\n"
                "Выберите папку игры или папку уровнем выше."
            )
            self.status.set("Клиент не найден.")
            return

        labels = [
            f"{i + 1}. {client.root}  [{client.system_dir.name}]"
            for i, client in enumerate(self.clients)
        ]
        self.client_combo.configure(values=labels, state="readonly")
        if len(self.clients) == 1:
            self.client_combo.current(0)
            self._select_client(0)
        else:
            self._show_result(
                f"Найдено установок: {len(self.clients)}.\n\n"
                "Выберите нужную установку в списке выше. "
                "До выбора операции с файлами недоступны."
            )
            self.status.set(f"Найдено вариантов: {len(self.clients)}. Выберите клиент.")

    def _on_client_selected(self, _event=None):
        index = self.client_combo.current()
        if index >= 0:
            self._select_client(index)

    def _select_client(self, index: int):
        if not 0 <= index < len(self.clients):
            return
        self.selected_client = self.clients[index]
        client = self.selected_client
        config = str(client.config) if client.config else "не найдена"
        details = (
            f"Клиент выбран\n"
            f"{'─' * 48}\n"
            f"Папка: {client.root}\n"
            f"System: {client.system_dir}\n"
            f"Исполняемый файл: {client.executable}\n"
            f"Конфигурация: {config}\n"
            f"Формат конфигурации: {client.config_format}\n\n"
        )
        if client.config_format == "plain_ini":
            details += "Обычный INI: доступно безопасное изменение ServerAddr в [URL]."
        elif client.config_format == "encrypted_candidate":
            details += (
                "Возможна зашифрованная конфигурация протокола 413. "
                "Перед изменением будет создана резервная копия и выполнена проверка."
            )
        elif client.config_format == "missing":
            details += "Конфигурация не найдена. Настройка подключения недоступна."
        else:
            details += (
                "Формат неизвестен или файл недоступен. "
                "Изменение запрещено, пока формат не будет проверен."
            )
        self._show_result(details)
        self._set_actions(True)
        self.patch_button.configure(
            state="normal" if client.config is not None and
            client.config_format in ("plain_ini", "encrypted_candidate")
            else "disabled"
        )
        self.status.set("Клиент выбран. Перед изменениями будет создана резервная копия.")

    def make_backup(self):
        client = self.selected_client
        if client is None:
            messagebox.showinfo(APP_TITLE, "Сначала выберите клиент.")
            return
        files = [client.executable]
        if client.config and client.config.is_file():
            files.append(client.config)
        try:
            archive = create_backup(files, client.root / "patcher_backups")
        except Exception as exc:
            messagebox.showerror(APP_TITLE, f"Резервная копия не создана:\n{exc}")
            self.status.set("Ошибка резервного копирования.")
            return
        self.status.set(f"Резервная копия создана: {archive}")
        messagebox.showinfo(APP_TITLE, f"Резервная копия проверена:\n{archive}")

    def patch_config(self):
        client = self.selected_client
        if client is None or client.config is None:
            messagebox.showinfo(APP_TITLE, "Выберите клиент с конфигурацией.")
            return
        address = self.server_address.get().strip()
        if client.config_format not in ("plain_ini", "encrypted_candidate"):
            messagebox.showwarning(
                APP_TITLE, "Формат не распознан. Файл не изменён."
            )
            return
        if not messagebox.askyesno(
            APP_TITLE,
            f"Выбран клиент:\n{client.root}\n\n"
            f"Изменить ServerAddr на:\n{address}\n\n"
            "Перед изменением будет создана резервная копия."
        ):
            return
        try:
            backup_dir = client.root / "patcher_backups"
            if client.config_format == "plain_ini":
                result = patch_plain_ini(client.config, address, backup_dir)
                details = str(result)
            else:
                encoder = _find_l2encdec()
                result, backup = patch_encrypted_config(
                    client.config, address, encoder=encoder,
                    decoder=encoder, backup_dir=backup_dir
                )
                details = (
                    f"{result}\n" +
                    (f"Резервная копия: {backup}" if backup
                     else "Адрес уже установлен; изменений нет.")
                )
        except Exception as exc:
            messagebox.showerror(
                APP_TITLE, f"Изменение отменено или не завершено:\n{exc}"
            )
            self.status.set("Настройка не завершена. Проверьте сообщение об ошибке.")
            return
        self.status.set(f"Конфигурация обработана: {result}")
        messagebox.showinfo(APP_TITLE, f"Готово:\n{details}")

def main():
    app = PatcherApp()
    app.mainloop()

if __name__ == "__main__":
    main()
