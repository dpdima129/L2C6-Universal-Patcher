from __future__ import annotations

from datetime import datetime
from pathlib import Path
import os
import zipfile


def create_backup(files: list[Path], backup_dir: Path) -> Path:
    """Create and verify a timestamped ZIP backup without changing sources."""
    existing_files = [p.resolve() for p in files if p.is_file()]
    if not existing_files:
        raise ValueError("No existing files were provided for backup.")

    if len(set(existing_files)) != len(existing_files):
        raise ValueError("Duplicate source files were provided for backup.")

    backup_dir = backup_dir.expanduser().resolve()
    backup_dir.mkdir(parents=True, exist_ok=True)

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    archive = backup_dir / f"l2_client_backup_{stamp}.zip"

    common_parent = Path(
        os.path.commonpath([str(p.parent) for p in existing_files])
    )

    members: dict[str, Path] = {}
    for source in existing_files:
        try:
            relative = source.relative_to(common_parent)
        except ValueError:
            relative = Path(source.name)

        member_name = relative.as_posix()
        if member_name in members:
            raise ValueError(
                f"Duplicate archive path would be created: {member_name}"
            )
        members[member_name] = source

    try:
        with zipfile.ZipFile(
            archive, mode="x", compression=zipfile.ZIP_DEFLATED
        ) as zf:
            for member_name, source in members.items():
                zf.write(source, arcname=member_name)

        with zipfile.ZipFile(archive, "r") as zf:
            bad_member = zf.testzip()
            if bad_member is not None:
                raise RuntimeError(
                    f"Backup integrity check failed: {bad_member}"
                )

            archived_names = zf.namelist()
            if len(archived_names) != len(members):
                raise RuntimeError(
                    "Backup validation failed: unexpected file count."
                )

            if set(archived_names) != set(members):
                raise RuntimeError(
                    "Backup validation failed: file list does not match."
                )

            for member_name, source in members.items():
                if zf.read(member_name) != source.read_bytes():
                    raise RuntimeError(
                        f"Backup validation failed: content mismatch for "
                        f"{member_name}"
                    )

        return archive
    except Exception:
        archive.unlink(missing_ok=True)
        raise


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="Back up Lineage 2 client files"
    )
    parser.add_argument("--backup-dir", type=Path, required=True)
    parser.add_argument("files", nargs="+", type=Path)
    args = parser.parse_args()

    try:
        result = create_backup(args.files, args.backup_dir)
        print(f"Backup created and validated: {result}")
    except Exception as exc:
        raise SystemExit(f"Backup failed: {exc}")
