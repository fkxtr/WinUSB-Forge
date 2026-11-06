"""FAT image preparation and exclusive, identity-pinned USB writes.

Native filesystem tools only touch disposable regular files. Actual block-device
writes use one already-open descriptor, never a name reopened by a subprocess.
No device is mounted, and no host boot configuration is changed.
"""

from __future__ import annotations

import contextlib
import fcntl
import hashlib
import json
import os
import shutil
import stat
import struct
import tempfile
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO

from .core import ForgeError, Runner, unprivileged
from .devices import Device, DeviceDiscovery, PartitionPlanner, Plan, SafetyGuard
from .fat import Fat32Reader
from .media import PreparedMedia, inspect_tree, safe_relative

MIB = 1024 * 1024
BLOCK = 4 * MIB
MANIFEST = "WINUSB-FORGE.json"
BLKGETDISKSEQ = 0x80081280
BLKGETSIZE64 = 0x80081272
BLKFLSBUF = 0x1261
BLKRRPART = 0x125F
Progress = Callable[[int, int], None]


@dataclass(frozen=True)
class VerificationResult:
    files: int
    bytes_checked: int
    source_manifest: bool
    partition_type: str = "MBR 0x0C"
    filesystem: str = "FAT32"
    hardware_boot_tested: bool = False


def make_mbr(plan: Plan) -> bytes:
    """A single visible primary FAT32/LBA partition; no legacy boot code."""
    if not (2048 <= plan.start_sector < 2**32 and 0 < plan.sector_count < 2**32):
        raise ForgeError("partition_invalid")
    data = bytearray(512)
    data[440:444] = os.urandom(4)
    data[446:462] = struct.pack(
        "<B3sB3sII",
        0,
        b"\xfe\xff\xff",
        0x0C,
        b"\xfe\xff\xff",
        plan.start_sector,
        plan.sector_count,
    )
    data[510:512] = b"\x55\xaa"
    return bytes(data)


def read_mbr(stream: BinaryIO, disk_size: int) -> tuple[int, int]:
    stream.seek(0)
    data = stream.read(512)
    if len(data) != 512 or data[510:512] != b"\x55\xaa":
        raise ForgeError("verification", "missing MBR signature")
    partitions = [data[n : n + 16] for n in range(446, 510, 16)]
    if any(part != bytes(16) for part in partitions[1:]):
        raise ForgeError("verification", "exactly one primary partition required")
    boot, _, kind, _, start, count = struct.unpack("<B3sB3sII", partitions[0])
    if boot not in (0, 0x80) or kind != 0x0C or start < 2048 or count == 0:
        raise ForgeError("verification", "expected visible MBR type 0x0C partition")
    offset, size = start * 512, count * 512
    if offset + size > disk_size or size > 32 * 1024**3:
        raise ForgeError("verification", "partition extends outside supported bounds")
    return offset, size


def _check_hidden_sectors(stream: BinaryIO, expected: int, offset: int = 0) -> None:
    stream.seek(offset + 28)
    hidden = stream.read(4)
    if len(hidden) != 4 or struct.unpack("<I", hidden)[0] != expected:
        raise ForgeError("verification", "FAT hidden-sector count disagrees with MBR")


def _check_fd(fd: int, device: Device) -> None:
    info = os.fstat(fd)
    if not stat.S_ISBLK(info.st_mode):
        raise ForgeError("device_identity", "not a block device")
    if f"{os.major(info.st_rdev)}:{os.minor(info.st_rdev)}" != device.major_minor:
        raise ForgeError("device_changed")
    sequence, size = bytearray(8), bytearray(8)
    try:
        fcntl.ioctl(fd, BLKGETDISKSEQ, sequence, True)
        fcntl.ioctl(fd, BLKGETSIZE64, size, True)
    except OSError as error:
        raise ForgeError("device_identity", "kernel identity unavailable") from error
    if (
        struct.unpack("=Q", sequence)[0] != device.diskseq
        or struct.unpack("=Q", size)[0] != device.size
    ):
        raise ForgeError("device_changed")


@contextlib.contextmanager
def pinned_device(device: Device, guard: SafetyGuard, *, write: bool) -> Iterator[int]:
    guard.revalidate(device, allow_read_only=not write)
    flags = (os.O_RDWR if write else os.O_RDONLY) | os.O_EXCL | os.O_CLOEXEC | os.O_NOFOLLOW
    try:
        fd = os.open(device.path, flags)
    except OSError as error:
        raise ForgeError("device_busy", "cannot exclusively open device") from error
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        _check_fd(fd, device)
        guard.revalidate(device, allow_read_only=not write)
        yield fd
    finally:
        os.close(fd)


@contextlib.contextmanager
def _source(root: Path, name: str) -> Iterator[int]:
    """Pin regular source files without following links in any component."""
    parts = safe_relative(name).parts
    directory = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for part in parts[:-1]:
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=directory)
            os.close(directory)
            directory = child
        fd = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
        try:
            if not stat.S_ISREG(os.fstat(fd).st_mode):
                raise ForgeError("unsafe_path", "source must be a regular file")
            yield fd
        finally:
            os.close(fd)
    finally:
        os.close(directory)


def _manifest(files: dict[str, str]) -> bytes:
    return (
        json.dumps({"schema": 1, "files": files}, sort_keys=True, ensure_ascii=True) + "\n"
    ).encode()


def _verified_tree(
    root: Path, runner: Runner, expected: dict[str, str] | None = None
) -> VerificationResult:
    media = inspect_tree(root, runner)
    actual = dict(media.files)
    marker = [name for name in actual if name.casefold() == MANIFEST.casefold()]
    baseline = None
    if marker:
        path = root / marker[0]
        if path.stat().st_size > 16 * MIB:
            raise ForgeError("verification", "manifest exceeds size limit")
        try:
            document = json.loads(path.read_text(encoding="utf-8"))
            if document.get("schema") != 1 or not isinstance(document.get("files"), dict):
                raise ValueError("unsupported manifest")
            baseline = document["files"]
            if not all(isinstance(k, str) and isinstance(v, str) for k, v in baseline.items()):
                raise ValueError("invalid manifest")
        except (ValueError, AttributeError, UnicodeError) as error:
            raise ForgeError("verification", "invalid manifest") from error
        del actual[marker[0]]
        if baseline != actual:
            raise ForgeError("verification", "manifest checksum mismatch")
    if expected is not None and actual != expected:
        raise ForgeError("verification", "source checksum mismatch")
    return VerificationResult(len(actual), media.total_bytes, baseline is not None)


class Writer:
    def __init__(
        self,
        runner: Runner,
        discovery: DeviceDiscovery | None = None,
        guard: SafetyGuard | None = None,
    ) -> None:
        self.runner = runner
        self.discovery = discovery or DeviceDiscovery(runner)
        self.guard = guard or SafetyGuard(self.discovery)

    def _build_volume(self, media: PreparedMedia, plan: Plan, directory: Path) -> Path:
        # Both full volume allocation and a complete extracted verification tree
        # must fit. Sparse truncate alone would provide a misleading preflight.
        required = 2 * plan.partition_bytes + media.total_bytes + 64 * MIB
        if shutil.disk_usage(directory).free < required:
            raise ForgeError("staging_space", "need space for FAT32 image and verification copy")
        if any(name.casefold() == MANIFEST.casefold() for name in media.files):
            raise ForgeError("unsafe_path", "reserved WinUSB Forge manifest filename")
        volume = directory / "volume.fat"
        with volume.open("xb") as stream:
            stream.truncate(plan.partition_bytes)
        self.runner.run(
            ["mkfs.vfat", "-F", "32", "-h", str(plan.start_sector), "-n", plan.label, str(volume)]
        )
        directories: set[str] = set()
        for name in sorted(media.files):
            if any(ord(char) > 0xFFFF for char in name):
                raise ForgeError("unsafe_path", "non-BMP filenames are unsupported by mtools")
            for parent in reversed(Path(name).parents):
                relative = parent.as_posix()
                if relative != "." and relative not in directories:
                    self.runner.run(["mmd", "-i", str(volume), "::/" + relative])
                    directories.add(relative)
            with _source(media.root, name) as fd:
                self.runner.run(
                    ["mcopy", "-i", str(volume), f"/proc/self/fd/{fd}", "::/" + name],
                    pass_fds=(fd,),
                )
        manifest = directory / MANIFEST
        manifest.write_bytes(_manifest(media.files))
        self.runner.run(["mcopy", "-i", str(volume), str(manifest), "::/" + MANIFEST])
        self.runner.run(["fsck.fat", "-n", str(volume)])
        extracted = directory / "checked"
        extracted.mkdir()
        with volume.open("rb") as stream:
            Fat32Reader(stream, 0, plan.partition_bytes).extract(extracted)
        _verified_tree(extracted, self.runner, media.files)
        shutil.rmtree(extracted)
        return volume

    def _write_volume(
        self, volume: Path | BinaryIO, device: Device, plan: Plan, progress: Progress | None
    ) -> None:
        offset = plan.start_sector * 512
        total = plan.partition_bytes * 2
        done = 0
        source_fd = (
            os.open(volume, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
            if isinstance(volume, Path)
            else os.dup(volume.fileno())
        )
        with (
            os.fdopen(source_fd, "rb") as source,
            pinned_device(device, self.guard, write=True) as fd,
        ):
            info = os.fstat(source.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_size != plan.partition_bytes:
                raise ForgeError("verification", "FAT image is not the prepared regular file")
            # Stale GPT headers at either end must not survive an MBR conversion.
            # Write the new MBR last: an interrupted transfer has no valid new MBR.
            for position in (0, device.size - MIB):
                self._pwrite(fd, bytes(MIB), position, device)
            digest = hashlib.sha256()
            position = offset
            source.seek(0)
            remaining = plan.partition_bytes
            while remaining:
                block = source.read(min(BLOCK, remaining))
                if not block:
                    raise ForgeError("verification", "FAT image truncated")
                remaining -= len(block)
                digest.update(block)
                self._pwrite(fd, block, position, device)
                position += len(block)
                done += len(block)
                if progress:
                    progress(done, total)
            if position - offset != plan.partition_bytes or source.read(1):
                raise ForgeError("verification", "FAT image length changed")
            mbr = make_mbr(plan)
            self._pwrite(fd, mbr, 0, device)
            os.fsync(fd)
            # Flush and invalidate kernel block buffers before full readback.
            fcntl.ioctl(fd, BLKFLSBUF)
            result = hashlib.sha256()
            remaining = plan.partition_bytes
            position = offset
            while remaining:
                _check_fd(fd, device)
                block = os.pread(fd, min(BLOCK, remaining), position)
                if not block:
                    raise ForgeError("verification", "short device readback")
                result.update(block)
                remaining -= len(block)
                position += len(block)
                done += len(block)
                if progress:
                    progress(done, total)
            if result.digest() != digest.digest() or os.pread(fd, 512, 0) != mbr:
                raise ForgeError("verification", "device readback mismatch")
            _check_fd(fd, device)
            os.fsync(fd)
            fcntl.ioctl(fd, BLKRRPART)

    @staticmethod
    def _pwrite(fd: int, block: bytes, position: int, device: Device) -> None:
        view = memoryview(block)
        while view:
            _check_fd(fd, device)
            count = os.pwrite(fd, view, position)
            if count <= 0:
                raise ForgeError("write_failed", "short block-device write")
            view = view[count:]
            position += count

    def create(
        self,
        media: PreparedMedia,
        device: Device,
        plan: Plan,
        confirmation: str,
        progress: Progress | None = None,
    ) -> VerificationResult:
        if getattr(self.runner, "dry_run", False):
            raise ForgeError("dry_run_write")
        self.guard.confirm(device, confirmation)
        self.guard.revalidate(device)
        if plan != PartitionPlanner.plan(device, media.total_bytes, plan.label):
            raise ForgeError("partition_invalid", "plan does not match current media and device")
        if os.geteuid() != 0:
            raise ForgeError("permissions", "USB creation requires sudo")
        # Never elevate archive/filesystem parsers; only raw I/O needs root.
        with unprivileged():
            temporary = tempfile.TemporaryDirectory(prefix="winusb-forge-volume-")
            try:
                volume = self._build_volume(media, plan, Path(temporary.name))
            except BaseException:
                temporary.cleanup()
                raise
        try:
            # Freeze the user-owned image into an anonymous root-owned inode.
            # Re-verify this exact immutable snapshot before opening the USB.
            with tempfile.TemporaryFile(mode="w+b") as frozen:
                space = os.fstatvfs(frozen.fileno())
                if (
                    space.f_bavail * space.f_frsize
                    < plan.partition_bytes + media.total_bytes + 64 * MIB
                ):
                    raise ForgeError(
                        "staging_space", "insufficient space to freeze and verify image"
                    )
                with _source(volume.parent, volume.name) as source_fd:
                    if os.fstat(source_fd).st_size != plan.partition_bytes:
                        raise ForgeError("verification", "FAT image size changed")
                    remaining = plan.partition_bytes
                    while remaining:
                        block = os.read(source_fd, min(BLOCK, remaining))
                        if not block:
                            raise ForgeError("verification", "FAT image truncated")
                        frozen.write(block)
                        remaining -= len(block)
                    if os.read(source_fd, 1):
                        raise ForgeError("verification", "FAT image grew")
                frozen.flush()
                _check_hidden_sectors(frozen, plan.start_sector)
                with (
                    unprivileged(),
                    tempfile.TemporaryDirectory(prefix="winusb-forge-frozen-") as checked,
                ):
                    Fat32Reader(frozen, 0, plan.partition_bytes).extract(Path(checked))
                    _verified_tree(Path(checked), self.runner, media.files)
                try:
                    self._write_volume(frozen, device, plan, progress)
                except (OSError, ForgeError, KeyboardInterrupt) as error:
                    raise ForgeError(
                        "write_incomplete", "USB may be incomplete; recreate it before use"
                    ) from error
        finally:
            with unprivileged():
                temporary.cleanup()
        return VerificationResult(len(media.files), plan.partition_bytes, True)

    def verify(self, device: Device) -> VerificationResult:
        with pinned_device(device, self.guard, write=False) as fd:
            # The descriptor remains pinned while parsers run without privileges.
            with os.fdopen(os.dup(fd), "rb") as stream:
                offset, size = read_mbr(stream, device.size)
                _check_hidden_sectors(stream, offset // 512, offset)
                with (
                    unprivileged(),
                    tempfile.TemporaryDirectory(prefix="winusb-forge-verify-") as temporary,
                ):
                    root = Path(temporary)
                    if shutil.disk_usage(root).free < size + 64 * MIB:
                        raise ForgeError(
                            "staging_space", "verification needs up to the partition size"
                        )
                    Fat32Reader(stream, offset, size).extract(root)
                    result = _verified_tree(root, self.runner)
                _check_fd(fd, device)
                return result
