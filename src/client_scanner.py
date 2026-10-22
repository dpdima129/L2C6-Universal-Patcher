from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import os


@dataclass
class ClientInstallation:
    root: Path
    system_dir: Path
    executable: Path
    config: Path | None
    config_format: str


def classify_config(path: Path) -> str:
    """Classify a config without attempting to modify or decrypt it."""
    try:
        data = path.read_bytes()
    except OSError:
        return "unreadable"

    if not data:
        return "empty"

    # A plain INI file should be readable text with recognizable INI syntax.
    try:
        text = data.decode("utf-8-sig")
        if "\x00" not in text and any(
            line.lstrip().startswith("[") and "]" in line
            for line in text.splitlines()
        ):
            return "plain_ini"
    except UnicodeDecodeError:
        pass

    # Recognize the legacy protocol-413 header stored as UTF-16LE,
    # even when the encrypted config is named L2.ini.
    header = "Lineage2Ver413".encode("utf-16le")
    payload = data[2:] if data.startswith(bytes.fromhex("FF FE")) else data
    if payload.startswith(header):
        return "encrypted_candidate"
    # Known legacy encrypted config filename; encryption is not assumed valid.
    if path.name.casefold() == "lineage2ver413":
        return "encrypted_candidate"

    return "unknown"


def _system_dirs(root: Path):
    """Yield supported system directories, prioritizing the standard layout."""
    try:
        children = list(root.iterdir())
    except OSError:
        return

    candidates = []
    for child in children:
        if not child.is_dir():
            continue
        name = child.name.lower()
        if name == "system" or name == "system2" or (
            name.startswith("system_") or name.startswith("system-")
        ):
            candidates.append(child)

    candidates.sort(
        key=lambda p: (
            {"system": 0, "system2": 1}.get(p.name.lower(), 2),
            p.name.lower(),
        )
    )
    yield from candidates


def discover_clients(start: str | Path, max_depth: int = 3) -> list[ClientInstallation]:
    """Find likely Lineage 2 client roots, without changing any files."""
    base = Path(start).expanduser().resolve()
    if not base.is_dir():
        return []

    found: list[ClientInstallation] = []
    visited: set[Path] = set()

    def inspect(root: Path) -> None:
        for system_dir in _system_dirs(root):
            executable = next(
                (
                    p for p in system_dir.iterdir()
                    if p.is_file() and p.name.lower() == "l2.exe"
                ),
                None,
            )
            if executable is None:
                continue

            configs = [
                p for p in system_dir.iterdir()
                if p.is_file() and p.name.lower() in ("l2.ini", "lineage2ver413")
            ]
            config = next(
                (p for p in configs if p.name.lower() == "l2.ini"),
                None,
            )
            if config is None and configs:
                config = configs[0]

            fmt = classify_config(config) if config else "missing"
            found.append(ClientInstallation(
                root=root,
                system_dir=system_dir,
                executable=executable,
                config=config,
                config_format=fmt,
            ))

    # Check the selected folder itself and then descend a bounded number of levels.
    inspect(base)
    try:
        for current, dirs, _files in os.walk(base):
            current_path = Path(current)
            try:
                depth = len(current_path.relative_to(base).parts)
            except ValueError:
                dirs[:] = []
                continue

            dirs[:] = [
                name for name in dirs
                if name.lower() not in {
                    ".git", ".venv", "venv", "__pycache__", "system"
                }
            ]

            if depth >= max_depth:
                dirs[:] = []

            if current_path == base:
                continue
            if current_path in visited:
                continue
            visited.add(current_path)
            inspect(current_path)
    except OSError:
        pass

    # Deduplicate roots and return stable output.
    unique = {}
    for item in found:
        unique[(str(item.root), str(item.system_dir))] = item

    return sorted(
        unique.values(),
        key=lambda item: (str(item.root).lower(), str(item.system_dir).lower()),
    )


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Scan for Lineage 2 client installations")
    parser.add_argument("path", nargs="?", default=".", help="Folder to scan")
    parser.add_argument("--depth", type=int, default=3)
    args = parser.parse_args()

    installations = discover_clients(args.path, max_depth=max(0, args.depth))
    if not installations:
        print("No compatible client layout found.")
    for client in installations:
        print(f"Client root : {client.root}")
        print(f"System dir  : {client.system_dir}")
        print(f"Executable  : {client.executable}")
        print(f"Config      : {client.config or 'not found'}")
        print(f"Config type : {client.config_format}")
        print()
