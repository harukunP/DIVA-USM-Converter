"""Create review screenshots of the real Tk widgets on an active X display.

This never runs a conversion. The file-picker result and progress messages are
fixtures; it exercises the callbacks and visible states without touching PVs.
Requires Pillow only for screenshots (already listed in requirements-assets).
"""
from __future__ import annotations

import argparse
import sys
import tempfile
import tkinter as tk
from pathlib import Path
from tkinter import ttk
from unittest.mock import patch

from PIL import ImageGrab

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from diva_usm_converter.gui import DivaApp
from diva_usm_converter.i18n import LANGUAGES, SettingsStore


def descendants(widget):
    for child in widget.winfo_children():
        yield child
        yield from descendants(child)


def select_menu_language(root, app, code: str) -> None:
    main = root.nametowidget(root.cget("menu"))
    settings = next(root.nametowidget(main.entrycget(i, "menu"))
                    for i in range(main.index("end") + 1)
                    if main.type(i) == "cascade" and
                    main.entrycget(i, "label") == app.tr("menu.settings"))
    languages = next(root.nametowidget(settings.entrycget(i, "menu"))
                     for i in range(settings.index("end") + 1)
                     if settings.type(i) == "cascade" and
                     settings.entrycget(i, "label") == app.tr("menu.language"))
    index = next(i for i in range(languages.index("end") + 1)
                 if languages.type(i) == "radiobutton" and languages.entrycget(i, "value") == code)
    languages.invoke(index)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=Path("test_output/gui-visual-check"))
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    temporary = tempfile.TemporaryDirectory(prefix="DIVA visual fixture ")
    temp_root = Path(temporary.name)
    settings = SettingsStore(temp_root / "settings.json")
    root = tk.Tk()
    root.attributes("-topmost", True)
    attempt = {"count": 0}

    def choose_first_language() -> None:
        attempt["count"] += 1
        dialogs = [item for item in root.winfo_children() if isinstance(item, tk.Toplevel)]
        if dialogs:
            dialog = dialogs[0]
            dialog.attributes("-topmost", True)
            items = list(descendants(dialog))
            combo = next(item for item in items if isinstance(item, ttk.Combobox))
            buttons = [item for item in items if isinstance(item, ttk.Button)]
            ImageGrab.grab().save(args.output / "01-first-language.png")
            combo.set(LANGUAGES["pt-BR"])
            buttons[-1].invoke()
        elif attempt["count"] < 30:
            root.after(100, choose_first_language)

    root.after(100, choose_first_language)
    with patch("diva_usm_converter.gui.SettingsStore", return_value=settings):
        app = DivaApp(root)
        root.update()
        ImageGrab.grab().save(args.output / "02-main-pt-BR.png")

        select_menu_language(root, app, "es")
        root.update()
        ImageGrab.grab().save(args.output / "03-settings-language-es.png")

        source = temp_root / "Entrada com espaço" / "Vídeo São João.usm"
        source.parent.mkdir(parents=True)
        source.write_bytes(b"UI-only fixture; not a valid USM")
        choose_files = next(item for item in descendants(root)
                            if isinstance(item, ttk.Button) and
                            item.cget("text") == app.tr("input.files"))
        with patch("diva_usm_converter.gui.filedialog.askopenfilenames",
                   return_value=(str(source),)):
            choose_files.invoke()
        root.update()
        source_id = str(source.resolve())
        app.events.put({"source": source_id, "file": source.name, "file_count": 1,
                        "file_index": 1, "completed": 0, "status": "converting",
                        "file_percent": 42, "remaining_seconds": 30,
                        "estimated_total_seconds": 40})
        app._poll_events()
        root.update()
        ImageGrab.grab().save(args.output / "04-file-selection-progress.png")
        app.events.put({"source": source_id, "file": source.name, "file_count": 1,
                        "file_index": 1, "completed": 1, "status": "success",
                        "file_percent": 100, "remaining_seconds": 0,
                        "estimated_total_seconds": 40})
        app._poll_events()
        root.update()
        ImageGrab.grab().save(args.output / "05-completion-log.png")
        root.destroy()
    temporary.cleanup()
    print(f"Screenshots saved in {args.output.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
