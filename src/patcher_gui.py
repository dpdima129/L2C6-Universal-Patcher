from __future__ import annotations

import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from pathlib import Path

from client_scanner import discover_clients
from backup_manager import create_backup
from config_patcher import patch_plain_ini

APP_TITLE = "L2C6 Universal Patcher"
DEFAULT_SERVER = "ujuko1bg.pwrp.cc"


class PatcherApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(APP_TITLE)
        self.geometry("760x520")
        self.minsize(650, 450)

        self.client_path = tk.StringVar()
        self.server_address = tk.StringVar(value=DEFAULT_SERVER)
        self.status = tk.StringVar(value="Выберите папку клиента Lineage 2.")
        self.selected_client = None

        self._build_ui()

    def _build_ui(self):
        outer = ttk.Frame(self, padding=18)
        outer.pack(fill="both", expand=True)

        ttk.Label(
            outer, text="L2C6 Universal Patcher",
            font=("Segoe UI", 19, "bold")
        ).pack(anchor="w")

        ttk.Label(
            outer,
            text="Lineage 2 Interlude C6 • поиск клиента и безопасная настройка",
        ).pack(anchor="w", pady=(2, 16))

        path_frame = ttk.LabelFrame(outer, text="Папка игры", padding=10)
        path_frame.pack(fill="x")

        path_row = ttk.Frame(path_frame)
        path_row.pack(fill="x")
        ttk.Entry(path_row, textvariable=self.client_path).pack(
            side="left", fill="x", expand=True
        )
        ttk.Button(path_row, text="Обзор…", command=self.choose_folder).pack(
            side="left", padx=(8, 0)
        )

        action_row = ttk.Frame(path_frame)
        action_row.pack(fill="x", pady=(10, 0))
        ttk.Button(
            action_row, text="Найти клиент", command=self.scan_client
        ).pack(side="left")
        ttk.Button(
            action_row, text="Создать резервную копию",
            command=self.make_backup
        ).pack(side="left", padx=(8, 0))

        details = ttk.LabelFrame(outer, text="Результат проверки", padding=10)
        details.pack(fill="both", expand=True, pady=12)

        self.result = tk.Text(
            details, height=10, wrap="word",
            state="disabled", font=("Consolas", 10)
        )
        self.result.pack(fill="both", expand=True)

        server_frame = ttk.LabelFrame(
            outer, text="Настройки подключения", padding=10
        )
        server_frame.pack(fill="x")

        ttk.Label(server_frame, text="Адрес сервера:").grid(
            row=0, column=0, sticky="w"
        )
        ttk.Entry(
            server_frame, textvariable=self.server_address, width=36
        ).grid(row=0, column=1, sticky="ew", padx=8)

        ttk.Button(
            server_frame, text="Настроить l2.ini",
            command=self.patch_config
        ).grid(row=0, column=2, sticky="e")

        server_frame.columnconfigure(1, weight=1)

        ttk.Label(
            outer, textvariable=self.status, wraplength=700
        ).pack(fill="x", pady=(12, 0))

    def _show_result(self, text: str):
        self.result.configure(state="normal")
        self.result.delete("1.0", "end")
        self.result.insert("1.0", text)
        self.result.configure(state="disabled")

    def choose_folder(self):
        folder = filedialog.askdirectory(title="Выберите папку Lineage 2")
        if folder:
            self.client_path.set(folder)
            self.scan_client()

    def scan_client(self):
        folder = self.client_path.get().strip()
        if not folder:
            messagebox.showinfo(APP_TITLE, "Сначала выберите папку игры.")
            return

        clients = discover_clients(Path(folder), max_depth=3)
        if not clients:
            self.selected_client = None
            self._show_result(
                "Совместимый клиент не найден.\n\n"
                "Ожидается L2.exe внутри папки system, system2, "
                "system_* или system-*."
            )
            self.status.set("Проверка завершена: клиент не найден.")
            return

        self.selected_client = clients[0]
        lines = []
        for index, client in enumerate(clients, start=1):
            lines.extend([
                f"Клиент #{index}",
                f"Папка: {client.root}",
                f"System: {client.system_dir}",
                f"L2.exe: {client.executable}",
                f"Конфигурация: {client.config or 'не найдена'}",
                f"Формат: {client.config_format}",
                "",
            ])

        self._show_result("\n".join(lines))
        self.status.set(f"Найдено вариантов клиента: {len(clients)}.")

    def make_backup(self):
        client = self.selected_client
        if client is None:
            messagebox.showinfo(APP_TITLE, "Сначала найдите клиент.")
            return

        files = [client.executable]
        if client.config and client.config.is_file():
            files.append(client.config)

        backup_dir = client.root / "patcher_backups"
        try:
            archive = create_backup(files, backup_dir)
        except Exception as exc:
            messagebox.showerror(APP_TITLE, f"Ошибка резервного копирования:\n{exc}")
            return

        self.status.set(f"Резервная копия создана: {archive}")
        messagebox.showinfo(APP_TITLE, f"Резервная копия проверена:\n{archive}")

    def patch_config(self):
        client = self.selected_client
        if client is None or client.config is None:
            messagebox.showinfo(APP_TITLE, "Сначала найдите клиент с конфигурацией.")
            return

        if client.config_format != "plain_ini":
            messagebox.showwarning(
                APP_TITLE,
                "Этот формат пока не поддерживается.\n"
                "Файл не изменён. Зашифрованный Lineage2Ver413 "
                "будет поддержан только после проверки его формата."
            )
            return

        address = self.server_address.get().strip()
        if not messagebox.askyesno(
            APP_TITLE,
            f"Создать резервную копию и изменить ServerAddr на:\n{address}?"
        ):
            return

        try:
            result = patch_plain_ini(
                client.config,
                address,
                client.root / "patcher_backups"
            )
        except Exception as exc:
            messagebox.showerror(APP_TITLE, f"Изменение отменено:\n{exc}")
            return

        self.status.set(f"Конфигурация обработана: {result}")
        messagebox.showinfo(APP_TITLE, f"Готово:\n{result}")


def main():
    app = PatcherApp()
    app.mainloop()


if __name__ == "__main__":
    main()
