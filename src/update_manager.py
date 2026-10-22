from __future__ import annotations

import hashlib
import json
import os
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path, PurePosixPath


class UpdateError(RuntimeError):
    """Manifest or file update failed safely."""


def _relative_path(value: str) -> PurePosixPath:
    if not isinstance(value, str) or not value or "\\" in value:
        raise UpdateError("Invalid manifest path.")
    path = PurePosixPath(value)
    if path.is_absolute() or any(p in ("", ".", "..") for p in path.parts):
        raise UpdateError("Unsafe manifest path.")
    if ":" in path.parts[0] or any(ord(c) < 32 for c in value):
        raise UpdateError("Unsafe manifest path.")
    return path


def _download(url: str, timeout: int, limit: int) -> bytes:
    parsed = urllib.parse.urlsplit(url)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username
        or parsed.password
    ):
        raise UpdateError("Download URL must use HTTPS without embedded credentials.")
    request = urllib.request.Request(
        url, headers={"User-Agent": "L2C6-Universal-Patcher/1"}
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            if response.status != 200:
                raise UpdateError(f"Download failed: HTTP {response.status}.")
            data = response.read(limit + 1)
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise UpdateError(f"Network download failed: {exc}") from exc
    if len(data) > limit:
        raise UpdateError("Downloaded data exceeds the allowed size.")
    return data


def fetch_manifest(manifest_url: str, timeout: int = 20) -> dict:
    parsed_manifest_url = urllib.parse.urlsplit(manifest_url)
    if (
        parsed_manifest_url.scheme != "https"
        or not parsed_manifest_url.hostname
        or parsed_manifest_url.username
        or parsed_manifest_url.password
    ):
        raise UpdateError("Manifest URL must use HTTPS without embedded credentials.")
    raw = _download(manifest_url, timeout, 2 * 1024 * 1024)
    try:
        manifest = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise UpdateError("Manifest is not valid UTF-8 JSON.") from exc
    if not isinstance(manifest, dict) or not isinstance(manifest.get("files"), list):
        raise UpdateError("Manifest has no valid files list.")
    for item in manifest["files"]:
        if not isinstance(item, dict):
            raise UpdateError("Invalid manifest file entry.")
        _relative_path(item.get("path"))
        size, digest, download = item.get("size"), item.get("sha256"), item.get("download")
        if type(size) is not int or size < 0:
            raise UpdateError("Invalid file size in manifest.")
        if not isinstance(digest, str) or len(digest) != 64 or any(
            c not in "0123456789abcdefABCDEF" for c in digest
        ):
            raise UpdateError("Invalid SHA-256 in manifest.")
        if not isinstance(download, str) or not download:
            raise UpdateError("Missing download path in manifest.")
        target_url = urllib.parse.urljoin(manifest_url, download)
        parsed_target = urllib.parse.urlsplit(target_url)
        if (
            parsed_target.scheme != "https"
            or parsed_target.netloc != parsed_manifest_url.netloc
            or parsed_target.username
            or parsed_target.password
        ):
            raise UpdateError("Cross-host downloads are not allowed.")
    return manifest


def update_files(
    manifest_url: str,
    client_root: Path,
    *,
    timeout: int = 30,
    max_file_size: int = 512 * 1024 * 1024,
) -> list[Path]:
    """Download, verify, then atomically install manifest files.

    Existing files are backed up before replacement. No client is modified
    until its downloaded file has passed size and SHA-256 validation.
    """
    client_root = Path(client_root).expanduser().resolve()
    manifest = fetch_manifest(manifest_url, timeout=min(timeout, 30))
    changed: list[Path] = []

    for item in manifest["files"]:
        rel = _relative_path(item["path"])
        size = item["size"]
        if size > max_file_size:
            raise UpdateError(f"File exceeds size limit: {rel}")
        destination = client_root.joinpath(*rel.parts)
        # Refuse symlinks anywhere in the destination path.
        cursor = client_root
        for part in rel.parts:
            cursor = cursor / part
            if cursor.is_symlink():
                raise UpdateError(f"Symlink destination refused: {rel}")
        resolved_parent = destination.parent.resolve()
        if resolved_parent != client_root and client_root not in resolved_parent.parents:
            raise UpdateError(f"Destination escapes client directory: {rel}")

        url = urllib.parse.urljoin(manifest_url, item["download"])
        parsed_url = urllib.parse.urlsplit(url)
        parsed_base = urllib.parse.urlsplit(manifest_url)
        if (
            parsed_url.scheme != "https"
            or parsed_url.netloc != parsed_base.netloc
            or parsed_url.username
            or parsed_url.password
        ):
            raise UpdateError("Download origin does not match the HTTPS manifest.")
        data = _download(url, timeout, max_file_size)
        if len(data) != size:
            raise UpdateError(f"Size verification failed: {rel}")
        digest = hashlib.sha256(data).hexdigest()
        if digest.lower() != item["sha256"].lower():
            raise UpdateError(f"SHA-256 verification failed: {rel}")

        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.exists() and destination.read_bytes() == data:
            continue

        backup = None
        if destination.exists():
            if not destination.is_file():
                raise UpdateError(f"Destination is not a regular file: {rel}")
            backup_dir = client_root / "patcher_backups"
            backup_dir.mkdir(exist_ok=True)
            backup = backup_dir / (str(rel).replace("/", "__") + ".pre-update")
            if backup.exists():
                backup = backup_dir / (
                    str(rel).replace("/", "__") + f".{hashlib.sha256(destination.read_bytes()).hexdigest()[:12]}.pre-update"
                )
            backup.write_bytes(destination.read_bytes())

        temp_name = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="wb", dir=destination.parent,
                prefix=".l2c6-update-", suffix=".tmp", delete=False
            ) as stream:
                temp_name = stream.name
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temp_name, destination)
            temp_name = None
        finally:
            if temp_name:
                Path(temp_name).unlink(missing_ok=True)
        if hashlib.sha256(destination.read_bytes()).hexdigest() != digest:
            if backup is not None:
                destination.write_bytes(backup.read_bytes())
            else:
                destination.unlink(missing_ok=True)
            raise UpdateError(f"Installed file verification failed: {rel}")
        changed.append(destination)

    return changed
