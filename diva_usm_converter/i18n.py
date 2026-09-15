"""Localization and per-user settings, independent of the GUI toolkit."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path


LANGUAGES = {
    "pt-BR": "Português (Brasil)",
    "es": "Español",
    "en": "English",
    "fr": "Français",
}
DEFAULT_LANGUAGE = "en"


def resource_path(*parts: str) -> Path:
    """Resolve bundled resources in source runs and PyInstaller bundles."""
    root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
    return root.joinpath(*parts)


def user_data_dir() -> Path:
    """Return a writable per-user data/config directory on Windows and Termux."""
    if sys.platform == "win32":
        base = os.environ.get("APPDATA") or os.environ.get("LOCALAPPDATA")
        return (Path(base) if base else Path.home() / "AppData" / "Roaming") / "DIVA USM Converter"
    if os.environ.get("PREFIX", "").endswith("/com.termux/files/usr"):
        base = os.environ.get("XDG_CONFIG_HOME")
        return (Path(base) if base else Path.home() / ".config") / "DIVA USM Converter"
    base = os.environ.get("XDG_CONFIG_HOME")
    return (Path(base) if base else Path.home() / ".config") / "DIVA USM Converter"


class SettingsStore:
    def __init__(self, path: Path | None = None):
        self.path = path or user_data_dir() / "settings.json"

    def load(self) -> dict:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, UnicodeError):
            return {}
        return data if isinstance(data, dict) else {}

    def save(self, settings: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp = self.path.with_name(self.path.name + ".tmp")
        temp.write_text(json.dumps(settings, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        os.replace(temp, self.path)


class Translator:
    def __init__(self, language: str = DEFAULT_LANGUAGE, locale_dir: Path | None = None):
        self.locale_dir = locale_dir or resource_path("locales")
        self.language = language if language in LANGUAGES else DEFAULT_LANGUAGE
        self._catalogs: dict[str, dict] = {}

    def _load(self, language: str) -> dict:
        if language not in self._catalogs:
            path = self.locale_dir / f"{language}.json"
            try:
                catalog = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError, UnicodeError):
                catalog = {}
            self._catalogs[language] = catalog if isinstance(catalog, dict) else {}
        return self._catalogs[language]

    def set_language(self, language: str) -> None:
        self.language = language if language in LANGUAGES else DEFAULT_LANGUAGE

    def text(self, key: str, **values) -> str:
        fallback = self._load(DEFAULT_LANGUAGE).get(key, key)
        value = self._load(self.language).get(key, fallback)
        try:
            return value.format(**values)
        except (KeyError, ValueError):
            return value
