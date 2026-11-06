"""Device fixtures are JSON and ordinary files; tests never open block devices."""

from __future__ import annotations

import json
import os
import stat
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from winusb_forge.core import ForgeError
from winusb_forge.devices import (
    GIB,
    MIB,
    Device,
    DeviceDiscovery,
    PartitionPlanner,
    SafetyGuard,
)


class FakeRunner:
    def __init__(self, nodes):
        self.nodes = nodes
        self.commands = []

    def run(self, args, **kwargs):
        self.commands.append((args, kwargs))
        return json.dumps({"blockdevices": self.nodes})


@pytest.fixture
def hardware(tmp_path):
    dev = tmp_path / "dev"
    sys = tmp_path / "sys"
    dev.mkdir()
    (sys / "dev/block").mkdir(parents=True)

    def make(name="sdc", number="8:32", transport="usb", sequence=17):
        physical = sys / "devices" / ("usb1" if transport == "usb" else "pci0000:00") / name
        (physical / "holders").mkdir(parents=True)
        (physical / "diskseq").write_text(str(sequence))
        (sys / "dev/block" / number).symlink_to(physical)
        (dev / name).touch()
        return {
            "path": str(dev / name),
            "type": "disk",
            "tran": transport,
            "model": "Test drive",
            "vendor": "Fixture",
            "serial": "SERIAL-" + name,
            "size": 64 * GIB,
            "ro": False,
            "maj:min": number,
            "log-sec": 512,
            "mountpoints": [None],
        }

    def child(parent, name="sdc1", number="8:33", mounts=None, kind="part"):
        physical = sys / "devices/usb1" / name
        (physical / "holders").mkdir(parents=True)
        (sys / "dev/block" / number).symlink_to(physical)
        node = {
            "path": str(dev / name),
            "type": kind,
            "size": GIB,
            "maj:min": number,
            "mountpoints": [None] if mounts is None else mounts,
        }
        parent.setdefault("children", []).append(node)
        return node

    return dev, sys, make, child


def discover(hardware, nodes):
    dev, sys, _, _ = hardware
    return DeviceDiscovery(FakeRunner(nodes), sys, dev)


def good_device():
    return Device(
        path="/dev/sdc",
        model="Fixture",
        serial="ABC",
        size=64 * GIB,
        transport="usb",
        major_minor="8:32",
        diskseq=17,
        sys_path="/sys/devices/usb1/sdc",
        usb_ancestry=True,
    )


def test_usb_discovery_uses_sysfs_and_does_not_assume_sda(hardware):
    _, _, make, _ = hardware
    discovery = discover(hardware, [make()])
    device = discovery.list()[0]
    assert device.path.endswith("/sdc")
    assert device.diskseq == 17
    assert device.usb_ancestry
    SafetyGuard(discovery).validate(device)
    assert all(not kwargs.get("write") for _, kwargs in discovery.runner.commands)


def test_several_disks_same_model_are_distinguished(hardware):
    _, _, make, _ = hardware
    nodes = [make(), make("sdd", "8:48", sequence=18), make("sda", "8:0", "sata")]
    devices = discover(hardware, nodes).list()
    assert len(devices) == 3
    assert len({device.identity for device in devices}) == 3
    assert len([device for device in devices if device.transport == "usb"]) == 2


def test_no_disks(hardware):
    assert discover(hardware, []).list() == []


@pytest.mark.parametrize("mount", ["/", "/boot", "/boot/efi", "/home", "/media/user/USB", "[SWAP]"])
def test_all_mounted_descendants_rejected(hardware, mount):
    _, _, make, child = hardware
    parent = make()
    child(parent, mounts=[mount])
    discovery = discover(hardware, [parent])
    with pytest.raises(ForgeError):
        SafetyGuard(discovery).validate(discovery.list()[0])


def test_nested_lvm_root_is_rejected(hardware):
    _, _, make, child = hardware
    parent = make()
    partition = child(parent)
    child(partition, "dm-0", "253:0", ["/"], "lvm")
    discovery = discover(hardware, [parent])
    assert "/" in discovery.list()[0].mountpoints
    with pytest.raises(ForgeError):
        SafetyGuard(discovery).validate(discovery.list()[0])


@pytest.mark.parametrize("field", ["size", "ro", "maj:min", "mountpoints", "log-sec", "path"])
def test_incomplete_lsblk_fails_closed(hardware, field):
    _, _, make, _ = hardware
    node = make()
    del node[field]
    with pytest.raises(ForgeError):
        discover(hardware, [node]).list()


def test_bad_json_rejected(hardware):
    class Invalid:
        def run(self, args):
            return "not json"

    with pytest.raises(ForgeError):
        DeviceDiscovery(Invalid()).list()


def test_missing_diskseq_fails_closed(hardware):
    _, sys, make, _ = hardware
    node = make()
    (sys / "dev/block/8:32/diskseq").unlink()
    discovery = discover(hardware, [node])
    device = discovery.list()[0]
    assert device.diskseq is None
    with pytest.raises(ForgeError):
        SafetyGuard(discovery).validate(device)


def test_holder_blocks_unmounted_device(hardware):
    _, sys, make, _ = hardware
    node = make()
    (sys / "dev/block/8:32/holders/dm-0").touch()
    discovery = discover(hardware, [node])
    with pytest.raises(ForgeError):
        SafetyGuard(discovery).validate(discovery.list()[0])


@pytest.mark.parametrize(
    "change",
    [
        {"transport": "sata"},
        {"usb_ancestry": False},
        {"read_only": True},
        {"logical_sector": 4096},
        {"diskseq": None},
        {"holders": ("dm-0",)},
        {"mountpoints": ("[SWAP]",)},
    ],
)
def test_guard_rejects_unsafe_device(change):
    guard = SafetyGuard(None)
    with pytest.raises(ForgeError):
        guard.validate(replace(good_device(), **change))


def test_allow_only_writer_owned_mount():
    guard = SafetyGuard(None)
    device = replace(good_device(), mountpoints=("/run/forge/private",))
    guard.validate(device, allow_mounts=("/run/forge/private",))
    with pytest.raises(ForgeError):
        guard.validate(
            replace(device, mountpoints=("/run/forge/private", "/home")), ("/run/forge/private",)
        )


def test_read_only_verification_keeps_other_safeguards():
    device = replace(good_device(), read_only=True)
    discovery = SimpleNamespace(select=lambda path: device)
    guard = SafetyGuard(discovery)
    guard.validate(device, allow_read_only=True)
    assert guard.revalidate(device, allow_read_only=True) == device
    with pytest.raises(ForgeError):
        guard.revalidate(device)
    with pytest.raises(ForgeError):
        guard.validate(replace(device, mountpoints=("/",)), allow_read_only=True)


@pytest.mark.parametrize(
    "field,value", [("serial", "NEW"), ("diskseq", 18), ("size", 32 * GIB), ("major_minor", "8:48")]
)
def test_identity_changed_on_revalidation(field, value):
    original = good_device()
    discovery = SimpleNamespace(select=lambda path: replace(original, **{field: value}))
    with pytest.raises(ForgeError):
        SafetyGuard(discovery).revalidate(original)


def test_disconnected_during_revalidation():
    def gone(path):
        raise ForgeError("device_missing")

    with pytest.raises(ForgeError):
        SafetyGuard(SimpleNamespace(select=gone)).revalidate(good_device())


@pytest.mark.parametrize("answer", ["", "yes", "ERASE /dev/sdc", " ERASE /dev/sdc 17 68719476736"])
def test_confirmation_must_match_full_identity(answer):
    with pytest.raises(ForgeError):
        SafetyGuard(None).confirm(good_device(), answer)


def test_exact_confirmation():
    device = good_device()
    SafetyGuard(None).confirm(device, device.confirmation)


def test_select_by_id_and_block_device_number(hardware, monkeypatch):
    dev, _, make, _ = hardware
    node = make()
    directory = dev / "disk/by-id"
    directory.mkdir(parents=True)
    alias = directory / "usb-Test_SERIAL"
    alias.symlink_to(dev / "sdc")
    original_stat = Path.stat

    def fake_stat(path, *args, **kwargs):
        if path == dev / "sdc":
            return SimpleNamespace(st_mode=stat.S_IFBLK, st_rdev=os.makedev(8, 32))
        return original_stat(path, *args, **kwargs)

    monkeypatch.setattr(Path, "stat", fake_stat)
    device = discover(hardware, [node]).select(alias)
    assert device.path == str(dev / "sdc")
    assert str(alias) in device.by_id


def test_regular_file_rejected(hardware):
    dev, _, make, _ = hardware
    node = make()
    with pytest.raises(ForgeError):
        discover(hardware, [node]).select(dev / "sdc")


def test_missing_and_relative_device_rejected(hardware):
    discovery = discover(hardware, [])
    for path in ["sdc", "/dev/does-not-exist-forge"]:
        with pytest.raises(ForgeError):
            discovery.select(path)


@pytest.mark.parametrize("capacity", [16, 64, 128])
def test_partition_plan_visible_fat32_and_unallocated_capacity(capacity):
    device = replace(good_device(), size=capacity * GIB)
    plan = PartitionPlanner.plan(device, 6 * GIB)
    assert plan.start_sector == 2048
    assert plan.partition_bytes >= 6 * GIB + 512 * MIB
    assert plan.partition_bytes % MIB == 0
    assert plan.partition_bytes + MIB + plan.unallocated_bytes == device.size
    assert "label: dos" in plan.sfdisk_script
    assert "type=c" in plan.sfdisk_script
    assert "efi" not in plan.sfdisk_script


@pytest.mark.parametrize("content", [0, -1, True, 33 * GIB])
def test_invalid_or_oversized_content_rejected(content):
    with pytest.raises(ForgeError):
        PartitionPlanner.plan(good_device(), content)


def test_insufficient_capacity_rejected_before_format():
    with pytest.raises(ForgeError):
        PartitionPlanner.plan(replace(good_device(), size=4 * GIB), 4 * GIB)


def test_mbr_capacity_limit():
    with pytest.raises(ForgeError):
        PartitionPlanner.plan(replace(good_device(), size=3 * 1024 * GIB), GIB)


@pytest.mark.parametrize(
    "label", ["", "TOO_LONG_LABEL", "bad\nlabel", "bad;label", "small", "../BAD"]
)
def test_label_validation(label):
    with pytest.raises(ForgeError):
        PartitionPlanner.plan(good_device(), GIB, label)
