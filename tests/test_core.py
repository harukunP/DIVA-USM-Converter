import tempfile
import unittest
import importlib.util
import struct
from pathlib import Path

from diva_usm_converter.core import ConverterError, apply_pvdb, extract_usm_file, inspect_usm, pvdb_plan, walk_usm_chunks


class SafeWorkflowTests(unittest.TestCase):
    def test_inspect_requires_crid_even_with_usm_extension(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "fake.usm"
            p.write_bytes(b"not usm")
            with self.assertRaises(ConverterError):
                inspect_usm(p)

    def test_inspect_counts_markers_without_claiming_codec(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "tiny.usm"
            def chunk(tag, payload):
                return tag + len(payload).to_bytes(4, "big") + payload
            # 24-byte packet header plus a small payload; CRID header is another chunk.
            video = bytes([0, 24, 0, 0, 0, 0, 0, 0]) + bytes(16) + b"v"
            audio = bytes([0, 24, 0, 0, 1, 0, 0, 0]) + bytes(16) + b"a"
            p.write_bytes(chunk(b"CRID", bytes(12)) + chunk(b"@SFV", video) + chunk(b"@SFA", audio))
            result = inspect_usm(p)
            self.assertEqual(result["chunk_marker_counts"], {"video": 1, "audio": 1})
            self.assertIn("não determinado", result["codec"])
            chunks = walk_usm_chunks(p)
            self.assertEqual([c["tag"] for c in chunks], ["CRID", "@SFV", "@SFA"])
            self.assertEqual(chunks[1]["payload_size"], 1)

    def test_chunk_walker_rejects_truncated_declaration(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "broken.usm"
            p.write_bytes(b"CRID" + (100).to_bytes(4, "big") + bytes(4))
            with self.assertRaises(ConverterError):
                walk_usm_chunks(p)

    @unittest.skipUnless(importlib.util.find_spec("wannacri"), "WannaCRI não instalado")
    def test_wannacri_demux_roundtrip_isolated_and_non_overwriting(self):
        from wannacri.usm import GenericVideo, Usm
        from wannacri.usm.media.video import create_video_crid_page, create_video_header_page

        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            source = root / "Vídeo São João.usm"
            output = root / "extracted"
            frame = b"synthetic-vp9-payload"
            # Structurally valid IVF envelope. The payload is intentionally not a
            # decodable VP9 frame; this test covers CRI demux and byte preservation.
            ivf = (b"DKIF" + struct.pack("<HH4sHHIIII", 0, 32, b"VP90", 320, 180,
                                         30, 1, 1, 0) + struct.pack("<IQ", len(frame), 0) + frame)
            crid = create_video_crid_page("synthetic.ivf", len(ivf), len(ivf), 0, 1000, 16777984)
            header = create_video_header_page(1, 1, 30.0, len(ivf), 9, 0,
                                              {"width": 320, "height": 180})
            video = GenericVideo(lambda: iter([(ivf, True)]), crid, header, 1, 0)
            source.write_bytes(b"".join(Usm([video], version=16777984).stream()))
            before = source.read_bytes()

            report = extract_usm_file(source, output)
            extracted_video = output / source.name / "videos" / "synthetic.ivf"
            self.assertEqual(extracted_video.read_bytes(), ivf)
            self.assertEqual(source.read_bytes(), before)
            self.assertEqual(report["demuxer"], "WannaCRI")
            self.assertFalse(report["conversion_performed"])
            with self.assertRaises(ConverterError):
                extract_usm_file(source, output)

    def test_pvdb_preview_and_backup_write_only_explicitly(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            db = root / "pv_db.txt"
            out = root / "movies"
            out.mkdir()
            (out / "movie.mp4").write_bytes(b"mp4")
            original = 'id: 17\nmovie_file_name: "old/movie.usm"\nother: keep\n'
            db.write_text(original, encoding="utf-8")
            new, report, enc = pvdb_plan(db, out)
            self.assertEqual(db.read_text(encoding="utf-8"), original)
            self.assertTrue(report[0]["exists"])
            backup = apply_pvdb(db, new, enc)
            self.assertEqual(backup.read_text(encoding="utf-8"), original)
            self.assertIn(str(out / "movie.mp4"), db.read_text(encoding="utf-8"))
            with self.assertRaises(ConverterError):
                apply_pvdb(db, new, enc)


if __name__ == "__main__":
    unittest.main()
