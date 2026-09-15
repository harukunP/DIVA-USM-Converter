import json
import tempfile
import unittest
from pathlib import Path

from diva_usm_converter.i18n import LANGUAGES, SettingsStore, Translator, resource_path


class LocalizationTests(unittest.TestCase):
    def test_all_initial_languages_have_complete_catalogues(self):
        base = json.loads((resource_path("locales") / "en.json").read_text(encoding="utf-8"))
        for code in LANGUAGES:
            with self.subTest(language=code):
                catalog = json.loads((resource_path("locales") / f"{code}.json").read_text(encoding="utf-8"))
                self.assertEqual(set(base), set(catalog))
                self.assertTrue(all(isinstance(value, str) and value for value in catalog.values()))

    def test_language_names_and_accented_strings_load(self):
        expectations = {
            "pt-BR": "Equilibrado — mais rápido, boa qualidade",
            "es": "Equilibrado — más rápido, buena calidad",
            "en": "Balanced — quicker, good quality",
            "fr": "Équilibré — rapide, bonne qualité",
        }
        for language, expected in expectations.items():
            with self.subTest(language=language):
                translator = Translator(language)
                self.assertEqual(translator.text("profile.balanced"), expected)
        self.assertEqual(LANGUAGES["pt-BR"], "Português (Brasil)")
        self.assertEqual(LANGUAGES["es"], "Español")
        self.assertEqual(LANGUAGES["fr"], "Français")

    def test_missing_translation_falls_back_to_english(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "en.json").write_text(json.dumps({"known": "English fallback"}), encoding="utf-8")
            (root / "es.json").write_text(json.dumps({"other": "Otro"}), encoding="utf-8")
            self.assertEqual(Translator("es", root).text("known"), "English fallback")

    def test_language_setting_round_trips_in_unicode_path(self):
        with tempfile.TemporaryDirectory(prefix="DIVA réglages ") as folder:
            path = Path(folder) / "preferências" / "settings.json"
            first = SettingsStore(path)
            first.save({"language": "pt-BR", "output_folder": "C:/Vídeos DIVA/saída"})
            second = SettingsStore(path)
            self.assertEqual(second.load(), {"language": "pt-BR", "output_folder": "C:/Vídeos DIVA/saída"})


if __name__ == "__main__":
    unittest.main()
