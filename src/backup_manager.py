from __future__ import annotations

from datetime import datetime
from pathlib import Path
import zipfile


def create_backup(files: list[Path], backup_dir: Path) -> Path:
    """Create a timestamped ZIP backup without changing the source files."""
    existing_files = [p.resolve() for p in files if p.is_file()]
    if not existing_files:
        raise ValueError("No existing files were provided for backup.")

    backup_dir = backup_dir.expanduser().resolve()
    backup_dir.mkdir(parents=True, exist_ok=True)

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    archive = backup_dir / f"l2_client_backup_{stamp}.zip"

    # Store paths relative to a common parent where possible.
    common_parent = Path(
        __import__("os").path.commonpath([str(p.parent) for p in existing_files])
    )

    try:
        with zipfile.ZipFile(
            archive, mode="x", compression=zipfile.ZIP_DEFLATED
        ) as zf:
            for source in existing_files:
                try:
                    relative = source.relative_to(common_parent)
                except ValueError:
                    relative = Path(source.name)
                zf.write(source, arcname=str(relative))

        # Validate the archive before reporting success.
        with zipfile.ZipFile(archive, "r") as zf:
            bad_member = zf.testzip()
            if bad_member is not None:
                raise RuntimeError(f"Backup validation failed: {bad_member}")

        return archive
    except Exception:
        archive.unlink(missing_ok=True)
        raise


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Back up Lineage 2 client files")
    parser.add_argument("--backup-dir", type=Path, required=True)
    parser.add_argument("files", nargs="+", type=Path)
    args = parser.parse_args()

    try:
        result = create_backup(args.files, args.backup_dir)
        print(f"Backup created and validated: {result}")
    except Exception as exc:
        raise SystemExit(f"Backup failed: {exc}")
