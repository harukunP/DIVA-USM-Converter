import hashlib
import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from diva_usm_converter.core import ConverterError, run_batch


def fake_diagnostics():
    return {
        "tools": [
            {"name": "ffmpeg", "usable": True, "path": "ffmpeg"},
            {"name": "ffprobe", "usable": True, "path": "ffprobe"},
            {"name": "wannacri", "usable": True, "path": "wannacri"},
        ],
        "available_encoders": ["libx264"],
    }


class BatchSafetyTests(unittest.TestCase):
    def test_unicode_paths_error_report_and_original_preserved(self):
        with tempfile.TemporaryDirectory(prefix="DIVA São João ") as temp:
            root = Path(temp)
            source = root / "Entrada com espaço" / "Vídeo PV.usm"
            source.parent.mkdir()
            source.write_bytes(b"original USM bytes")
            original_hash = hashlib.sha256(source.read_bytes()).hexdigest()
            output = root / "Saída MP4"
            progress = []
            with patch("diva_usm_converter.core.diagnostics", fake_diagnostics), \
                 patch("diva_usm_converter.core.extract_usm_file",
                       side_effect=ConverterError("demux intencionalmente falhou")):
                report = run_batch([source], output, "balanced", root / "estado.json",
                                   progress=progress.append)
            self.assertEqual(report["failures"], 1)
            self.assertEqual(report["files"][0]["status"], "error")
            self.assertIn("demux intencionalmente falhou", report["files"][0]["error"])
            self.assertFalse((output / "Vídeo PV.mp4").exists())
            self.assertEqual(hashlib.sha256(source.read_bytes()).hexdigest(), original_hash)
            self.assertEqual(progress[0]["status"], "extracting")
            saved_report = json.loads((output / "conversion-report.json").read_text(encoding="utf-8"))
            self.assertEqual(saved_report["failures"], 1)

    def test_interruption_before_encode_discards_partial_output(self):
        with tempfile.TemporaryDirectory(prefix="DIVA cancelamento ") as temp:
            root = Path(temp)
            source = root / "origem.usm"
            source.write_bytes(b"source")
            cancel = threading.Event()
            progress = []

            def request_cancel(event):
                progress.append(event)
                if event.get("status") == "extracting":
                    cancel.set()

            extraction = {"files": [{"kind": "videos", "path": "videos/video.ivf"}]}
            with patch("diva_usm_converter.core.diagnostics", fake_diagnostics), \
                 patch("diva_usm_converter.core.extract_usm_file", return_value=extraction), \
                 patch("diva_usm_converter.core._ffprobe_json",
                       return_value={"streams": [{"codec_type": "video", "codec_name": "vp9",
                                                  "duration": "1", "width": 16, "height": 16}]}):
                report = run_batch([source], root / "out", "balanced", root / "state.json",
                                   progress=request_cancel, cancel_event=cancel)
            self.assertEqual(report["cancelled"], 1)
            self.assertFalse((root / "out" / "origem.mp4").exists())
            self.assertEqual(source.read_bytes(), b"source")

    def test_existing_invalid_output_is_never_overwritten(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "original.usm"
            source.write_bytes(b"USM source")
            output = root / "out"
            output.mkdir()
            existing = output / "original.mp4"
            existing.write_bytes(b"keep this invalid file")
            before = existing.read_bytes()
            with patch("diva_usm_converter.core.diagnostics", fake_diagnostics):
                report = run_batch([source], output, "balanced", root / "state.json")
            self.assertEqual(report["failures"], 1)
            self.assertEqual(existing.read_bytes(), before)

    def test_validated_previous_output_is_skipped(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "retomar.usm"
            source.write_bytes(b"same source")
            output = root / "out"
            output.mkdir()
            mp4 = output / "retomar.mp4"
            mp4.write_bytes(b"validated test output")
            state = root / "state.json"
            state.write_text(json.dumps({"files": {str(source.resolve()): {
                "status": "success",
                "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
                "profile": "balanced",
            }}}), encoding="utf-8")
            valid = {"duration": 1.0, "video": {"codec_name": "h264"}}
            with patch("diva_usm_converter.core.diagnostics", fake_diagnostics), \
                 patch("diva_usm_converter.core._validated_h264", return_value=valid), \
                 patch("diva_usm_converter.core.extract_usm_file") as extract:
                report = run_batch([source], output, "balanced", state)
            self.assertEqual(report["files"][0]["status"], "skipped_validated")
            extract.assert_not_called()
            self.assertEqual(mp4.read_bytes(), b"validated test output")


if __name__ == "__main__":
    unittest.main()
