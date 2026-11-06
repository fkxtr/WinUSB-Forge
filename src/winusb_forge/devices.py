"""Conservative block-device discovery and an MBR/FAT32 partition planner.

All operations in this module are read-only. A device name is never its identity:
the kernel disk sequence number distinguishes unplug/replug, including devices
whose firmware provides no serial number. The writer must additionally pin an
exclusive block-device descriptor and check its kernel identity.
"""

from __future__ import annotations

import json
import os
import re
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .core import ForgeError, Runner

MIB = 1024**2
GIB = 1024**3
MAX_PARTITION_BYTES = 32 * GIB
_MAJOR_MINOR = re.compile(r"^[0-9]+:[0-9]+$")


@dataclass(frozen=True)
class Partition:
    path: str
    major_minor: str
    size: int
    kind: str
    fstype: str
    mountpoints: tuple[str, ...]


@dataclass(frozen=True)
class Device:
    path: str
    model: str
    serial: str
    size: int
    transport: str
    major_minor: str
    diskseq: int | None
    logical_sector: int = 512
    read_only: bool = False
    mountpoints: tuple[str, ...] = ()
    partitions: tuple[Partition, ...] = ()
    holders: tuple[str, ...] = ()
    sys_path: str = ""
    by_id: tuple[str, ...] = ()
    usb_ancestry: bool = False
    vendor: str = ""

    @property
    def identity(self) -> tuple[object, ...]:
        return (
            self.major_minor,
            self.diskseq,
            self.sys_path,
            self.serial,
            self.size,
            self.model,
            self.transport,
            self.logical_sector,
        )

    @property
    def confirmation(self) -> str:
        return f"ERASE {self.path} {self.diskseq} {self.size}"


def _integer(value: object, field: str) -> int:
    if isinstance(value, bool):
        raise ForgeError("device_data", field)
    try:
        return int(str(value))
    except (ValueError, TypeError) as exc:
        raise ForgeError("device_data", field) from exc


def _boolean(value: object, field: str) -> bool:
    if value in (True, 1, "1"):
        return True
    if value in (False, 0, "0"):
        return False
    raise ForgeError("device_data", field)


def _mounts(node: dict[str, Any]) -> tuple[str, ...]:
    # MOUNTPOINTS includes [SWAP], unlike a simplistic mount-directory check.
    value = node.get("mountpoints")
    if not isinstance(value, list):
        raise ForgeError("device_data", "mountpoints")
    if any(item is not None and not isinstance(item, str) for item in value):
        raise ForgeError("device_data", "mountpoints")
    return tuple(item for item in value if item)


def _descendants(node: dict[str, Any]) -> list[dict[str, Any]]:
    children = node.get("children", [])
    if not isinstance(children, list) or any(not isinstance(x, dict) for x in children):
        raise ForgeError("device_data", "children")
    result = []
    for child in children:
        result.append(child)
        result.extend(_descendants(child))
    return result


class DeviceDiscovery:
    """Read util-linux JSON and corroborate it against the kernel's sysfs tree."""

    def __init__(
        self,
        runner: Runner,
        sys_root: Path = Path("/sys"),
        dev_root: Path = Path("/dev"),
    ) -> None:
        self.runner = runner
        self.sys_root = sys_root
        self.dev_root = dev_root

    def _kernel_info(
        self, major_minor: str, descendants: list[dict[str, Any]]
    ) -> tuple[int | None, str, bool, tuple[str, ...]]:
        try:
            path = (self.sys_root / "dev/block" / major_minor).resolve(strict=True)
            path.relative_to(self.sys_root.resolve())
            seq = int((path / "diskseq").read_text().strip())
            if seq < 1:
                raise ValueError("invalid diskseq")
            holders: list[str] = []
            for number in [major_minor] + [str(x.get("maj:min", "")) for x in descendants]:
                if not _MAJOR_MINOR.fullmatch(number):
                    raise ValueError("invalid major/minor")
                holder_dir = self.sys_root / "dev/block" / number / "holders"
                holders.extend(entry.name for entry in holder_dir.iterdir())
            usb = any(re.fullmatch(r"usb[0-9]+", part) for part in path.parts)
            return seq, str(path), usb, tuple(sorted(set(holders)))
        except (OSError, ValueError):
            # A disappearing disk, inaccessible holders, or an old kernel must
            # be displayed as unverified, never silently authorized for writing.
            return None, "", False, ("identity-unavailable",)

    def _aliases(self, path: str) -> tuple[str, ...]:
        directory = self.dev_root / "disk/by-id"
        try:
            return tuple(
                sorted(
                    str(item)
                    for item in directory.iterdir()
                    if item.is_symlink() and str(item.resolve()) == path
                )
            )
        except OSError:
            return ()

    def list(self) -> list[Device]:
        output = self.runner.run(
            [
                "lsblk",
                "--json",
                "--bytes",
                "--paths",
                "--output",
                "NAME,PATH,TYPE,TRAN,MODEL,VENDOR,SERIAL,SIZE,RO,MAJ:MIN,LOG-SEC,MOUNTPOINTS,FSTYPE,PARTTYPE",
            ]
        )
        try:
            document = json.loads(output)
            nodes = document["blockdevices"]
        except (json.JSONDecodeError, KeyError, TypeError) as exc:
            raise ForgeError("device_data", "lsblk JSON") from exc
        if not isinstance(nodes, list):
            raise ForgeError("device_data", "blockdevices")
        devices = []
        seen = set()
        for node in nodes:
            if not isinstance(node, dict):
                raise ForgeError("device_data", "blockdevices")
            if node.get("type") != "disk":
                continue
            path = node.get("path")
            number = node.get("maj:min")
            if (
                not isinstance(path, str)
                or Path(path).parent != self.dev_root
                or not isinstance(number, str)
                or not _MAJOR_MINOR.fullmatch(number)
                or number in seen
            ):
                raise ForgeError("device_data", "device identity")
            seen.add(number)
            descendants = _descendants(node)
            mounts = list(_mounts(node))
            partitions = []
            for child in descendants:
                child_mounts = _mounts(child)
                mounts.extend(child_mounts)
                partitions.append(
                    Partition(
                        path=str(child.get("path", "")),
                        major_minor=str(child.get("maj:min", "")),
                        size=_integer(child.get("size"), "partition size"),
                        kind=str(child.get("parttype") or ""),
                        fstype=str(child.get("fstype") or ""),
                        mountpoints=child_mounts,
                    )
                )
            seq, sys_path, usb, holders = self._kernel_info(number, descendants)
            devices.append(
                Device(
                    path=path,
                    model=str(node.get("model") or "").strip(),
                    serial=str(node.get("serial") or "").strip(),
                    size=_integer(node.get("size"), "size"),
                    transport=str(node.get("tran") or "").lower(),
                    major_minor=number,
                    diskseq=seq,
                    logical_sector=_integer(node.get("log-sec"), "logical sector"),
                    read_only=_boolean(node.get("ro"), "read-only"),
                    mountpoints=tuple(sorted(set(mounts))),
                    partitions=tuple(partitions),
                    holders=holders,
                    sys_path=sys_path,
                    by_id=self._aliases(path),
                    usb_ancestry=usb,
                    vendor=str(node.get("vendor") or "").strip(),
                )
            )
        return devices

    def select(self, path: str | Path) -> Device:
        selected = Path(path)
        if not selected.is_absolute():
            raise ForgeError("device_path", "absolute device path required")
        try:
            selected = selected.resolve(strict=True)
            info = selected.stat()
        except OSError as exc:
            raise ForgeError("device_missing") from exc
        if selected.parent != self.dev_root or not stat.S_ISBLK(info.st_mode):
            raise ForgeError("device_path", "whole block device required")
        matches = [device for device in self.list() if device.path == str(selected)]
        if len(matches) != 1:
            raise ForgeError("device_missing", "whole disk required")
        device = matches[0]
        if device.major_minor != f"{os.major(info.st_rdev)}:{os.minor(info.st_rdev)}":
            raise ForgeError("device_changed")
        return device


class SafetyGuard:
    def __init__(self, discovery: DeviceDiscovery) -> None:
        self.discovery = discovery

    def validate(
        self,
        device: Device,
        allow_mounts: tuple[str, ...] = (),
        *,
        allow_read_only: bool = False,
    ) -> None:
        if device.transport != "usb" or not device.usb_ancestry:
            raise ForgeError("device_internal")
        if device.diskseq is None or device.diskseq < 1 or not device.sys_path:
            raise ForgeError("device_identity")
        if not _MAJOR_MINOR.fullmatch(device.major_minor) or device.size <= 0:
            raise ForgeError("device_identity")
        if device.logical_sector != 512:
            raise ForgeError("device_sector", "512-byte logical sectors required")
        if device.read_only and not allow_read_only:
            raise ForgeError("device_read_only")
        if device.holders:
            raise ForgeError("device_busy", "active block-device holders")
        if any(mount not in allow_mounts for mount in device.mountpoints):
            raise ForgeError("device_busy", "mounted filesystem or active swap")

    def revalidate(
        self,
        device: Device,
        allow_mounts: tuple[str, ...] = (),
        *,
        allow_read_only: bool = False,
    ) -> Device:
        current = self.discovery.select(device.path)
        if current.identity != device.identity:
            raise ForgeError("device_changed")
        self.validate(current, allow_mounts=allow_mounts, allow_read_only=allow_read_only)
        return current

    def confirm(self, device: Device, answer: str) -> None:
        if answer != device.confirmation:
            raise ForgeError("confirmation")


@dataclass(frozen=True)
class Plan:
    device: Device
    content_bytes: int
    label: str
    start_sector: int
    sector_count: int
    partition_bytes: int
    unallocated_bytes: int

    @property
    def sfdisk_script(self) -> str:
        return (
            "label: dos\nunit: sectors\n\n"
            f"start={self.start_sector}, size={self.sector_count}, type=c\n"
        )


class PartitionPlanner:
    """One visible MBR 0x0C partition; unused capacity is reported explicitly."""

    @staticmethod
    def plan(device: Device, content_bytes: int, label: str = "WIN11") -> Plan:
        if not re.fullmatch(r"[A-Z0-9_]{1,11}", label):
            raise ForgeError("label", "1–11 uppercase letters, numbers or underscores")
        if (
            isinstance(content_bytes, bool)
            or not isinstance(content_bytes, int)
            or content_bytes < 1
        ):
            raise ForgeError("capacity", "empty content")
        if device.logical_sector != 512:
            raise ForgeError("device_sector", "512-byte logical sectors required")
        # Reserve filesystem metadata plus practical copy overhead. Driver and
        # split-image sizes must already be included in the staged content total.
        margin = max(512 * MIB, (content_bytes + 9) // 10)
        needed = max(GIB, ((content_bytes + margin + MIB - 1) // MIB) * MIB)
        if needed > MAX_PARTITION_BYTES:
            raise ForgeError("capacity", "content exceeds the 32 GiB FAT32 policy")
        if device.size < needed + MIB:
            raise ForgeError("capacity", "USB is too small")
        # MBR uses 32-bit LBAs. Using a small leading partition is not a valid
        # reason to accept devices whose complete addressing exceeds that limit.
        if device.size // 512 > 2**32:
            raise ForgeError("capacity", "device exceeds MBR address range")
        return Plan(
            device=device,
            content_bytes=content_bytes,
            label=label,
            start_sector=MIB // 512,
            sector_count=needed // 512,
            partition_bytes=needed,
            unallocated_bytes=device.size - MIB - needed,
        )
