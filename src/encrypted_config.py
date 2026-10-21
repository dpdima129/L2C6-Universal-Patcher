from __future__ import annotations

import re
import subprocess
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator


class EncryptedConfigError(RuntimeError):
    """Raised when an encrypted Lineage 2 config cannot be decoded safely."""


def _looks_like_l2_ini(path: Path) -> bool:
    try:
        text = path.read_bytes().decode("utf-8-sig")
    except (OSError, UnicodeDecodeError):
        return False

    if "\x00" in text:
        return False

    section = None
    server_addr_count = 0

    for line in text.splitlines():
        header = re.match(r"^\s*\[([^\]]+)\]", line)
        if header:
            section = header.group(1).strip().casefold()
        elif section == "url" and re.match(
            r"^\s*ServerAddr\s*=", line, re.IGNORECASE
        ):
            server_addr_count += 1

    return server_addr_count == 1


@contextmanager
def decoded_config(
    source: Path,
    decoder: Path,
    timeout: int = 15,
) -> Iterator[Path]:
    """
    Decode a Lineage2Ver413 candidate into a temporary file.

    The source is never modified. The yielded file exists only inside
    the context and is removed automatically afterwards.
    """
    source = source.expanduser().resolve()
    decoder = decoder.expanduser().resolve()

    if not source.is_file():
        raise FileNotFoundError(f"Config not found: {source}")
    if source.name.casefold() != "lineage2ver413":
        raise EncryptedConfigError(
            "Expected a file named Lineage2Ver413."
        )
    if not decoder.is_file():
        raise FileNotFoundError(f"Decoder not found: {decoder}")
    if timeout < 1 or timeout > 120:
        raise ValueError("Timeout must be between 1 and 120 seconds.")

    with tempfile.TemporaryDirectory(prefix="l2c6-decode-") as temp_dir:
        output = Path(temp_dir) / "decoded.ini"
        errors = []

        # Try both parameter sets; accept only a structurally valid INI.
        for extra_args in ([], ["-l"]):
            output.unlink(missing_ok=True)
            command = [
                str(decoder),
                "-c", "decode",
                "-p", "413",
                "-o", str(output),
                *extra_args,
                str(source),
            ]

            try:
                result = subprocess.run(
                    command,
                    capture_output=True,
                    text=True,
                    timeout=timeout,
                    check=False,
                )
            except subprocess.TimeoutExpired:
                errors.append("Decoder timed out.")
                continue
            except OSError as exc:
                raise EncryptedConfigError(
                    f"Could not start decoder: {exc}"
                ) from exc

            if result.returncode == 0 and output.is_file():
                if _looks_like_l2_ini(output):
                    yield output
                    return
                errors.append("Decoded output is not a valid L2 INI.")
            else:
                detail = (result.stderr or result.stdout or "").strip()
                errors.append(detail or f"Decoder exit code: {result.returncode}")

        raise EncryptedConfigError(
            "Could not decode a valid Lineage 2 INI. "
            + " | ".join(errors)
        )
