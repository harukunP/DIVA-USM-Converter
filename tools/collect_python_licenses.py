"""Copy license texts for all installed distributions into a package staging tree."""
from __future__ import annotations

import argparse
import re
import shutil
from importlib.metadata import distributions
from pathlib import Path


def safe_name(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", value)


def collect(license_dir: Path, manifest_path: Path) -> int:
    if license_dir.exists():
        shutil.rmtree(license_dir)
    license_dir.mkdir(parents=True)
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    records = []
    copied = 0
    for dist in sorted(distributions(), key=lambda item: (item.metadata.get("Name", "").casefold(), item.version)):
        name = dist.metadata.get("Name", "unknown")
        version = dist.version
        records.append(f"{name}=={version} | license: {dist.metadata.get('License-Expression') or dist.metadata.get('License') or 'see included license text'}")
        for item in dist.files or ():
            relative = str(item).replace("\\", "/")
            leaf = Path(relative).name.casefold()
            if "/licenses/" not in f"/{relative.casefold()}" and not any(
                    word in leaf for word in ("license", "licence", "copying", "notice")):
                continue
            source = Path(dist.locate_file(item))
            if not source.is_file():
                continue
            target = license_dir / safe_name(f"{name}-{version}") / Path(relative)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
            copied += 1
    if copied == 0:
        raise RuntimeError("No Python distribution license files were found")
    manifest_path.write_text(
        "DIVA USM Converter - Python build environment components\n\n" +
        "This manifest lists the distributions installed in the isolated build environment.\n" +
        "Their license texts are included under licenses/python/.\n\n" +
        "\n".join(records) + "\n",
        encoding="utf-8",
    )
    return copied


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--license-dir", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    args = parser.parse_args()
    count = collect(args.license_dir, args.manifest)
    print(f"Collected {count} license files from installed Python distributions")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
