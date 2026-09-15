import struct
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class PackagingConfigurationTests(unittest.TestCase):
    def test_ico_has_windows_icon_header_and_expected_embedded_sizes(self):
        icon = ROOT / "assets" / "diva-icon.ico"
        payload = icon.read_bytes()
        reserved, kind, count = struct.unpack_from("<HHH", payload)
        self.assertEqual((reserved, kind), (0, 1))
        self.assertGreaterEqual(count, 1)
        entries = [struct.unpack_from("<BBBBHHII", payload, 6 + i * 16)
                   for i in range(count)]
        dimensions = {(entry[0] or 256, entry[1] or 256) for entry in entries}
        self.assertTrue({(16, 16), (32, 32), (48, 48), (256, 256)}.issubset(dimensions))
        for entry in entries:
            size, offset = entry[-2:]
            self.assertGreater(size, 0)
            self.assertGreaterEqual(offset, 6 + count * 16)
            self.assertLessEqual(offset + size, len(payload))

    def test_pyinstaller_spec_includes_runtime_resources_and_dependency_hooks(self):
        spec = (ROOT / "packaging/windows/DivaUSMConverter.spec").read_text(encoding="utf-8")
        for expected in ("root / \"locales\"", "root / \"assets\"", "diva-icon.ico",
                         "README.md", "DEPENDENCY_PROVENANCE.md", "python-licenses", "ffmpeg", "copy_metadata",
                         "collect_submodules(\"wannacri\")", "hiddenimports=hiddenimports"):
            with self.subTest(expected=expected):
                self.assertIn(expected, spec)
        for locale in ("en.json", "pt-BR.json", "es.json", "fr.json"):
            self.assertTrue((ROOT / "locales" / locale).is_file())

    def test_windows_build_refuses_unverified_or_incomplete_ffmpeg_vendor_tree(self):
        script = (ROOT / "packaging/windows/build.ps1").read_text(encoding="utf-8")
        for expected in ("ffmpeg.exe", "ffprobe.exe", "libx264", "LICENSES",
                         "THIRD_PARTY_NOTICES.txt", "SOURCE_CODE_OR_OFFER.txt",
                         "BUILDINFO.md", "SHA256SUMS.txt", "Get-FileHash",
                         "wannacri-0.3.3-py3-none-any.whl",
                         "3d96b35c9a76632d2e773eeb2372810e854d9d77b381f81dc348d92f9aacde5c",
                         "--gui-smoke-test", "unittest discover"):
            with self.subTest(expected=expected):
                self.assertIn(expected, script)

    def test_wannacri_runtime_license_and_source_bundle_notice_exist(self):
        self.assertTrue((ROOT / "licenses/WannaCRI-MIT.txt").is_file())
        requirements = (ROOT / "requirements-runtime.txt").read_text(encoding="utf-8")
        self.assertIn("WannaCRI==0.3.3", requirements)

    def test_python_license_collector_includes_installed_runtime_package(self):
        with tempfile.TemporaryDirectory(prefix="DIVA licenses ") as folder:
            license_dir = Path(folder) / "python-licenses"
            manifest = Path(folder) / "python-third-party.txt"
            run = subprocess.run(
                [sys.executable, str(ROOT / "tools/collect_python_licenses.py"),
                 "--license-dir", str(license_dir), "--manifest", str(manifest)],
                capture_output=True, text=True, check=False,
            )
            self.assertEqual(run.returncode, 0, run.stderr)
            self.assertIn("WannaCRI==0.3.3", manifest.read_text(encoding="utf-8"))
            self.assertTrue(list(license_dir.rglob("LICENCE")))


if __name__ == "__main__":
    unittest.main()
