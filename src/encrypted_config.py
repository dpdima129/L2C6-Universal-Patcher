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
        elif section in {"url", "auth"} and re.match(
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
    """Decode a supported encrypted config to a temporary file."""
    source = source.expanduser().resolve()
    decoder = decoder.expanduser().resolve()

    if not source.is_file():
        raise FileNotFoundError(f"Config not found: {source}")

    if source.name.casefold() not in {"lineage2ver413", "l2.ini"}:
        raise EncryptedConfigError(
            "Expected l2.ini or Lineage2Ver413."
        )

    if not decoder.is_file():
        raise FileNotFoundError(f"Decoder not found: {decoder}")

    if not 1 <= timeout <= 120:
        raise ValueError("Timeout must be between 1 and 120 seconds.")

    with tempfile.TemporaryDirectory(prefix="l2c6-decode-") as temp_dir:
        temp = Path(temp_dir)
        decoder_input = temp / "Lineage2Ver413"
        output = temp / "decoded.ini"

        # l2encdec expects this filename; only a temporary copy is renamed.
        decoder_input.write_bytes(source.read_bytes())
        errors = []

        for extra_args in ([], ["-l"]):
            output.unlink(missing_ok=True)
            command = [
                str(decoder),
                "-c", "decode",
                "-p", "413",
                "-o", str(output),
                *extra_args,
                str(decoder_input),
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
                errors.append(
                    detail or f"Decoder exit code: {result.returncode}"
                )

        raise EncryptedConfigError(
            "Could not decode a valid Lineage 2 INI. "
            + " | ".join(errors)
        )
