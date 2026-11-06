"""Read user-supplied F6 drivers without executing or modifying them."""

from __future__ import annotations

import hashlib
import os
import re
import stat
from dataclasses import dataclass
from pathlib import Path

from .core import ForgeError
from .media import FAT32_MAX, safe_relative, scan_tree


@dataclass(frozen=True)
class DriverInfo:
    root: Path
    files: tuple[str, ...]
    pci_ids: tuple[str, ...]
    name: str
    hashes: dict[str, str]


def _open_source(root: Path, name: str) -> int:
    """Walk every source component using no-follow directory descriptors."""
    parts = safe_relative(name).parts
    directory = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for part in parts[:-1]:
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=directory)
            os.close(directory)
            directory = child
        fd = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            os.close(fd)
            raise ForgeError("driver_invalid", "driver source is not a regular file")
        return fd
    finally:
        os.close(directory)


def decode_inf(raw: bytes) -> str:
    if not raw or len(raw) > 16 * 1024**2:
        raise ForgeError("driver_invalid", "INF is empty or exceeds 16 MiB")
    if raw.startswith((b"\xff\xfe", b"\xfe\xff")):
        encoding = "utf-16"
    elif b"\x00" in raw:
        # UTF-16 without BOM occurs in OEM packages. Reject odd-length data.
        if len(raw) % 2:
            raise ForgeError("driver_invalid", "malformed UTF-16 INF")
        encoding = "utf-16-le" if raw[1::2].count(0) > raw[::2].count(0) else "utf-16-be"
    else:
        try:
            return raw.decode("utf-8-sig")
        except UnicodeDecodeError:
            encoding = "cp1252"
    try:
        text = raw.decode(encoding)
    except UnicodeDecodeError as exc:
        raise ForgeError("driver_invalid", "unreadable INF encoding") from exc
    if "\x00" in text:
        raise ForgeError("driver_invalid", "INF contains NUL characters")
    return text


def inspect_drivers(path: Path) -> DriverInfo:
    path = path.expanduser().absolute()
    entries = scan_tree(path)
    infs = [file for key, file in entries.items() if key.endswith(".inf")]
    if not infs:
        raise ForgeError("driver_invalid", "no INF files found")
    if any(file.stat().st_size > FAT32_MAX for file in entries.values()):
        raise ForgeError("driver_invalid", "driver file exceeds FAT32")
    identifiers: set[str] = set()
    for inf in infs:
        with os.fdopen(_open_source(path, inf.relative_to(path).as_posix()), "rb") as stream:
            if os.fstat(stream.fileno()).st_size > 16 * 1024**2:
                raise ForgeError("driver_invalid", "INF exceeds 16 MiB")
            text = decode_inf(stream.read(16 * 1024**2 + 1))
        if not re.search(r"(?im)^\s*\[Version\]\s*(?:;.*)?$", text):
            raise ForgeError("driver_invalid", "INF lacks a Version section")
        # A storage F6 package must carry its binaries and signed catalogue.
        # Copying the complete source tree preserves SourceDisksFiles subfolders.
        sys_names = {
            match.group(1).strip().casefold()
            for match in re.finditer(r"(?i)([\w .+-]+\.sys)\b", text)
        }
        cats = {
            match.group(1).strip().strip('"').casefold()
            for match in re.finditer(r"(?im)^\s*CatalogFile(?:\.[\w.]+)?\s*=\s*([^;\r\n]+)", text)
        }
        available = {file.name.casefold() for file in entries.values() if file.stat().st_size > 0}
        if not sys_names or not sys_names.issubset(available):
            raise ForgeError("driver_invalid", "referenced SYS binaries are missing")
        if not cats or not cats.issubset(available):
            raise ForgeError("driver_invalid", "referenced CAT catalogues are missing")
        for vendor, device in re.findall(r"PCI\\VEN_([0-9a-f]{4})&DEV_([0-9a-f]{4})", text, re.I):
            identifiers.add(f"{vendor.upper()}:{device.upper()}")
    name = "Intel RST VMD" if "8086:467F" in identifiers else "Storage drivers"
    hashes = {}
    for file in entries.values():
        relative = file.relative_to(path).as_posix()
        with os.fdopen(_open_source(path, relative), "rb") as stream:
            hashes[relative] = hashlib.file_digest(stream, "sha256").hexdigest()
    return DriverInfo(
        path,
        tuple(sorted(file.relative_to(path).as_posix() for file in entries.values())),
        tuple(sorted(identifiers)),
        name,
        hashes,
    )


def add_drivers(source: Path, root: Path) -> DriverInfo:
    info = inspect_drivers(source)
    entries = scan_tree(root)
    if any(key == "drivers" or key.startswith("drivers/") for key in entries) or any(
        child.name.casefold() == "drivers" for child in root.iterdir()
    ):
        raise ForgeError("driver_invalid", "media already contains a DRIVERS directory")
    target = root / "DRIVERS" / "STORAGE"
    target.mkdir(parents=True)
    for name in info.files:
        destination = target / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        with os.fdopen(_open_source(info.root, name), "rb") as src, destination.open("xb") as dst:
            digest = hashlib.sha256()
            for block in iter(lambda: src.read(1024 * 1024), b""):
                digest.update(block)
                dst.write(block)
        if digest.hexdigest() != info.hashes[name]:
            raise ForgeError("driver_invalid", "driver source changed during copy")
    inspect_drivers(target)
    return info
