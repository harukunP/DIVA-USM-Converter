# PyInstaller onedir Windows build. Run only on Windows; see build.ps1.
from pathlib import Path
from PyInstaller.utils.hooks import collect_submodules, copy_metadata

root = Path(SPECPATH).resolve().parents[1]
vendor = root / "vendor" / "ffmpeg" / "bin"
datas = [
    (str(root / "locales"), "locales"),
    (str(root / "assets"), "assets"),
    (str(root / "licenses"), "licenses"),
    (str(root / "README.md"), "."),
    (str(root / "packaging" / "windows" / "DEPENDENCY_PROVENANCE.md"), "licenses"),
    (str(root / "build" / "python-third-party.txt"), "licenses"),
    (str(root / "build" / "python-licenses"), "licenses/python"),
]
datas.extend((str(item), "ffmpeg") for item in vendor.iterdir() if item.is_file())
for name in ("LICENSES", "THIRD_PARTY_NOTICES.txt", "SOURCE_CODE_OR_OFFER.txt",
             "BUILDINFO.md", "SHA256SUMS.txt"):
    item = vendor.parent / name
    datas.append((str(item), "licenses/ffmpeg"))
for package in ("WannaCRI", "ffmpeg-python", "python-json-logger", "tqdm",
                "future", "colorama"):
    datas.extend(copy_metadata(package))

# Include license texts for the complete isolated build environment, including
# the PyInstaller bootloader and its build-time dependencies.
hiddenimports = collect_submodules("wannacri")

a = Analysis(
    [str(root / "diva_usm.py")],
    pathex=[str(root)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, [], exclude_binaries=True, name="DIVA-USM-Converter",
    debug=False, bootloader_ignore_signals=False, strip=False, upx=False,
    console=False, disable_windowed_traceback=False,
    icon=str(root / "assets" / "diva-icon.ico"),
)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False,
               name="DIVA-USM-Converter")
