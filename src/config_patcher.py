from __future__ import annotations

from pathlib import Path
import ipaddress
import re
import tempfile

from client_scanner import classify_config
from backup_manager import create_backup


def validate_server_address(address: str) -> str:
    address = address.strip()

    if not address or len(address) > 253:
        raise ValueError("Server address is empty or too long.")

    # Accept an IPv4/IPv6 literal or a DNS hostname, optionally with a port.
    host = address
    if address.startswith("[") and "]" in address:
        host = address[1:address.index("]")]
        suffix = address[address.index("]") + 1:]
        if suffix and not re.fullmatch(r":\d{1,5}", suffix):
            raise ValueError("Invalid port suffix.")
    elif address.count(":") == 1:
        possible_host, possible_port = address.rsplit(":", 1)
        if possible_port.isdigit():
            host = possible_host
            if not 1 <= int(possible_port) <= 65535:
                raise ValueError("Port must be between 1 and 65535.")
    elif address.count(":") > 1:
        host = address

    try:
        ipaddress.ip_address(host)
        return address
    except ValueError:
        pass

    if len(host) > 253 or not re.fullmatch(
        r"(?i)(?=.{1,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)(?:\.(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?))*\.?",
        host,
    ):
        raise ValueError("Enter a valid IP address or DNS hostname.")

    if ":" in address and address.count(":") == 1:
        port = address.rsplit(":", 1)[1]
        if port.isdigit() and not 1 <= int(port) <= 65535:
            raise ValueError("Port must be between 1 and 65535.")

    return address


def patch_plain_ini(
    config_path: Path,
    server_address: str,
    backup_dir: Path | None = None,
) -> Path:
    config_path = config_path.expanduser().resolve()
    if not config_path.is_file():
        raise FileNotFoundError(f"Config not found: {config_path}")

    if config_path.name.lower() != "l2.ini":
        raise ValueError("Only a plain l2.ini file is supported.")

    fmt = classify_config(config_path)
    if fmt != "plain_ini":
        raise ValueError(
            f"Refusing to edit config format '{fmt}'. No changes made."
        )

    server_address = validate_server_address(server_address)
    raw = config_path.read_bytes()
    text = raw.decode("utf-8-sig")

    # Require exactly one existing ServerAddr key; do not guess the INI section.
    matches = list(re.finditer(
        r"(?im)^(\s*ServerAddr\s*=\s*)([^;\r\n]*)([ \t]*(?:;[^\r\n]*)?)$",
        text,
    ))
    if len(matches) != 1:
        raise ValueError(
            f"Expected exactly one ServerAddr setting; found {len(matches)}. "
            "No changes made."
        )

    match = matches[0]
    updated = (
        text[:match.start()]
        + match.group(1) + server_address + match.group(3)
        + text[match.end():]
    )

    if updated == text:
        return config_path

    if backup_dir is None:
        backup_dir = config_path.parent / "backups"

    # Back up and validate before replacing the original file.
    create_backup([config_path], backup_dir)

    temp_name = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb", dir=config_path.parent,
            prefix=".l2ini-", suffix=".tmp", delete=False
        ) as temp:
            temp_name = temp.name
            temp.write(updated.encode("utf-8-sig" if raw.startswith(b"\xef\xbb\xbf") else "utf-8"))
            temp.flush()

        # Ensure the temporary output remains recognizable as plain INI.
        if classify_config(Path(temp_name)) != "plain_ini":
            raise RuntimeError("Validation failed; original file left unchanged.")

        Path(temp_name).replace(config_path)
    finally:
        if temp_name:
            Path(temp_name).unlink(missing_ok=True)

    return config_path


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Safely patch a plain Lineage 2 l2.ini")
    parser.add_argument("config", type=Path)
    parser.add_argument("server_address")
    parser.add_argument("--backup-dir", type=Path)
    args = parser.parse_args()

    try:
        result = patch_plain_ini(args.config, args.server_address, args.backup_dir)
        print(f"Config processed: {result}")
    except Exception as exc:
        raise SystemExit(f"Patch refused/failed: {exc}")
