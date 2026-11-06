"""Prepare and validate Windows media entirely in a disposable staging tree.

No function in this module opens a block device or mounts a filesystem.
"""

from __future__ import annotations

import hashlib
import os
import re
import shutil
import stat
import struct

# Bounded metadata only; DTD/entity declarations are forbidden before parsing.
import xml.etree.ElementTree as ET  # nosec B405
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from .core import ForgeError, Runner

FAT32_MAX = 4 * 1024**3 - 1
SPLIT_MIB = 3800
_RESERVED = re.compile(r"^(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\.|$)", re.I)


@dataclass(frozen=True)
class PreparedMedia:
    root: Path
    total_bytes: int
    files: dict[str, str]
    image_kind: str


def file_digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def safe_relative(name: str) -> PurePosixPath:
    """Validate a portable FAT/Windows filename before archive extraction."""
    if not name or "\\" in name or name.startswith("/"):
        raise ForgeError("unsafe_path", name)
    parts = name.split("/")
    if any(
        part in {"", ".", ".."}
        or part[-1:] in {" ", "."}
        or any(ord(char) > 0xFFFF for char in part)
        or len(part.encode("utf-16-le")) // 2 > 255
        or any(ord(char) < 32 or char in '<>:"|?*' for char in part)
        or _RESERVED.match(part)
        for part in parts
    ):
        raise ForgeError("unsafe_path", name)
    return PurePosixPath(name)


def scan_tree(root: Path) -> dict[str, Path]:
    """Reject links, special files, case aliases and unrepresentable paths."""
    if root.is_symlink() or not root.is_dir():
        raise ForgeError("unsafe_path", "media root must be a real directory")
    entries: dict[str, Path] = {}
    seen: set[str] = set()
    upper_seen: set[str] = set()

    def walk_error(error: OSError) -> None:
        raise error

    for current, directories, files in os.walk(root, followlinks=False, onerror=walk_error):
        for name in directories + files:
            path = Path(current) / name
            relative = path.relative_to(root).as_posix()
            safe_relative(relative)
            key = relative.casefold()
            if key in seen or relative.upper() in upper_seen:
                raise ForgeError("unsafe_path", "case-insensitive filename collision")
            seen.add(key)
            upper_seen.add(relative.upper())
            mode = path.lstat().st_mode
            if not stat.S_ISDIR(mode) and not stat.S_ISREG(mode):
                raise ForgeError("unsafe_path", "links and special files are unsupported")
            if stat.S_ISREG(mode):
                entries[key] = path
    return entries


def _x64_loader(path: Path) -> None:
    with path.open("rb") as stream:
        header = stream.read(64)
        if len(header) != 64 or header[:2] != b"MZ":
            raise ForgeError("iso_invalid", "UEFI loader is not a PE executable")
        offset = struct.unpack_from("<I", header, 60)[0]
        if offset < 64 or offset > path.stat().st_size - 94:
            raise ForgeError("iso_invalid", "invalid UEFI PE header")
        stream.seek(offset)
        pe = stream.read(94)
    if pe[:4] != b"PE\0\0" or struct.unpack_from("<H", pe, 4)[0] != 0x8664:
        raise ForgeError("architecture", "UEFI loader must be AMD64/x64")
    if struct.unpack_from("<H", pe, 24)[0] != 0x20B:
        raise ForgeError("architecture", "UEFI loader must use PE32+")
    if struct.unpack_from("<H", pe, 92)[0] != 10:
        raise ForgeError("iso_invalid", "UEFI loader must be an EFI application")


def _verify_image(path: Path, runner: Runner, refs: list[Path] | None = None) -> None:
    args = ["wimlib-imagex", "verify", str(path)]
    if refs:
        args.extend(f"--ref={reference}" for reference in refs)
    runner.run(args)
    xml = runner.run(["wimlib-imagex", "info", str(path), "--xml"], encoding="utf-16")
    try:
        if len(xml) > 16 * 1024**2 or re.search(r"<!\s*(?:DOCTYPE|ENTITY)", xml, re.I):
            raise ForgeError("iso_invalid", "unsafe or oversized WIM XML metadata")
        # Python 3.11+ Expat; no DTD/entity declarations, bounded input.
        document = ET.fromstring(xml.strip().lstrip("\ufeff"))  # nosec B314
        images = document.findall("IMAGE")
        if not images or any(image.findtext("WINDOWS/ARCH") != "9" for image in images):
            raise ForgeError("architecture", "all Windows image indexes must identify x64 (ARCH=9)")
    except ET.ParseError as exc:
        raise ForgeError("iso_invalid", "wimlib returned invalid image metadata") from exc


def inspect_tree(root: Path, runner: Runner, verify_images: bool = True) -> PreparedMedia:
    entries = scan_tree(root)
    for required in ("efi/boot/bootx64.efi", "sources/boot.wim", "boot/bcd", "boot/boot.sdi"):
        if required not in entries or entries[required].stat().st_size == 0:
            raise ForgeError("iso_invalid", f"missing or empty {required}")
    _x64_loader(entries["efi/boot/bootx64.efi"])
    images = [
        key
        for key in ("sources/install.wim", "sources/install.esd", "sources/install.swm")
        if key in entries
    ]
    if len(images) != 1:
        raise ForgeError(
            "iso_invalid", "exactly one install.wim, install.esd or install.swm is required"
        )
    selected = images[0]
    swms = {key for key in entries if re.fullmatch(r"sources/install(?:[0-9]+)?\.swm", key)}
    refs = None
    if selected.endswith(".swm"):
        expected = {"sources/install.swm"} | {
            f"sources/install{i}.swm" for i in range(2, len(swms) + 1)
        }
        if swms != expected:
            raise ForgeError(
                "iso_invalid", "split WIM parts must be contiguous and start with install.swm"
            )
        refs = [entries[key] for key in sorted(swms)]
    elif swms:
        raise ForgeError("iso_invalid", "mixed complete and split installation images")
    for path in entries.values():
        if path.stat().st_size > FAT32_MAX:
            raise ForgeError("file_too_large", path.relative_to(root).as_posix())
    if entries[selected].stat().st_size == 0:
        raise ForgeError("iso_invalid", "empty installation image")
    if verify_images:
        _verify_image(entries["sources/boot.wim"], runner)
        _verify_image(entries[selected], runner, refs)
    files = {path.relative_to(root).as_posix(): file_digest(path) for path in entries.values()}
    return PreparedMedia(
        root,
        sum(path.stat().st_size for path in entries.values()),
        files,
        selected.rsplit(".", 1)[1],
    )


def _archive_entries(listing: str) -> tuple[list[str], int]:
    """Parse 7-Zip's technical listing, rejecting links before extraction."""
    paths: list[str] = []
    files: list[str] = []
    seen: set[str] = set()
    total = 0
    for block in re.split(r"\r?\n\s*\r?\n", listing.strip("\r\n")):
        fields: dict[str, str] = {}
        for line in block.splitlines():
            if " = " not in line:
                raise ForgeError("iso_invalid", "ambiguous archive listing")
            key, value = line.split(" = ", 1)
            if key in fields:
                raise ForgeError("iso_invalid", "duplicate archive field")
            fields[key] = value
        if "Path" not in fields:
            continue
        name = fields["Path"]
        safe_relative(name)
        if name.casefold() in seen:
            raise ForgeError("unsafe_path", "duplicate archive path")
        seen.add(name.casefold())
        if any(
            key.casefold() in {"symbolic link", "hard link"} and value not in {"", "-"}
            for key, value in fields.items()
        ):
            raise ForgeError("unsafe_path", "archive contains a link")
        if fields.get("Folder") != "+" and fields.get("Links", "1") not in {"", "1"}:
            raise ForgeError("unsafe_path", "archive contains multiple links to a file")
        attributes = fields.get("Attributes", "")
        if re.search(r"(?:^|\s)[lbcps]", attributes) or fields.get("Encrypted") == "+":
            raise ForgeError("iso_invalid", "links, special files and encryption are unsupported")
        try:
            size = int(fields.get("Size") or "0")
        except ValueError as exc:
            raise ForgeError("iso_invalid", "invalid archive entry size") from exc
        if size < 0:
            raise ForgeError("iso_invalid", "negative archive entry size")
        total += size
        paths.append(name)
        if fields.get("Folder") != "+" and not attributes.startswith("D"):
            files.append(name)
    if not paths:
        raise ForgeError("iso_invalid", "archive listing is empty")
    # Detect file/parent aliases even when an archive omits directory records.
    canonical: dict[str, str] = {}
    uppercase: dict[str, str] = {}
    for name in paths:
        parts = PurePosixPath(name).parts
        for count in range(1, len(parts) + 1):
            prefix = "/".join(parts[:count])
            existing = canonical.setdefault(prefix.casefold(), prefix)
            existing_upper = uppercase.setdefault(prefix.upper(), prefix)
            if existing != prefix or existing_upper != prefix:
                raise ForgeError("unsafe_path", "case-insensitive directory collision")
    return files, total


class Media:
    def __init__(self, runner: Runner | None = None):
        self.runner = runner or Runner()

    def _extract(self, iso: Path, staging: Path, sha256: str | None) -> list[str]:
        # Pin the same inode for hashing, listing and extraction. Replacing the
        # pathname cannot substitute another ISO after checksum validation.
        fd = os.open(iso, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        try:
            initial = os.fstat(fd)
            if not stat.S_ISREG(initial.st_mode) or initial.st_size == 0:
                raise ForgeError("iso_missing", "ISO must be a nonempty regular file")
            if sha256 is not None:
                digest = hashlib.sha256()
                for block in iter(lambda: os.read(fd, 1024 * 1024), b""):
                    digest.update(block)
                os.lseek(fd, 0, os.SEEK_SET)
                if (
                    not re.fullmatch(r"[a-fA-F0-9]{64}", sha256)
                    or digest.hexdigest() != sha256.lower()
                ):
                    raise ForgeError("checksum", "ISO SHA-256 does not match")
            source = f"/proc/self/fd/{fd}"
            listing = self.runner.run(
                ["7z", "l", "-tUdf", "-slt", "-ba", "--", source], pass_fds=(fd,)
            )
            names, total = _archive_entries(listing)
            # Extraction and a simultaneous split output, plus filesystem overhead.
            required = total * 2 + 256 * 1024**2
            if shutil.disk_usage(staging).free < required:
                raise ForgeError(
                    "space", "insufficient staging space (up to twice extracted ISO size required)"
                )
            self.runner.run(
                ["7z", "x", "-tUdf", "-y", "-bd", f"-o{staging}", "--", source], pass_fds=(fd,)
            )
            after = os.fstat(fd)
            if (
                initial.st_dev,
                initial.st_ino,
                initial.st_size,
                initial.st_mtime_ns,
                initial.st_ctime_ns,
            ) != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns):
                raise ForgeError("iso_changed", "ISO changed while it was being inspected")
            return names
        finally:
            os.close(fd)

    def prepare(self, iso: Path, staging: Path, sha256: str | None = None) -> PreparedMedia:
        iso = iso.expanduser().absolute()
        if iso.is_symlink() or not iso.is_file() or iso.stat().st_size == 0:
            raise ForgeError("iso_missing", "ISO must be a nonempty regular file")
        if staging.is_symlink() or (staging.exists() and any(staging.iterdir())):
            raise ForgeError("unsafe_path", "staging directory must be empty")
        staging.mkdir(parents=True, exist_ok=True, mode=0o700)
        names = self._extract(iso, staging, sha256)
        entries = scan_tree(staging)
        listed = {item.casefold() for item in names}
        if set(entries) != listed:
            raise ForgeError("iso_invalid", "extracted files differ from archive listing")
        esd = entries.get("sources/install.esd")
        if esd and esd.stat().st_size > FAT32_MAX:
            raise ForgeError(
                "esd_too_large", "ESD exceeds FAT32; supply an official ISO with a WIM image"
            )
        wim = entries.get("sources/install.wim")
        if wim and wim.stat().st_size > FAT32_MAX:
            if esd or any(re.fullmatch(r"sources/install(?:[0-9]+)?\.swm", key) for key in entries):
                raise ForgeError("iso_invalid", "ambiguous installation images")
            _verify_image(wim, self.runner)
            output = wim.with_name("install.swm")
            self.runner.run(
                ["wimlib-imagex", "split", str(wim), str(output), str(SPLIT_MIB), "--check"]
            )
            parts = sorted(wim.parent.glob("install*.swm"))
            if not parts or any(
                not path.is_file() or path.stat().st_size == 0 or path.stat().st_size > FAT32_MAX
                for path in parts
            ):
                raise ForgeError(
                    "split_failed", "split WIM output is missing, empty or exceeds FAT32"
                )
            _verify_image(output, self.runner, parts)
            wim.unlink()
        return inspect_tree(staging, self.runner)
