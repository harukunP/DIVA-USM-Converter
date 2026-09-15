from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .core import ConverterError, apply_pvdb, diagnostics, extract_usm_file, inspect_usm, pvdb_plan, run_batch, walk_usm_chunks


def main(argv: list[str] | None = None) -> int:
    if argv is None:
        argv = sys.argv[1:]
    if not argv:
        argv = ["gui"]
    if argv == ["--self-test"]:
        result = diagnostics()
        tools = {tool["name"]: tool for tool in result["tools"]}
        failures = []
        for name in ("ffmpeg", "ffprobe", "wannacri"):
            if not tools[name]["usable"]:
                failures.append(f"{name}: {tools[name]['error'] or 'unavailable'}")
        if "libx264" not in result["available_encoders"]:
            failures.append("FFmpeg encoder libx264 unavailable")
        try:
            import tkinter  # noqa: F401
            from .i18n import LANGUAGES, Translator
            for language in LANGUAGES:
                if not Translator(language).text("app.title"):
                    failures.append(f"translation unavailable: {language}")
        except ImportError as exc:
            failures.append(f"Tkinter unavailable: {exc}")
        print(json.dumps({"ok": not failures, "diagnostics": result, "failures": failures},
                         ensure_ascii=False, indent=2))
        return 0 if not failures else 2
    if argv == ["--gui-smoke-test"]:
        import tempfile
        import tkinter as tk
        from tkinter import ttk
        from unittest.mock import patch
        from .gui import DivaApp
        from .i18n import LANGUAGES, SettingsStore
        try:
            with tempfile.TemporaryDirectory(prefix="diva-gui-smoke-") as folder:
                settings = SettingsStore(Path(folder) / "settings.json")
                selection_attempts = {"count": 0}

                def choose_first_language(root):
                    selection_attempts["count"] += 1
                    def descendants(widget):
                        for child in widget.winfo_children():
                            yield child
                            yield from descendants(child)
                    dialogs = [child for child in root.winfo_children() if isinstance(child, tk.Toplevel)]
                    if dialogs:
                        widgets = list(descendants(dialogs[0]))
                        combo = next((item for item in widgets if isinstance(item, ttk.Combobox)), None)
                        buttons = [item for item in widgets if isinstance(item, ttk.Button)]
                        if combo and buttons:
                            combo.set(LANGUAGES["fr"])
                            buttons[-1].invoke()
                            return
                    if selection_attempts["count"] < 30:
                        root.after(100, choose_first_language, root)

                def invoke_language_menu(root, app, language):
                    main = root.nametowidget(root.cget("menu"))
                    settings_menu = None
                    for index in range(main.index("end") + 1):
                        if main.type(index) == "cascade" and main.entrycget(index, "label") == app.tr("menu.settings"):
                            settings_menu = root.nametowidget(main.entrycget(index, "menu"))
                            break
                    if settings_menu is None:
                        raise ConverterError("GUI smoke test failed: settings menu missing")
                    language_menu = None
                    for index in range(settings_menu.index("end") + 1):
                        if (settings_menu.type(index) == "cascade" and
                                settings_menu.entrycget(index, "label") == app.tr("menu.language")):
                            language_menu = root.nametowidget(settings_menu.entrycget(index, "menu"))
                            break
                    if language_menu is None:
                        raise ConverterError("GUI smoke test failed: language menu missing")
                    for index in range(language_menu.index("end") + 1):
                        if language_menu.type(index) == "radiobutton" and language_menu.entrycget(index, "value") == language:
                            language_menu.invoke(index)
                            return
                    raise ConverterError(f"GUI smoke test failed: language menu entry missing: {language}")

                def descendants(widget):
                    for child in widget.winfo_children():
                        yield child
                        yield from descendants(child)

                root = tk.Tk()
                root.after(100, choose_first_language, root)
                with patch("diva_usm_converter.gui.SettingsStore", return_value=settings):
                    app = DivaApp(root)
                    root.update()
                    if app.translator.language != "fr" or settings.load().get("language") != "fr":
                        raise ConverterError("GUI smoke test failed: first-launch language selection/persistence")
                    invoke_language_menu(root, app, "pt-BR")
                    root.update()
                    if not any("Equilibrado" in label for label in app.profile_codes):
                        raise ConverterError("GUI smoke test failed: language change did not rebuild controls")
                    sample = Path(folder) / "Entrada São João" / "PV teste.usm"
                    sample.parent.mkdir()
                    sample.write_bytes(b"UI selection fixture")
                    file_button = next((item for item in descendants(root)
                                        if isinstance(item, ttk.Button) and
                                        item.cget("text") == app.tr("input.files")), None)
                    if file_button is None:
                        raise ConverterError("GUI smoke test failed: file selection button missing")
                    with patch("diva_usm_converter.gui.filedialog.askopenfilenames",
                               return_value=(str(sample),)):
                        file_button.invoke()
                    root.update()
                    if len(app.file_tree.get_children()) != 1:
                        raise ConverterError("GUI smoke test failed: selected USM was not listed")
                    app.events.put({"source": str(sample.resolve()), "file": sample.name,
                                    "file_count": 1, "file_index": 1, "completed": 0,
                                    "status": "converting", "file_percent": 42,
                                    "remaining_seconds": 30, "estimated_total_seconds": 40})
                    app._poll_events()
                    if app.file_tree.set(str(sample.resolve()), "progress") != "42%":
                        raise ConverterError("GUI smoke test failed: per-file progress display")
                    app.events.put({"source": str(sample.resolve()), "file": sample.name,
                                    "file_count": 1, "file_index": 1, "completed": 1,
                                    "status": "success", "file_percent": 100,
                                    "remaining_seconds": 0, "estimated_total_seconds": 40})
                    app._poll_events()
                    root.update()
                    log = app.log_text.get("1.0", "end")
                    if "PV teste.usm" not in log or "100%" not in app.file_tree.set(
                            str(sample.resolve()), "progress"):
                        raise ConverterError("GUI smoke test failed: completion status/log")
                    notebooks = [widget for widget in root.winfo_children()
                                 if isinstance(widget, ttk.Notebook)]
                    if notebooks:
                        raise ConverterError("GUI smoke test failed: obsolete PVDB/hex tabs still present")
                    root.destroy()
        except (tk.TclError, ConverterError) as exc:
            print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False))
            return 2
        print(json.dumps({"ok": True, "window": "Tk", "first_language": "fr",
                          "language_persistence": True, "unicode_file_selection": True,
                          "progress_and_log": True, "pvdb_hex_tabs": "absent"}))
        return 0
    parser = argparse.ArgumentParser(prog="diva-usm", description="Preparação segura de vídeos USM para Project DIVA")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("diagnose", help="verifica executáveis e encoders realmente disponíveis")
    inspect = sub.add_parser("inspect", help="inspeciona assinatura e marcadores USM sem assumir codec")
    inspect.add_argument("file", type=Path)
    extract = sub.add_parser("extract", help="demultiplexa USM VP9 com WannaCRI sem alterar a origem")
    extract.add_argument("file", type=Path)
    extract.add_argument("output_dir", type=Path)
    extract.add_argument("--key", type=lambda value: int(value, 0), help="chave CRI em decimal ou 0xHEX")
    batch = sub.add_parser("batch", help="converte USM em lote (requer demux CRI e FFmpeg funcionais)")
    batch.add_argument("input_dir", type=Path)
    batch.add_argument("output_dir", type=Path)
    batch.add_argument("--profile", choices=("quality", "balanced", "size"), default="balanced")
    batch.add_argument("--state", type=Path, default=Path(".diva-usm-state.json"))
    pvdb = sub.add_parser("pvdb", help="prévia de mudanças no PVDB; --apply grava com backup")
    pvdb.add_argument("file", type=Path)
    pvdb.add_argument("--output-dir", type=Path, required=True)
    pvdb.add_argument("--apply", action="store_true", help="grava somente quando todos os MP4 existem")
    sub.add_parser("gui", help="abre a interface gráfica nativa (Tk)")
    args = parser.parse_args(argv)
    try:
        if args.command == "diagnose":
            print(json.dumps(diagnostics(), ensure_ascii=False, indent=2))
        elif args.command == "inspect":
            result = inspect_usm(args.file)
            try:
                result["chunks"] = walk_usm_chunks(args.file)
                result["chunk_walk_valid"] = True
            except ConverterError as exc:
                result["chunk_walk_valid"] = False
                result["chunk_walk_error"] = str(exc)
            print(json.dumps(result, ensure_ascii=False, indent=2))
        elif args.command == "extract":
            print(json.dumps(extract_usm_file(args.file, args.output_dir, args.key),
                             ensure_ascii=False, indent=2))
        elif args.command == "pvdb":
            content, report, encoding = pvdb_plan(args.file, args.output_dir)
            print(json.dumps({"pvdb": str(args.file), "changes": report,
                              "all_destinations_exist": bool(report) and all(x["exists"] for x in report),
                              "applied": False}, ensure_ascii=False, indent=2))
            if args.apply:
                if not report or not all(x["exists"] for x in report):
                    raise ConverterError("PVDB não alterado: todos os destinos precisam existir")
                backup = apply_pvdb(args.file, content, encoding)
                print(f"PVDB atualizado; backup: {backup}")
        elif args.command == "batch":
            print(json.dumps(run_batch(args.input_dir, args.output_dir, args.profile, args.state), ensure_ascii=False, indent=2))
        elif args.command == "gui":
            try:
                from .gui import launch
            except ImportError as exc:
                raise ConverterError(
                    "Tkinter não está disponível neste Python; instale o suporte Tk e inicie uma sessão gráfica"
                ) from exc
            return launch()
    except (ConverterError, OSError) as exc:
        if getattr(sys, "frozen", False):
            try:
                from tkinter import messagebox
                messagebox.showerror("DIVA USM Converter", str(exc))
            except Exception:
                pass
        else:
            print(f"ERRO: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
