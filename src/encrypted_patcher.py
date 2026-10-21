from __future__ import annotations

import os
import shutil
import stat
import subprocess
import tempfile
from pathlib import Path

from backup_manager import create_backup
from config_patcher import patch_plain_ini
from encrypted_config import decoded_config, EncryptedConfigError


def patch_encrypted_config(
    config_path: Path,
    server_address: str,
    encoder: Path,
    decoder: Path | None = None,
    backup_dir: Path | None = None,
    timeout: int = 30,
) -> tuple[Path, Path | None]:
    """Safely patch Lineage2Ver413 and preserve a verified backup."""
    config_path = config_path.expanduser().resolve()
    encoder = encoder.expanduser().resolve()
    decoder = (decoder or encoder).expanduser().resolve()

    if not config_path.is_file():
        raise FileNotFoundError(f"Config not found: {config_path}")
    if config_path.name.casefold() != "lineage2ver413":
        raise EncryptedConfigError("Expected a file named Lineage2Ver413.")
    if not encoder.is_file() or not decoder.is_file():
        raise FileNotFoundError("Encoder or decoder executable not found.")
    if timeout < 1 or timeout > 120:
        raise ValueError("Timeout must be between 1 and 120 seconds.")

    original = config_path.read_bytes()
    original_mode = stat.S_IMODE(config_path.stat().st_mode)

    with tempfile.TemporaryDirectory(prefix="l2c6-patch-") as work:
        workdir = Path(work)
        plain_path = workdir / "l2.ini"

        # Decode without touching the original encrypted file.
        with decoded_config(config_path, decoder, timeout) as decoded:
            shutil.copyfile(decoded, plain_path)

        decoded_original = plain_path.read_bytes()

        # Reuse the existing, validated [URL] / ServerAddr editor.
        patch_plain_ini(
            plain_path,
            server_address,
            backup_dir=workdir / "temporary-backups",
        )
        patched_plain = plain_path.read_bytes()

        if patched_plain == decoded_original:
            if config_path.read_bytes() != original:
                raise RuntimeError("Original config changed during processing.")
            return config_path, None

        # Encode into a temporary file with the exact expected filename.
        encoded_path = workdir / "Lineage2Ver413"
        result = subprocess.run(
            [
                str(encoder), "-c", "encode", "-p", "413",
                "-o", str(encoded_path), str(plain_path),
            ],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
        if result.returncode != 0 or not encoded_path.is_file():
            detail = (result.stderr or result.stdout or "").strip()
            raise EncryptedConfigError(
                "Encoding failed; original was not changed. "
                + (detail or f"Exit code: {result.returncode}")
            )

        # Decode the new file and demand an exact byte-for-byte match.
        with decoded_config(encoded_path, decoder, timeout) as check_path:
            if check_path.read_bytes() != patched_plain:
                raise EncryptedConfigError(
                    "Round-trip verification failed; original was not changed."
                )

        encrypted_bytes = encoded_path.read_bytes()

        # Refuse to overwrite if another process changed the source.
        if config_path.read_bytes() != original:
            raise RuntimeError(
                "Original config changed during processing; replacement refused."
            )

        if backup_dir is None:
            backup_dir = config_path.parent / "backups"

        # Backup is created and verified before replacing the original.
        backup_path = create_backup([config_path], backup_dir)

        replacement_name = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="wb",
                dir=config_path.parent,
                prefix=".l2c6-encrypted-",
                suffix=".tmp",
                delete=False,
            ) as temp:
                replacement_name = temp.name
                temp.write(encrypted_bytes)
                temp.flush()
                os.fsync(temp.fileno())

            os.chmod(replacement_name, original_mode)

            if config_path.read_bytes() != original:
                raise RuntimeError(
                    "Original config changed before replacement; "
                    "the original was left untouched."
                )

            os.replace(replacement_name, config_path)
            replacement_name = None

            # Verify replacement; restore original bytes on any verification failure.
            try:
                with decoded_config(config_path, decoder, timeout) as check_path:
                    if check_path.read_bytes() != patched_plain:
                        raise EncryptedConfigError(
                            "Installed config content does not match patched content."
                        )
            except Exception as verification_error:
                restore_name = None
                try:
                    with tempfile.NamedTemporaryFile(
                        mode="wb",
                        dir=config_path.parent,
                        prefix=".l2c6-restore-",
                        suffix=".tmp",
                        delete=False,
                    ) as restore:
                        restore_name = restore.name
                        restore.write(original)
                        restore.flush()
                        os.fsync(restore.fileno())
                    os.chmod(restore_name, original_mode)
                    os.replace(restore_name, config_path)
                    restore_name = None
                except Exception as restore_error:
                    raise RuntimeError(
                        f"Verification failed ({verification_error}); "
                        f"automatic restoration failed ({restore_error}). "
                        f"Original backup: {backup_path}"
                    ) from restore_error
                finally:
                    if restore_name:
                        Path(restore_name).unlink(missing_ok=True)
                raise EncryptedConfigError(
                    "Installed config failed verification; original bytes restored."
                ) from verification_error

            return config_path, backup_path
        finally:
            if replacement_name:
                Path(replacement_name).unlink(missing_ok=True)
