from __future__ import annotations

import json
import hashlib
import io
import mmap
import os
import platform
import re
import struct
import sys
import shutil
import subprocess
import tempfile
import time
from fractions import Fraction
from collections.abc import Callable
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable


class ConverterError(RuntimeError):
    pass


@dataclass
class ToolInfo:
    name: str
    path: str | None
    version: str | None
    usable: bool
    error: str | None = None


def _tool_environment(name: str) -> dict[str, str]:
    env = os.environ.copy()
    # The host Codex environment injects a private native-library directory on
    # Termux. System FFmpeg must resolve its libraries from Termux PREFIX/lib.
    is_termux = sys.platform in {"linux", "android"} and os.environ.get("PREFIX", "").endswith("/com.termux/files/usr")
    if name in {"ffmpeg", "ffprobe"} and is_termux:
        env.pop("LD_LIBRARY_PATH", None)
    return env


def _resolve_executable(name: str) -> str | None:
    executable = name + (".exe" if os.name == "nt" else "")
    roots = []
    frozen_root = getattr(sys, "_MEIPASS", None)
    if frozen_root:
        roots.append(Path(frozen_root))
    project_root = Path(__file__).resolve().parent.parent
    roots.extend((project_root, project_root / "vendor"))
    for root in roots:
        for candidate in (root / "ffmpeg" / executable,
                          root / "vendor" / "ffmpeg" / "bin" / executable,
                          root / "ffmpeg" / "bin" / executable):
            if candidate.is_file():
                return str(candidate)
    return shutil.which(name) or (shutil.which(executable) if executable != name else None)


def _probe_wannacri() -> ToolInfo:
    path = shutil.which("wannacri")
    try:
        import importlib.metadata
        from wannacri.usm import Usm
        version = importlib.metadata.version("WannaCRI")
        usable = callable(getattr(Usm, "open", None)) and callable(getattr(Usm, "demux", None))
        return ToolInfo("wannacri", path, f"WannaCRI {version} Usm.open/demux", usable,
                        None if usable else "API Usm.open/demux ausente")
    except (ImportError, importlib.metadata.PackageNotFoundError) as exc:
        return ToolInfo("wannacri", path, None, False, str(exc))


def probe_tool(name: str, args: list[str]) -> ToolInfo:
    path = _resolve_executable(name)
    if not path:
        return ToolInfo(name, None, None, False, "não encontrado no PATH")
    try:
        proc = subprocess.run([path, *args], capture_output=True, text=True, timeout=8,
                              env=_tool_environment(name))
        output = (proc.stdout + proc.stderr).strip()
        return ToolInfo(name, path, output.splitlines()[0] if output else None,
                        proc.returncode == 0, None if proc.returncode == 0 else output[-500:])
    except (OSError, subprocess.TimeoutExpired) as exc:
        return ToolInfo(name, path, None, False, str(exc))


def diagnostics() -> dict:
    tools = [probe_tool("python", ["--version"]), probe_tool("ffmpeg", ["-version"]),
             probe_tool("ffprobe", ["-version"]), _probe_wannacri(),
             probe_tool("cricodecs", ["--help"]), probe_tool("vgmstream-cli", ["-h"])]
    ffmpeg = next(x for x in tools if x.name == "ffmpeg")
    encoders: list[str] = []
    if ffmpeg.usable:
        result = subprocess.run([ffmpeg.path, "-encoders"], capture_output=True, text=True,
                                env=_tool_environment("ffmpeg"))
        encoders = [name for name in re.findall(r"^\s*[VAS.]\S+\s+(\S+)", result.stdout, re.M)
                    if name != "="]
    decoders: list[str] = []
    if ffmpeg.usable:
        result = subprocess.run([ffmpeg.path, "-decoders"], capture_output=True, text=True,
                                env=_tool_environment("ffmpeg"))
        decoders = [name for name in re.findall(r"^\s*[VAS.]\S+\s+(\S+)", result.stdout, re.M)
                    if name != "="]
    ld_adjustment = (sys.platform in {"linux", "android"} and
                     os.environ.get("PREFIX", "").endswith("/com.termux/files/usr") and
                     bool(os.environ.get("LD_LIBRARY_PATH")))
    return {"tools": [asdict(t) for t in tools], "available_encoders": encoders,
            "available_decoders": decoders,
            "ffmpeg_ld_library_path_removed_for_subprocess": ld_adjustment}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _close_wannacri_stream_handles(parsed) -> None:
    """Close the file handle retained by WannaCRI 0.3.x stream factories.

    WannaCRI currently exposes no close() method on Usm. Its generators retain
    the input BufferedReader in a closure, so close it after demux completes.
    """
    media_tracks = [*getattr(parsed, "videos", []), *getattr(parsed, "audios", []),
                    *getattr(parsed, "alphas", [])]
    closed: set[int] = set()
    for track in media_tracks:
        factory = getattr(track, "_stream_factory", None)
        for cell in getattr(factory, "__closure__", None) or ():
            try:
                value = cell.cell_contents
            except ValueError:
                continue
            if isinstance(value, io.IOBase) and id(value) not in closed:
                value.close()
                closed.add(id(value))


def extract_usm_file(source: Path, output_dir: Path, key: int | None = None) -> dict:
    """Demux one USM with WannaCRI into a new, isolated output directory."""
    try:
        from wannacri.usm import Usm
    except ImportError as exc:
        raise ConverterError("WannaCRI não está disponível neste Python") from exc

    source = source.resolve(strict=True)
    if not source.is_file():
        raise ConverterError(f"entrada não é arquivo: {source}")
    output_dir = output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    destination = output_dir / source.name
    if destination.exists():
        raise ConverterError(f"destino já existe; nada será sobrescrito: {destination}")
    original_hash = _sha256(source)

    with tempfile.TemporaryDirectory(prefix=".diva-usm-", dir=output_dir) as temp_name:
        temp_root = Path(temp_name)
        try:
            parsed = Usm.open(source, key=key)
            video_codecs = []
            for video in parsed.videos:
                codec = video.header_page.get("mpeg_codec")
                value = codec.val if codec is not None else None
                video_codecs.append(value)
            audio_codecs = []
            for audio in parsed.audios:
                codec = audio.header_page.get("audio_codec")
                audio_codecs.append(codec.val if codec is not None else None)
            if not video_codecs:
                raise ConverterError("USM válido, mas sem canal de vídeo")
            if any(codec != 9 for codec in video_codecs):
                raise ConverterError(f"vídeo fora do escopo VP9; mpeg_codec detectado: {video_codecs}")

            try:
                videos, audios = parsed.demux(
                    path=str(temp_root), save_video=True, save_audio=True,
                    # WannaCRI slugifies this name. A neutral name without an
                    # extension or Unicode punctuation keeps the staging path
                    # deterministic across platforms and source filenames.
                    save_alpha=True, save_pages=False, folder_name="usm-streams",
                )
            finally:
                _close_wannacri_stream_handles(parsed)
            staged = temp_root / "usm-streams"
            if not staged.is_dir() or not videos:
                raise ConverterError("WannaCRI não produziu arquivos de vídeo")
            for returned in [*videos, *audios]:
                resolved = Path(returned).resolve()
                if not resolved.is_relative_to(staged.resolve()) or not resolved.is_file() or resolved.stat().st_size == 0:
                    raise ConverterError(f"stream extraído ausente, vazio ou fora da pasta de staging: {returned}")
            extracted = []
            for track in ("videos", "audios", "alphas"):
                for file in sorted((staged / track).glob("*")) if (staged / track).exists() else []:
                    if file.is_file():
                        extracted.append({"kind": track, "path": str(file.relative_to(staged)),
                                          "size": file.stat().st_size, "sha256": _sha256(file)})
            if not any(item["kind"] == "videos" for item in extracted):
                raise ConverterError("nenhum arquivo de vídeo extraído")
            if _sha256(source) != original_hash:
                raise ConverterError("hash da origem mudou durante a extração; resultado descartado")
            report = {"source": str(source), "source_sha256": original_hash,
                      "demuxer": "WannaCRI", "version": __import__("wannacri").__version__,
                      "video_codec_ids": video_codecs, "video_streams": len(videos),
                      "audio_streams": len(audios), "audio_codec_ids": audio_codecs,
                      "files": extracted,
                      "conversion_performed": False}
            (staged / "extraction-report.json").write_text(
                json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            os.rename(staged, destination)
            report["output_directory"] = str(destination)
            return report
        except ConverterError:
            raise
        except Exception as exc:
            raise ConverterError(f"falha no demux WannaCRI de {source.name}: {type(exc).__name__}: {exc}") from exc


def inspect_usm(path: Path) -> dict:
    """Report USM chunk markers without assuming codecs or decrypting payloads."""
    size = path.stat().st_size
    if size < 8:
        raise ConverterError("arquivo pequeno demais para ser um USM")
    with path.open("rb") as f:
        magic = f.read(4)
    if magic != b"CRID":
        raise ConverterError("assinatura CRID ausente; extensão .usm não prova o formato")
    tags = {b"@SFV": "video", b"@SFA": "audio", b"@ALP": "alpha", b"@SBT": "subtitle", b"@UTF": "metadata"}
    counts: dict[str, int] = {}
    examples: list[dict] = []
    with path.open("rb") as f:
        with mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ) as data:
            for tag, kind in tags.items():
                positions = []
                start = 0
                while (pos := data.find(tag, start)) >= 0:
                    positions.append(pos)
                    start = pos + 4
                if positions:
                    counts[kind] = len(positions)
                    examples.extend({"kind": kind, "offset": p} for p in positions[:2])
    return {"file": str(path), "size": size, "signature": "CRID", "chunk_marker_counts": counts,
            "markers": examples, "codec": "não determinado por varredura de assinatura",
            "note": "varredura indicativa; validação/demux requer decodificador CRI compatível"}


def walk_usm_chunks(path: Path) -> list[dict]:
    """Walk the declared USM chunk boundaries and report packet header fields.

    This validates framing only. UTF metadata, codec identification, masking,
    packet reassembly and timestamp conversion are deliberately not guessed.
    """
    total = path.stat().st_size
    chunks = []
    with path.open("rb") as f:
        if f.read(4) != b"CRID":
            raise ConverterError("assinatura CRID ausente")
        offset = 0
        while offset < total:
            if total - offset < 8:
                raise ConverterError(f"cabeçalho de chunk truncado no offset {offset}")
            f.seek(offset)
            head = f.read(8)
            tag = head[:4].decode("ascii", errors="replace")
            declared = struct.unpack(">I", head[4:])[0]
            end = offset + 8 + declared
            if declared == 0 or end > total:
                raise ConverterError(f"tamanho de chunk inválido em {offset}: {declared}")
            item = {"offset": offset, "tag": tag, "declared_size": declared}
            if tag in ("@SFV", "@SFA", "@ALP", "@SBT"):
                if declared < 24:
                    raise ConverterError(f"cabeçalho de stream curto em {offset}")
                f.seek(offset + 8)
                packet_header = f.read(24)
                payload_offset = packet_header[1]
                padding = int.from_bytes(packet_header[2:4], "big")
                stream_index = packet_header[4]
                payload_type = packet_header[7]
                frame_time = int.from_bytes(packet_header[8:12], "big")
                frame_rate = int.from_bytes(packet_header[12:16], "big")
                data_start = max(24, payload_offset)
                payload_size = declared - data_start - padding
                if payload_size < 0:
                    raise ConverterError(f"offset/padding excede chunk em {offset}")
                item.update({"stream_kind": {"@SFV": "video", "@SFA": "audio", "@ALP": "alpha", "@SBT": "subtitle"}[tag],
                             "stream_index": stream_index, "payload_type": payload_type,
                             "frame_time_raw": frame_time, "frame_rate_raw": frame_rate,
                             "payload_offset": payload_offset, "padding_size": padding,
                             "payload_size": payload_size})
            chunks.append(item)
            offset = end
    return chunks


# Match only the value of movie_file_name, preserving surrounding syntax and encoding.
FIELD_RE = re.compile(r"(?P<prefix>\bmovie_file_name\b\s*(?:[:=]\s*))(?P<quote>[\"']?)(?P<value>[^\"'\r\n,;}]+)(?P=quote)")


def read_text_preserve(path: Path) -> tuple[str, str, bytes]:
    raw = path.read_bytes()
    for encoding in ("utf-8-sig", "utf-8", "utf-16", "cp932"):
        try:
            return raw.decode(encoding), encoding, raw
        except UnicodeError:
            continue
    raise ConverterError("não foi possível decodificar o PVDB como texto conhecido")


def pvdb_plan(path: Path, output_dir: Path, recursive: bool = False) -> tuple[str, list[dict], str]:
    content, encoding, _ = read_text_preserve(path)
    matches = list(FIELD_RE.finditer(content))
    if not matches:
        raise ConverterError("nenhum campo movie_file_name encontrado; formato não reconhecido")
    new_content = content
    report = []
    for m in reversed(matches):
        old = m.group("value").strip()
        if not old:
            continue
        dest_name = Path(old.replace("\\", "/")).with_suffix(".mp4").name
        target = output_dir / dest_name
        report.insert(0, {"old": old, "new": str(target), "exists": target.is_file()})
        if target.is_file():
            value = str(target)
            new_content = new_content[:m.start("value")] + value + new_content[m.end("value"):]
    return new_content, report, encoding


def apply_pvdb(path: Path, content: str, encoding: str) -> Path:
    backup = path.with_name(path.name + ".bak")
    if backup.exists():
        raise ConverterError(f"backup já existe; não será sobrescrito: {backup}")
    shutil.copy2(path, backup)
    # utf-8-sig decoder strips BOM; restore it when writing.
    data = content.encode(encoding)
    if encoding == "utf-8-sig" and not data.startswith(b"\xef\xbb\xbf"):
        data = b"\xef\xbb\xbf" + data
    temp = path.with_name(path.name + ".tmp")
    temp.write_bytes(data)
    os.replace(temp, path)
    return backup


PROFILE_OPTIONS = {
    # balanced matches the preset/CRF used for the successful real-PV sample.
    "quality": ("slow", "18"),
    "balanced": ("veryfast", "23"),
    "size": ("veryfast", "28"),
}
ETA_SAMPLE_SIZE = 17_081_584
ETA_SAMPLE_DURATION = 129.583
ETA_SAMPLE_SECONDS_PER_MEDIA_SECOND = 167.33 / ETA_SAMPLE_DURATION

def _ffprobe_json(path: Path) -> dict:
    info = probe_tool("ffprobe", ["-version"])
    if not info.usable or not info.path:
        raise ConverterError("FFprobe não está funcional: " + str(info.error))
    proc = subprocess.run(
        [info.path, "-v", "error", "-show_entries",
         "format=format_name,duration,size:stream=index,codec_type,codec_name,width,height,duration,r_frame_rate,avg_frame_rate",
         "-of", "json", str(path)], capture_output=True, text=True, timeout=60,
        env=_tool_environment("ffprobe"))
    if proc.returncode:
        raise ConverterError(f"FFprobe falhou para {path.name}: {proc.stderr.strip()[-1000:]}")
    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        raise ConverterError(f"resposta inválida do FFprobe para {path.name}") from exc


def _validated_h264(path: Path) -> dict | None:
    try:
        probe = _ffprobe_json(path)
        videos = [stream for stream in probe.get("streams", [])
                  if stream.get("codec_type") == "video"]
        if (len(videos) != 1 or videos[0].get("codec_name") != "h264" or
                any(stream.get("codec_type") == "audio" for stream in probe.get("streams", []))):
            return None
        if not any(name in probe.get("format", {}).get("format_name", "")
                   for name in ("mp4", "mov")):
            return None
        if int(videos[0].get("width", 0)) <= 0 or int(videos[0].get("height", 0)) <= 0:
            return None
        duration = float(videos[0].get("duration") or probe.get("format", {}).get("duration") or 0)
        if duration <= 0:
            return None
        ffmpeg = probe_tool("ffmpeg", ["-version"])
        if not ffmpeg.usable or not ffmpeg.path:
            return None
        decode = subprocess.run([ffmpeg.path, "-v", "error", "-xerror", "-i", str(path),
                                 "-map", "0:v:0", "-f", "null", "-"],
                                capture_output=True, text=True, timeout=180,
                                env=_tool_environment("ffmpeg"))
        if decode.returncode:
            return None
        return {"probe": probe, "video": videos[0], "duration": duration}
    except (ConverterError, OSError, ValueError, subprocess.TimeoutExpired):
        return None


def _save_batch_state(path: Path, state: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".tmp")
    temp.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temp, path)


def _append_batch_log(output_dir: Path, entry: dict) -> None:
    with (output_dir / "conversion.log").open("a", encoding="utf-8") as log:
        log.write(json.dumps({"time": time.strftime("%Y-%m-%dT%H:%M:%S%z"), **entry},
                             ensure_ascii=False) + "\n")
        log.flush()


def run_batch(input_dir: Path | Iterable[Path], output_dir: Path, profile: str, state_path: Path,
              progress: Callable[[dict], None] | None = None,
              cancel_event=None) -> dict:
    """Demux VP9 USM videos and convert each to a silent H.264 MP4.

    The sample PV conversion measured 0.774x realtime with libx264 veryfast,
    CRF 23. That device measurement seeds ETA until this run supplies newer data.
    """
    if profile not in PROFILE_OPTIONS:
        raise ConverterError(f"perfil desconhecido: {profile}")
    if isinstance(input_dir, (str, os.PathLike)):
        input_path = Path(input_dir).resolve(strict=True)
        if not input_path.is_dir():
            raise ConverterError(f"entrada não é pasta: {input_path}")
        sources = sorted(path for path in input_path.iterdir()
                         if path.is_file() and path.suffix.lower() == ".usm")
        input_display = str(input_path)
        input_files = None
    else:
        sources = sorted({Path(path).resolve(strict=True) for path in input_dir})
        if any(not path.is_file() or path.suffix.lower() != ".usm" for path in sources):
            raise ConverterError("a seleção contém arquivos ausentes ou que não têm extensão .usm")
        input_files = [str(path) for path in sources]
        try:
            input_display = str(Path(os.path.commonpath([str(p.parent) for p in sources])).resolve()) if sources else ""
        except ValueError:  # selections may span Windows drive letters
            input_display = ""
    output_dir = output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    state_path = state_path.resolve()
    info = diagnostics()
    by_name = {t["name"]: t for t in info["tools"]}
    if not by_name["ffmpeg"]["usable"]:
        raise ConverterError("FFmpeg não inicia neste ambiente: " + str(by_name["ffmpeg"]["error"]))
    if not by_name["wannacri"]["usable"]:
        raise ConverterError("WannaCRI não encontrado; FFmpeg direto não é uma extração USM confiável")
    encoders = info["available_encoders"]
    if "libx264" not in encoders:
        raise ConverterError("encoder libx264 não disponível; perfis não podem presumir outro encoder")
    if not sources:
        raise ConverterError(f"nenhum arquivo USM encontrado em {input_display}")
    try:
        state = json.loads(state_path.read_text(encoding="utf-8")) if state_path.is_file() else {}
    except (OSError, json.JSONDecodeError):
        state = {}
    entries = state.get("files")
    if not isinstance(entries, dict):
        entries = {}
        state["files"] = entries
    # Measured real-PV baseline: encoding took 2:47.33 for 2:09.583 of video.
    measured_profiles = state.get("seconds_per_media_second_by_profile")
    if not isinstance(measured_profiles, dict):
        measured_profiles = {}
        state["seconds_per_media_second_by_profile"] = measured_profiles
    performance_key = f"{sys.platform}:{platform.machine()}:{profile}"
    seconds_per_media_second = measured_profiles.get(performance_key)
    is_termux = sys.platform in {"linux", "android"} and os.environ.get("PREFIX", "").endswith("/com.termux/files/usr")
    if seconds_per_media_second is None and is_termux and profile == "balanced":
        seconds_per_media_second = ETA_SAMPLE_SECONDS_PER_MEDIA_SECOND
    batch_started = time.monotonic()

    def estimated_files_time(files: list[Path]) -> float | None:
        # The real PV sample seeds estimates by input byte size until live FFmpeg
        # timestamps provide a rate for the current profile/device.
        if seconds_per_media_second is None:
            return None
        return sum(p.stat().st_size for p in files) / ETA_SAMPLE_SIZE * ETA_SAMPLE_DURATION * seconds_per_media_second

    def total_estimate(remaining: float | None) -> float | None:
        return time.monotonic() - batch_started + remaining if remaining is not None else None

    preset, crf = PROFILE_OPTIONS[profile]
    completed = 0
    outcomes: list[dict] = []
    for index, source in enumerate(sources, 1):
        source = source.resolve(strict=True)
        destination = output_dir / f"{source.stem}.mp4"
        source_hash = _sha256(source)
        prior = entries.get(str(source), {})
        if (destination.is_file() and prior.get("status") == "success" and
                prior.get("source_sha256") == source_hash and prior.get("profile") == profile):
            valid = _validated_h264(destination)
            if valid:
                completed += 1
                result = {"source": str(source), "output": str(destination),
                          "status": "skipped_validated", "duration": valid["duration"]}
                outcomes.append(result)
                _append_batch_log(output_dir, result)
                if progress:
                    future_estimate = estimated_files_time(sources[index:])
                    progress({"file_index": index, "file_count": len(sources),
                              "file": source.name, "status": result["status"],
                              "source": str(source),
                              "file_percent": 100, "completed": completed,
                              "remaining_seconds": future_estimate,
                              "estimated_total_seconds": total_estimate(future_estimate)})
                continue
        if destination.exists():
            message = f"destino já existe e não pertence a um resultado validado: {destination}"
            entries[str(source)] = {"status": "error", "error": message}
            result = {"source": str(source), "output": str(destination),
                      "status": "error", "error": message}
            outcomes.append(result)
            _append_batch_log(output_dir, result)
            _save_batch_state(state_path, state)
            continue

        started = time.monotonic()
        if progress:
            initial_estimate = estimated_files_time(sources[index - 1:])
            progress({"file_index": index, "file_count": len(sources), "file": source.name,
                      "source": str(source),
                      "status": "extracting", "file_percent": 0, "completed": completed,
                      "remaining_seconds": initial_estimate,
                      "estimated_total_seconds": total_estimate(initial_estimate)})
        temp_fd, temp_name = tempfile.mkstemp(prefix=f".{source.stem}.", suffix=".partial.mp4",
                                              dir=output_dir)
        os.close(temp_fd)
        temp_output = Path(temp_name)
        temp_output.unlink()
        try:
            with tempfile.TemporaryDirectory(prefix=".diva-batch-", dir=output_dir) as staging:
                extraction = extract_usm_file(source, Path(staging))
                video_files = [Path(staging) / source.name / item["path"]
                               for item in extraction["files"] if item["kind"] == "videos"]
                if len(video_files) != 1:
                    raise ConverterError(f"esperado um fluxo de vídeo VP9; encontrados {len(video_files)}")
                input_probe = _ffprobe_json(video_files[0])
                video_streams = [s for s in input_probe.get("streams", [])
                                 if s.get("codec_type") == "video"]
                if len(video_streams) != 1 or video_streams[0].get("codec_name") != "vp9":
                    raise ConverterError("fluxo extraído não foi validado como um único vídeo VP9 pelo FFprobe")
                duration = float(video_streams[0].get("duration") or
                                 input_probe.get("format", {}).get("duration") or 0)
                if duration <= 0:
                    raise ConverterError("duração do vídeo extraído não identificada pelo FFprobe")
                if cancel_event is not None and cancel_event.is_set():
                    raise ConverterError("DIVA_CANCELLED")
                ffmpeg_path = by_name["ffmpeg"]["path"]
                command = [ffmpeg_path, "-hide_banner", "-loglevel", "error", "-stats_period", "0.5",
                           "-progress", "pipe:1", "-nostats", "-i", str(video_files[0]),
                           "-map", "0:v:0", "-an", "-c:v", "libx264", "-preset", preset,
                           "-crf", crf, "-pix_fmt", "yuv420p", "-movflags", "+faststart",
                           str(temp_output)]
                stderr_path = temp_output.with_suffix(".log")
                try:
                    with stderr_path.open("w", encoding="utf-8") as error_log:
                        process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=error_log,
                                                   text=True, bufsize=1,
                                                   env=_tool_environment("ffmpeg"))
                        assert process.stdout is not None
                        for line in process.stdout:
                            if cancel_event is not None and cancel_event.is_set():
                                process.terminate()
                                try:
                                    process.wait(timeout=5)
                                except subprocess.TimeoutExpired:
                                    process.kill()
                                    process.wait()
                                raise ConverterError("DIVA_CANCELLED")
                            if line.startswith("out_time_ms="):
                                try:
                                    media_time = int(line.split("=", 1)[1]) / 1_000_000
                                except ValueError:
                                    continue
                                percent = min(99.0, media_time / duration * 100)
                                elapsed = time.monotonic() - started
                                speed = media_time / elapsed if elapsed > 0 and media_time > 0 else 0
                                if speed > 0:
                                    estimate = max(0.0, duration - media_time) / speed
                                    future_estimate = estimated_files_time(sources[index:])
                                    if future_estimate is None:
                                        future_estimate = (elapsed / media_time / max(1, source.stat().st_size) *
                                                           sum(p.stat().st_size for p in sources[index:])) if media_time else 0
                                    remaining = estimate + future_estimate
                                else:
                                    future_estimate = estimated_files_time(sources[index:])
                                    remaining = (duration * seconds_per_media_second + future_estimate
                                                 if seconds_per_media_second is not None and future_estimate is not None
                                                 else None)
                                if progress:
                                    progress({"file_index": index, "file_count": len(sources),
                                              "file": source.name, "source": str(source),
                                              "status": "converting",
                                              "file_percent": percent, "completed": completed,
                                              "remaining_seconds": remaining,
                                              "estimated_total_seconds": total_estimate(remaining)})
                        return_code = process.wait()
                    if return_code:
                        detail = stderr_path.read_text(encoding="utf-8", errors="replace")[-2000:]
                        raise ConverterError(f"FFmpeg retornou {return_code}: {detail.strip()}")
                finally:
                    stderr_path.unlink(missing_ok=True)
            valid = _validated_h264(temp_output)
            if not valid:
                raise ConverterError("MP4 temporário não passou pela validação FFprobe/H.264")
            if abs(valid["duration"] - duration) > max(0.15, duration * 0.002):
                raise ConverterError(f"duração MP4 ({valid['duration']:.3f}s) difere do VP9 ({duration:.3f}s)")
            input_video = video_streams[0]
            output_video = valid["video"]
            if (int(output_video.get("width", 0)) != int(input_video.get("width", 0)) or
                    int(output_video.get("height", 0)) != int(input_video.get("height", 0))):
                raise ConverterError("resolução do MP4 difere do vídeo VP9 de origem")
            input_rate = input_video.get("avg_frame_rate") or input_video.get("r_frame_rate")
            output_rate = output_video.get("avg_frame_rate") or output_video.get("r_frame_rate")
            try:
                if input_rate and output_rate and Fraction(input_rate) != Fraction(output_rate):
                    raise ConverterError("taxa de quadros do MP4 difere do vídeo VP9 de origem")
            except (ValueError, ZeroDivisionError):
                pass
            if _sha256(source) != source_hash:
                raise ConverterError("hash da origem mudou durante conversão; MP4 temporário descartado")
            os.replace(temp_output, destination)
            elapsed = time.monotonic() - started
            if duration > 0 and elapsed > 0:
                measured = elapsed / duration
                # Smooth new observations to avoid ETA swings between files.
                seconds_per_media_second = (seconds_per_media_second * 0.5 + measured * 0.5
                                            if seconds_per_media_second is not None else measured)
                measured_profiles[performance_key] = seconds_per_media_second
            completed += 1
            result = {"source": str(source), "output": str(destination), "status": "success",
                      "duration": valid["duration"], "source_sha256": source_hash,
                      "elapsed_seconds": round(elapsed, 2), "video": valid["video"]}
            outcomes.append(result)
            result["profile"] = profile
            entries[str(source)] = {**result}
            _save_batch_state(state_path, state)
            _append_batch_log(output_dir, result)
            if progress:
                remaining = estimated_files_time(sources[index:])
                progress({"file_index": index, "file_count": len(sources), "file": source.name,
                          "source": str(source), "status": "success", "file_percent": 100, "completed": completed,
                          "remaining_seconds": remaining,
                          "estimated_total_seconds": total_estimate(remaining)})
        except Exception as exc:
            temp_output.unlink(missing_ok=True)
            failure = str(exc)
            cancelled = failure == "DIVA_CANCELLED" or (
                cancel_event is not None and cancel_event.is_set())
            result = {"source": str(source), "output": str(destination),
                      "status": "cancelled" if cancelled else "error", "error": failure}
            outcomes.append(result)
            entries[str(source)] = result
            _save_batch_state(state_path, state)
            _append_batch_log(output_dir, result)
            if progress:
                progress({"file_index": index, "file_count": len(sources), "file": source.name,
                          "source": str(source), "status": result["status"],
                          "file_percent": 0, "completed": completed,
                          "remaining_seconds": None, "error": failure})
            if cancelled:
                for pending_index, pending_source in enumerate(sources[index:], index + 1):
                    pending_result = {"source": str(pending_source), "status": "cancelled",
                                      "error": "DIVA_CANCELLED"}
                    outcomes.append(pending_result)
                    entries[str(pending_source)] = pending_result
                    _append_batch_log(output_dir, pending_result)
                    if progress:
                        progress({"file_index": pending_index, "file_count": len(sources),
                                  "file": pending_source.name, "source": str(pending_source),
                                  "status": "cancelled", "file_percent": 0,
                                  "completed": completed, "remaining_seconds": None,
                                  "error": "DIVA_CANCELLED"})
                _save_batch_state(state_path, state)
                break
    report = {"input_dir": input_display, "input_files": input_files,
              "output_dir": str(output_dir), "profile": profile,
              "total": len(sources), "completed": completed, "successes": sum(
                  x["status"] in {"success", "skipped_validated"} for x in outcomes),
              "failures": sum(x["status"] == "error" for x in outcomes),
              "cancelled": sum(x["status"] == "cancelled" for x in outcomes), "files": outcomes,
              "state": str(state_path)}
    report_path = output_dir / "conversion-report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report
