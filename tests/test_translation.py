from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from subway_blind import translation


class TranslationSystemTests(unittest.TestCase):
    def setUp(self):
        self.temp_directory = tempfile.TemporaryDirectory()
        self.base_path = Path(self.temp_directory.name)
        self.langs_path = self.base_path / "langs"
        self.langs_path.mkdir(parents=True, exist_ok=True)

    def tearDown(self):
        translation.set_language("english")
        self.temp_directory.cleanup()

    def _write_turkish_pack(self) -> None:
        pack_path = self.langs_path / "turkish"
        pack_path.mkdir(parents=True, exist_ok=True)
        (pack_path / "manifest.json").write_text(
            (
                "{\n"
                '  "id": "turkish",\n'
                '  "name": "Türkçe",\n'
                '  "version": "1.0.0",\n'
                '  "author": "Community",\n'
                '  "language_file": "turkish.lng"\n'
                "}\n"
            ),
            encoding="utf-8",
        )
        (pack_path / "turkish.lng").write_text("Start [=] Başla\n", encoding="utf-8")

    def test_available_languages_reads_manifest_based_folders(self):
        self._write_turkish_pack()
        with patch("subway_blind.translation._resource_base_dir", return_value=self.base_path):
            languages = translation.available_languages()
        self.assertEqual(languages, ["english", "turkish"])

    def test_language_display_name_uses_manifest_name(self):
        self._write_turkish_pack()
        with patch("subway_blind.translation._resource_base_dir", return_value=self.base_path):
            display_name = translation.language_display_name("turkish")
        self.assertEqual(display_name, "Türkçe")

    def test_available_language_entries_include_manifest_metadata(self):
        self._write_turkish_pack()
        with patch("subway_blind.translation._resource_base_dir", return_value=self.base_path):
            entries = translation.available_language_entries()
        turkish = next(entry for entry in entries if entry.key == "turkish")
        self.assertEqual(turkish.name, "Türkçe")
        self.assertEqual(turkish.version, "1.0.0")
        self.assertEqual(turkish.author, "Community")

    def test_manifest_with_utf8_bom_is_parsed(self):
        pack_path = self.langs_path / "turkish"
        pack_path.mkdir(parents=True, exist_ok=True)
        (pack_path / "manifest.json").write_text(
            (
                "{\n"
                '  "id": "turkish",\n'
                '  "name": "Türkçe",\n'
                '  "version": "1.1.0",\n'
                '  "author": "vireon-interactive",\n'
                '  "language_file": "turkish.lng"\n'
                "}\n"
            ),
            encoding="utf-8-sig",
        )
        (pack_path / "turkish.lng").write_text("Start [=] Başla\n", encoding="utf-8")
        with patch("subway_blind.translation._resource_base_dir", return_value=self.base_path):
            entries = translation.available_language_entries()
        turkish = next(entry for entry in entries if entry.key == "turkish")
        self.assertEqual(turkish.version, "1.1.0")
        self.assertEqual(turkish.author, "vireon-interactive")

    def test_set_language_loads_lng_from_manifest(self):
        self._write_turkish_pack()
        with patch("subway_blind.translation._resource_base_dir", return_value=self.base_path):
            selected = translation.set_language("turkish")
            translated = translation.translate_text("Start")
        self.assertEqual(selected, "turkish")
        self.assertEqual(translated, "Başla")

    def test_set_language_falls_back_to_english_when_pack_is_invalid(self):
        broken_pack_path = self.langs_path / "broken"
        broken_pack_path.mkdir(parents=True, exist_ok=True)
        (broken_pack_path / "manifest.json").write_text(
            (
                "{\n"
                '  "id": "broken",\n'
                '  "name": "Broken Pack",\n'
                '  "language_file": "missing.lng"\n'
                "}\n"
            ),
            encoding="utf-8",
        )
        with patch("subway_blind.translation._resource_base_dir", return_value=self.base_path):
            selected = translation.set_language("broken")
            translated = translation.translate_text("Start")
        self.assertEqual(selected, "english")
        self.assertEqual(translated, "Start")


if __name__ == "__main__":
    unittest.main()
