"""Localized native Tk interface focused on USM to silent H.264 MP4 conversion."""
from __future__ import annotations

import hashlib
import logging
import os
import queue
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from .core import ConverterError, run_batch
from .i18n import LANGUAGES, SettingsStore, Translator, resource_path, user_data_dir


def format_eta(seconds: float | None, translator: Translator) -> str:
    if seconds is None:
        return translator.text("eta.unknown")
    seconds = max(0, int(seconds))
    hours, remainder = divmod(seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    return f"{hours:d}:{minutes:02d}:{seconds:02d}" if hours else f"{minutes:d}:{seconds:02d}"


class DivaApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.settings = SettingsStore()
        self.preferences = self.settings.load()
        self._logger = self._make_logger()
        self.translator = Translator(self.preferences.get("language", "en"))
        self.sources: list[Path] = []
        self.file_states: dict[str, tuple[str, str]] = {}
        self.events: queue.Queue = queue.Queue()
        self.running = False
        self.cancel_event: threading.Event | None = None
        self.close_after_cancel = False
        self.logo_image = None
        self.profile_codes: dict[str, str] = {}
        self.window_icon = None
        self.root.protocol("WM_DELETE_WINDOW", self._close)
        if "language" not in self.preferences or self.preferences.get("language") not in LANGUAGES:
            self._first_language_dialog()
        self._render()
        self.root.after(100, self._poll_events)

    def tr(self, key: str, **values) -> str:
        return self.translator.text(key, **values)

    def _make_logger(self) -> logging.Logger:
        logger = logging.getLogger("diva_usm_converter.ui")
        if not logger.handlers:
            log_dir = user_data_dir() / "logs"
            log_dir.mkdir(parents=True, exist_ok=True)
            handler = logging.FileHandler(log_dir / "application.log", encoding="utf-8")
            handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
            logger.addHandler(handler)
            logger.setLevel(logging.INFO)
        return logger

    def _first_language_dialog(self) -> None:
        dialog = tk.Toplevel(self.root)
        dialog.title("DIVA USM Converter")
        dialog.resizable(False, False)
        dialog.transient(self.root)
        dialog.grab_set()
        frame = ttk.Frame(dialog, padding=22)
        frame.pack(fill="both", expand=True)
        ttk.Label(frame, text="DIVA USM Converter", font=("TkDefaultFont", 15, "bold")).pack(anchor="w")
        ttk.Label(frame, text="Choose a language / Selecione o idioma / Seleccione el idioma / Choisissez la langue").pack(anchor="w", pady=(12, 8))
        names = list(LANGUAGES.values())
        language_by_name = {name: code for code, name in LANGUAGES.items()}
        selected = tk.StringVar(value=LANGUAGES["en"])
        ttk.Combobox(frame, textvariable=selected, state="readonly", values=names, width=30).pack(fill="x")

        def choose() -> None:
            self.translator.set_language(language_by_name[selected.get()])
            dialog.destroy()

        ttk.Button(frame, text="Continue / Continuar / Continuer", command=choose).pack(anchor="e", pady=(14, 0))
        dialog.protocol("WM_DELETE_WINDOW", choose)
        self.root.wait_window(dialog)
        self.preferences["language"] = self.translator.language
        self.settings.save(self.preferences)

    def _set_language(self, language: str, persist: bool = True) -> None:
        self.translator.set_language(language)
        self.preferences["language"] = self.translator.language
        if persist:
            self.settings.save(self.preferences)
        self._render()

    def _render(self) -> None:
        for child in self.root.winfo_children():
            child.destroy()
        self.root.title(self.tr("app.title"))
        self.root.geometry("1040x700")
        self.root.minsize(800, 540)
        try:
            self.root.iconbitmap(str(resource_path("assets", "diva-icon.ico")))
        except tk.TclError:
            try:
                self.window_icon = tk.PhotoImage(file=str(resource_path("assets", "diva-icon.png"))).subsample(4, 4)
                self.root.iconphoto(True, self.window_icon)
            except tk.TclError:
                self.window_icon = None
        self._build_menu()
        self._build_main()
        self._refresh_files()

    def _build_menu(self) -> None:
        menu = tk.Menu(self.root)
        file_menu = tk.Menu(menu, tearoff=False)
        file_menu.add_command(label=self.tr("menu.quit"), command=self._close)
        menu.add_cascade(label=self.tr("menu.file"), menu=file_menu)
        settings_menu = tk.Menu(menu, tearoff=False)
        lang_menu = tk.Menu(settings_menu, tearoff=False)
        self.language_var = tk.StringVar(value=self.translator.language)
        for code, native_name in LANGUAGES.items():
            lang_menu.add_radiobutton(label=native_name, value=code,
                                      variable=self.language_var,
                                      command=lambda item=code: self._set_language(item))
        settings_menu.add_cascade(label=self.tr("menu.language"), menu=lang_menu)
        menu.add_cascade(label=self.tr("menu.settings"), menu=settings_menu)
        help_menu = tk.Menu(menu, tearoff=False)
        help_menu.add_command(label=self.tr("menu.about"), command=self._about)
        help_menu.add_command(label=self.tr("menu.dependencies"), command=lambda: messagebox.showinfo(
            self.tr("menu.dependencies"), self.tr("dialog.dependencies"), parent=self.root))
        menu.add_cascade(label=self.tr("menu.help"), menu=help_menu)
        self.root.config(menu=menu)

    def _build_main(self) -> None:
        frame = ttk.Frame(self.root, padding=14)
        frame.pack(fill="both", expand=True)
        header = ttk.Frame(frame)
        header.pack(fill="x", pady=(0, 14))
        try:
            self.logo_image = tk.PhotoImage(file=str(resource_path("assets", "diva-logo.png"))).subsample(12, 12)
            ttk.Label(header, image=self.logo_image).pack(side="left", padx=(0, 12))
        except tk.TclError:
            self.logo_image = None
        titles = ttk.Frame(header)
        titles.pack(side="left", fill="x", expand=True)
        ttk.Label(titles, text=self.tr("header.title"), font=("TkDefaultFont", 19, "bold")).pack(anchor="w")
        ttk.Label(titles, text=self.tr("header.subtitle"), wraplength=820).pack(anchor="w", pady=(4, 0))

        paths = ttk.Frame(frame)
        paths.pack(fill="x", pady=5)
        self.input_var = tk.StringVar()
        self.output_var = tk.StringVar(value=self.preferences.get("output_folder", ""))
        ttk.Label(paths, text=self.tr("input.label"), width=22).grid(row=0, column=0, sticky="w", pady=5)
        ttk.Entry(paths, textvariable=self.input_var).grid(row=0, column=1, sticky="ew", padx=6)
        ttk.Button(paths, text=self.tr("input.folder"), command=self._choose_input_folder).grid(row=0, column=2, padx=3)
        ttk.Button(paths, text=self.tr("input.files"), command=self._choose_files).grid(row=0, column=3, padx=3)
        ttk.Label(paths, text=self.tr("output.label"), width=22).grid(row=1, column=0, sticky="w", pady=5)
        ttk.Entry(paths, textvariable=self.output_var).grid(row=1, column=1, sticky="ew", padx=6)
        ttk.Button(paths, text=self.tr("output.choose"), command=self._choose_output).grid(row=1, column=2, columnspan=2, sticky="ew", padx=3)
        paths.columnconfigure(1, weight=1)

        options = ttk.Frame(frame)
        options.pack(fill="x", pady=(7, 3))
        ttk.Label(options, text=self.tr("profile.label")).pack(side="left")
        self.profile_codes = {
            self.tr("profile.balanced"): "balanced",
            self.tr("profile.quality"): "quality",
            self.tr("profile.size"): "size",
        }
        saved_profile = self.preferences.get("profile", "balanced")
        display_profile = next((label for label, code in self.profile_codes.items() if code == saved_profile),
                               self.tr("profile.balanced"))
        self.profile_var = tk.StringVar(value=display_profile)
        ttk.Combobox(options, textvariable=self.profile_var, state="readonly", width=36,
                     values=list(self.profile_codes)).pack(side="left", padx=8)
        ttk.Label(frame, text=self.tr("profile.help"), wraplength=950,
                  justify="left").pack(anchor="w", fill="x", pady=(1, 3))

        ttk.Label(frame, text=self.tr("files.heading"), font=("TkDefaultFont", 11, "bold")).pack(anchor="w", pady=(8, 4))
        tools = ttk.Frame(frame)
        tools.pack(fill="x", pady=(0, 4))
        ttk.Button(tools, text=self.tr("input.remove"), command=self._remove_selected).pack(side="left")
        ttk.Button(tools, text=self.tr("input.clear"), command=self._clear_files).pack(side="left", padx=6)
        self.file_tree = ttk.Treeview(frame, columns=("file", "status", "progress"), show="headings", height=11)
        self.file_tree.heading("file", text=self.tr("column.file"))
        self.file_tree.heading("status", text=self.tr("column.status"))
        self.file_tree.heading("progress", text=self.tr("column.progress"))
        self.file_tree.column("file", width=530, anchor="w")
        self.file_tree.column("status", width=235, anchor="w")
        self.file_tree.column("progress", width=100, anchor="e")
        self.file_tree.pack(fill="both", expand=True)
        footer = ttk.Frame(frame)
        footer.pack(fill="x", pady=(8, 0))
        self.eta_var = tk.StringVar(value=self.tr("eta.remaining", time=self.tr("eta.unknown")))
        self.total_eta_var = tk.StringVar(value=self.tr("eta.total", time=self.tr("eta.unknown")))
        ttk.Label(footer, textvariable=self.eta_var).pack(side="right", padx=8)
        ttk.Label(footer, textvariable=self.total_eta_var).pack(side="right", padx=8)
        self.start_button = ttk.Button(footer, text=self.tr("button.start"), command=self._start_batch)
        self.start_button.pack(side="left")
        self.cancel_button = ttk.Button(footer, text=self.tr("button.cancel"), command=self._request_cancel, state="disabled")
        self.cancel_button.pack(side="left", padx=7)
        self.total_progress = ttk.Progressbar(frame, mode="determinate", maximum=100)
        self.total_progress.pack(fill="x", pady=(8, 3))
        self.status_var = tk.StringVar(value=self.tr("status.ready"))
        ttk.Label(frame, textvariable=self.status_var, wraplength=970).pack(anchor="w", pady=3)
        ttk.Label(frame, text=self.tr("log.title"), font=("TkDefaultFont", 10, "bold")).pack(anchor="w", pady=(5, 2))
        self.log_text = tk.Text(frame, height=6, wrap="word", state="disabled")
        self.log_text.pack(fill="both", expand=False)

    def _about(self) -> None:
        messagebox.showinfo(self.tr("about.title"), self.tr("about.body"), parent=self.root)

    def _choose_input_folder(self) -> None:
        selected = filedialog.askdirectory(title=self.tr("dialog.input_folder"))
        if not selected:
            return
        self.input_var.set(selected)
        self._add_sources(sorted(Path(selected).iterdir()))

    def _choose_files(self) -> None:
        selected = filedialog.askopenfilenames(
            title=self.tr("dialog.input_files"),
            filetypes=((self.tr("dialog.usm_files"), "*.usm"),))
        if selected:
            self._add_sources(Path(item) for item in selected)

    def _choose_output(self) -> None:
        selected = filedialog.askdirectory(title=self.tr("dialog.output_folder"))
        if selected:
            self.output_var.set(selected)
            self.preferences["output_folder"] = selected
            self.settings.save(self.preferences)

    def _add_sources(self, paths) -> None:
        existing = {path.resolve() for path in self.sources}
        for raw in paths:
            path = Path(raw)
            if path.is_file() and path.suffix.lower() == ".usm":
                resolved = path.resolve()
                if resolved not in existing:
                    self.sources.append(resolved)
                    existing.add(resolved)
        self._refresh_files()

    def _refresh_files(self) -> None:
        if not hasattr(self, "file_tree"):
            return
        self.file_tree.delete(*self.file_tree.get_children())
        for path in self.sources:
            state, percent = self.file_states.get(str(path), ("pending", "0%"))
            self.file_tree.insert("", "end", iid=str(path),
                                  values=(path.name, self.tr(f"state.{state}"), percent))
        if hasattr(self, "status_var"):
            self.status_var.set(self.tr("status.files_added", count=len(self.sources)) if self.sources
                                else self.tr("status.ready"))

    def _remove_selected(self) -> None:
        selected = set(self.file_tree.selection())
        self.sources = [path for path in self.sources if str(path) not in selected]
        self._refresh_files()

    def _clear_files(self) -> None:
        if self.running:
            return
        self.sources.clear()
        self._refresh_files()

    def _start_batch(self) -> None:
        if self.running:
            return
        if not self.sources:
            messagebox.showerror(self.tr("dialog.error.title"), self.tr("status.need_input"), parent=self.root)
            return
        output = Path(self.output_var.get()).expanduser()
        if not self.output_var.get().strip():
            messagebox.showerror(self.tr("dialog.error.title"), self.tr("status.need_output"), parent=self.root)
            return
        try:
            output.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            messagebox.showerror(self.tr("dialog.error.title"), self._friendly_error(exc), parent=self.root)
            return
        profile = self.profile_codes.get(self.profile_var.get(), "balanced")
        self.preferences.update({"profile": profile, "output_folder": str(output)})
        self.settings.save(self.preferences)
        self.running = True
        self.cancel_event = threading.Event()
        self.start_button.configure(state="disabled")
        self.cancel_button.configure(state="normal")
        self.status_var.set(self.tr("status.batch_running"))
        state_path = output / ".diva-usm-state.json"

        def worker() -> None:
            try:
                result = run_batch(self.sources[:], output, profile, state_path,
                                   progress=self.events.put, cancel_event=self.cancel_event)
                self.events.put({"event": "finished", "result": result})
            except Exception as exc:
                self.events.put({"event": "fatal", "error": str(exc)})

        threading.Thread(target=worker, name="DIVA-conversion", daemon=True).start()

    def _friendly_error(self, error: object) -> str:
        raw = str(error)
        if raw == "DIVA_CANCELLED":
            return self.tr("dialog.error.cancelled")
        if "FFmpeg não inicia" in raw or "ffmpeg.exe" in raw.lower() and "not found" in raw.lower():
            return self.tr("dialog.error.ffmpeg")
        if "WannaCRI não encontrado" in raw or "wannacri" in raw.lower() and "missing" in raw.lower():
            return self.tr("dialog.error.wannacri")
        if "encoder libx264 não disponível" in raw:
            return self.tr("dialog.error.encoder")
        if "nenhum arquivo USM" in raw:
            return self.tr("dialog.error.no_files")
        if "destino já existe" in raw:
            detail = raw.partition(": ")[2] or raw
            return self.tr("dialog.error.output_exists", detail=detail)
        return self.tr("dialog.error.generic", detail=raw)

    def _append_log(self, message: str, level: str = "info") -> None:
        self._logger.error(message) if level == "error" else self._logger.info(message)
        if hasattr(self, "log_text"):
            self.log_text.configure(state="normal")
            self.log_text.insert("end", message + "\n")
            self.log_text.see("end")
            self.log_text.configure(state="disabled")

    def _poll_events(self) -> None:
        try:
            while True:
                event = self.events.get_nowait()
                if "event" in event:
                    self._finish_worker(event)
                    continue
                iid = event.get("source", "")
                if iid not in self.file_tree.get_children():
                    iid = next((item for item in self.file_tree.get_children()
                                if Path(item).name == event.get("file")), "")
                state_key = event.get("status", "error")
                if iid:
                    self.file_states[iid] = (state_key, f"{event.get('file_percent', 0):.0f}%")
                    self.file_tree.set(iid, "status", self.tr(f"state.{state_key}"))
                    self.file_tree.set(iid, "progress", f"{event.get('file_percent', 0):.0f}%")
                count = event.get("file_count", len(self.sources))
                if count:
                    overall = event.get("completed", 0) / count * 100
                    if state_key == "converting":
                        overall = ((event.get("file_index", 1) - 1 + event.get("file_percent", 0) / 100)
                                   / count * 100)
                    self.total_progress.configure(value=min(100, overall))
                self.eta_var.set(self.tr("eta.remaining", time=format_eta(event.get("remaining_seconds"), self.translator)))
                self.total_eta_var.set(self.tr("eta.total", time=format_eta(event.get("estimated_total_seconds"), self.translator)))
                if state_key in {"extracting", "success", "skipped_validated", "error", "cancelled"}:
                    message = f"{Path(iid).name if iid else event.get('file', '')}: {self.tr(f'state.{state_key}')}"
                    if event.get("error"):
                        message += " — " + self._friendly_error(event["error"])
                    self._append_log(message, "error" if state_key == "error" else "info")
        except queue.Empty:
            pass
        if self.root.winfo_exists():
            self.root.after(100, self._poll_events)

    def _finish_worker(self, event: dict) -> None:
        result = event.get("result")
        if result:
            report = Path(result["output_dir"]) / "conversion-report.json"
            self.status_var.set(self.tr("status.batch_complete", successes=result["successes"],
                                        failures=result["failures"], report=report))
            self.total_progress.configure(value=100 if not result.get("cancelled") else
                                          result["completed"] / max(1, result["total"]) * 100)
            self._append_log(self.status_var.get())
            if result.get("failures"):
                messagebox.showwarning(self.tr("report.title"),
                                       self.tr("report.body", successes=result["successes"],
                                               failures=result["failures"], report=report), parent=self.root)
        else:
            error = event.get("error", "")
            friendly = self._friendly_error(error)
            self.status_var.set(friendly)
            self._append_log(friendly, "error")
            messagebox.showerror(self.tr("dialog.error.title"), friendly, parent=self.root)
        self.running = False
        self.cancel_event = None
        self.start_button.configure(state="normal")
        self.cancel_button.configure(state="disabled")
        self.preferences["output_folder"] = self.output_var.get()
        self.settings.save(self.preferences)
        if self.close_after_cancel:
            self.root.destroy()
        else:
            self._refresh_files()

    def _request_cancel(self) -> None:
        if not self.running or not self.cancel_event:
            return
        if messagebox.askyesno(self.tr("dialog.confirm_cancel_batch.title"),
                               self.tr("dialog.confirm_cancel_batch.body"), parent=self.root):
            self.cancel_event.set()
            self.cancel_button.configure(state="disabled")
            self.status_var.set(self.tr("status.cancel_requested"))

    def _close(self) -> None:
        if self.running:
            if not messagebox.askyesno(self.tr("dialog.confirm_cancel.title"),
                                       self.tr("dialog.confirm_cancel.body"), parent=self.root):
                return
            self.close_after_cancel = True
            if self.cancel_event:
                self.cancel_event.set()
            return
        self.root.destroy()


def launch() -> int:
    try:
        root = tk.Tk()
    except tk.TclError as exc:
        raise ConverterError("Tk could not start; verify that Tk and an active graphical display are installed") from exc
    DivaApp(root)
    root.mainloop()
    return 0
