"""Bounded, read-only FAT32 extraction from an already pinned byte stream.

This parser never opens a device by name and never mounts a filesystem. Malformed
allocation chains, ambiguous names and unsafe paths fail closed.
"""

from __future__ import annotations

import struct
from collections.abc import Iterator
from pathlib import Path
from typing import BinaryIO

from .core import ForgeError
from .media import safe_relative


class Fat32Reader:
    """Extract a FAT32 partition without granting a kernel filesystem parser writes."""

    def __init__(self, stream: BinaryIO, offset: int, size: int):
        self.stream, self.offset, self.size = stream, offset, size
        if offset < 0 or size < 512:
            self._fail("invalid partition bounds")
        boot = self._read(0, 512)
        if boot[510:512] != b"\x55\xaa":
            self._fail("missing FAT boot signature")
        self.sector = struct.unpack_from("<H", boot, 11)[0]
        sectors_per_cluster = boot[13]
        reserved = struct.unpack_from("<H", boot, 14)[0]
        fats = boot[16]
        total = struct.unpack_from("<I", boot, 32)[0]
        fat_sectors = struct.unpack_from("<I", boot, 36)[0]
        flags, version = struct.unpack_from("<HH", boot, 40)
        self.root = struct.unpack_from("<I", boot, 44)[0]
        if (
            self.sector not in {512, 1024, 2048, 4096}
            or not 1 <= sectors_per_cluster <= 128
            or sectors_per_cluster & (sectors_per_cluster - 1)
            or reserved < 1
            or fats not in {1, 2}
            or not fat_sectors
            or version
            or any(boot[17:19])
            or any(boot[19:21])
            or any(boot[22:24])
            or total * self.sector > size
        ):
            self._fail("unsupported or invalid FAT32 boot parameters")
        fsinfo, backup = struct.unpack_from("<HH", boot, 48)
        for address in (fsinfo, backup):
            if address not in {0, 0xFFFF} and address >= reserved:
                self._fail("metadata sector lies outside reserved region")
        if backup not in {0, 0xFFFF}:
            if self._read(backup * self.sector, 512) != boot:
                self._fail("backup boot sector differs from primary")
        if fsinfo not in {0, 0xFFFF}:
            info = self._read(fsinfo * self.sector, 512)
            if (
                struct.unpack_from("<I", info, 0)[0] != 0x41615252
                or struct.unpack_from("<I", info, 484)[0] != 0x61417272
                or struct.unpack_from("<I", info, 508)[0] != 0xAA550000
            ):
                self._fail("invalid FAT32 FSInfo signatures")
        self.cluster_bytes = sectors_per_cluster * self.sector
        self.data_offset = (reserved + fats * fat_sectors) * self.sector
        self.cluster_count = (total * self.sector - self.data_offset) // self.cluster_bytes
        fat_bytes = fat_sectors * self.sector
        if (
            not 65525 <= self.cluster_count < 0x0FFFFFF5
            or fat_bytes < (self.cluster_count + 2) * 4
            or fat_bytes > 128 * 1024**2
            or not 2 <= self.root < self.cluster_count + 2
        ):
            self._fail("invalid FAT32 allocation geometry")
        active = flags & 0xF if flags & 0x80 else 0
        if active >= fats or flags & ~0x008F:
            self._fail("invalid FAT selection")
        self.fat = self._read((reserved + active * fat_sectors) * self.sector, fat_bytes)
        if not flags & 0x80:
            for index in range(1, fats):
                if (
                    self._read((reserved + index * fat_sectors) * self.sector, fat_bytes)
                    != self.fat
                ):
                    self._fail("FAT mirrors disagree")
        if self._fat_entry(0) < 0x0FFFFFF0 or self._fat_entry(1) < 0x0FFFFFF8:
            self._fail("invalid reserved FAT entries")
        self.claimed = bytearray((self.cluster_count + 9) // 8)
        self.entry_count = 0

    @staticmethod
    def _fail(detail: str) -> None:
        raise ForgeError("verification", detail)

    def _read(self, relative: int, count: int) -> bytes:
        if relative < 0 or count < 0 or relative + count > self.size:
            self._fail("read exceeds partition bounds")
        self.stream.seek(self.offset + relative)
        data = self.stream.read(count)
        if len(data) != count:
            self._fail("truncated FAT32 partition")
        return data

    def _fat_entry(self, cluster: int) -> int:
        return int(struct.unpack_from("<I", self.fat, cluster * 4)[0]) & 0x0FFFFFFF

    def _chain(self, first: int) -> Iterator[int]:
        current = first
        while True:
            if not 2 <= current < self.cluster_count + 2:
                self._fail("cluster outside data region")
            index, bit = divmod(current, 8)
            if self.claimed[index] & (1 << bit):
                self._fail("cyclic or cross-linked cluster chain")
            self.claimed[index] |= 1 << bit
            yield current
            current = self._fat_entry(current)
            if current >= 0x0FFFFFF8:
                return

    def _cluster(self, cluster: int) -> bytes:
        return self._read(self.data_offset + (cluster - 2) * self.cluster_bytes, self.cluster_bytes)

    @staticmethod
    def _short_name(entry: bytes) -> str:
        raw = entry[:11]
        if raw[0] == 0x05:
            raw = b"\xe5" + raw[1:]
        base = raw[:8].decode("cp437").rstrip(" ")
        extension = raw[8:].decode("cp437").rstrip(" ")
        if "." in base and not (base in {".", ".."} and not extension):
            raise ForgeError("verification", "invalid short filename")
        if entry[12] & 0x08:
            base = base.lower()
        if entry[12] & 0x10:
            extension = extension.lower()
        return base + ("." + extension if extension else "")

    def _long_name(self, fragments: list[bytes], entry: bytes) -> str:
        count = fragments[0][0] & 0x1F
        if not 1 <= count <= 20 or len(fragments) != count or fragments[0][0] != count | 0x40:
            self._fail("invalid long filename sequence")
        checksum = 0
        for byte in entry[:11]:
            checksum = (((checksum & 1) << 7) + (checksum >> 1) + byte) & 255
        for index, fragment in enumerate(fragments):
            expected = count - index | (0x40 if index == 0 else 0)
            if (
                fragment[0] != expected
                or fragment[13] != checksum
                or fragment[12]
                or any(fragment[26:28])
            ):
                self._fail("invalid long filename metadata")
        encoded = b"".join(part[1:11] + part[14:26] + part[28:32] for part in reversed(fragments))
        units = list(struct.unpack("<" + "H" * (len(encoded) // 2), encoded))
        if 0 in units:
            end = units.index(0)
            if any(unit != 0xFFFF for unit in units[end + 1 :]):
                self._fail("invalid long filename padding")
            units = units[:end]
        if not 1 <= len(units) <= 255 or 0xFFFF in units:
            self._fail("invalid long filename length")
        try:
            return struct.pack("<" + "H" * len(units), *units).decode("utf-16-le")
        except UnicodeError as exc:
            raise ForgeError("verification", "invalid UTF-16 filename") from exc

    def extract(self, destination: Path) -> None:
        """Extract into a private, empty directory; never overwrite an existing path."""
        if destination.is_symlink() or not destination.is_dir() or any(destination.iterdir()):
            self._fail("extraction requires an empty real directory")
        self._directory(self.root, destination, parent=0, depth=0)

    def _directory(self, first: int, destination: Path, parent: int, depth: int) -> None:
        if depth > 64:
            self._fail("directory nesting exceeds limit")
        fragments: list[bytes] = []
        seen: set[str] = set()
        children: list[tuple[int, Path]] = []
        ended = False
        directory_bytes = 0
        for cluster in self._chain(first):
            directory_bytes += self.cluster_bytes
            if directory_bytes > 16 * 1024**2:
                self._fail("directory exceeds safe parsing limit")
            data = self._cluster(cluster)
            for position in range(0, len(data), 32):
                entry = data[position : position + 32]
                if ended:
                    continue
                if entry[0] == 0:
                    if fragments:
                        self._fail("orphan long filename entries")
                    ended = True
                    continue
                if entry[0] == 0xE5:
                    fragments = []
                    continue
                if entry[11] == 0x0F:
                    fragments.append(entry)
                    if len(fragments) > 20:
                        self._fail("too many long filename fragments")
                    continue
                attributes = entry[11]
                if attributes & 0xC0 or attributes & 0x18 == 0x18:
                    self._fail("invalid directory entry attributes")
                if attributes & 0x08:
                    if fragments or depth:
                        self._fail("invalid volume label")
                    continue
                name = self._long_name(fragments, entry) if fragments else self._short_name(entry)
                fragments = []
                first_cluster = (struct.unpack_from("<H", entry, 20)[0] << 16) | struct.unpack_from(
                    "<H", entry, 26
                )[0]
                length = struct.unpack_from("<I", entry, 28)[0]
                if name in {".", ".."}:
                    if (
                        not attributes & 0x10
                        or length
                        or first_cluster != (first if name == "." else parent)
                    ):
                        self._fail("invalid dot directory reference")
                    continue
                safe_relative(name)
                if "/" in name or name.casefold() in seen:
                    self._fail("unsafe or duplicate FAT filename")
                seen.add(name.casefold())
                self.entry_count += 1
                if self.entry_count > 200000:
                    self._fail("too many directory entries")
                path = destination / name
                if attributes & 0x10:
                    if length:
                        self._fail("directory with nonzero file length")
                    path.mkdir(mode=0o700)
                    children.append((first_cluster, path))
                else:
                    self._file(first_cluster, length, path)
        if fragments:
            self._fail("orphan long filename entries")
        for cluster, path in children:
            self._directory(cluster, path, parent=first if depth else 0, depth=depth + 1)

    def _file(self, first: int, length: int, destination: Path) -> None:
        if not length and not first:
            destination.open("xb").close()
            return
        remaining = length
        with destination.open("xb") as stream:
            for cluster in self._chain(first):
                if remaining <= 0:
                    self._fail("file allocation exceeds declared length")
                data = self._cluster(cluster)[:remaining]
                stream.write(data)
                remaining -= len(data)
        if remaining:
            self._fail("file allocation shorter than declared length")
