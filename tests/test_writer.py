"""USB operations are simulated using private regular files; never real devices."""

import contextlib
import dataclasses
import hashlib
import io
import os
import shutil
from unittest.mock import Mock

import pytest

from winusb_forge import writer
from winusb_forge.core import ForgeError, Runner
from winusb_forge.devices import Device, PartitionPlanner, Plan
from winusb_forge.media import PreparedMedia, inspect_tree


@pytest.fixture
def device():
    return Device(
        "/dev/sdz",
        "Fixture",
        "fixture-serial",
        8 * 1024**3,
        "usb",
        "8:240",
        83,
        sys_path="/sys/devices/usb1/fixture",
        usb_ancestry=True,
    )


@pytest.fixture
def guard():
    result = Mock()
    result.confirm.side_effect = lambda device, answer: (
        None if answer == device.confirmation else (_ for _ in ()).throw(ForgeError("confirmation"))
    )
    return result


def test_mbr_is_visible_type_c_one_partition(device):
    plan = PartitionPlanner.plan(device, 100)
    data = writer.make_mbr(plan)
    assert data[450] == 0x0C
    assert data[462:510] == bytes(48)
    assert writer.read_mbr(io.BytesIO(data), device.size) == (1024**2, plan.partition_bytes)


@pytest.mark.parametrize("offset, value", [(510, 0), (450, 0xEE), (450, 0xEF), (462, 1), (446, 1)])
def test_invalid_mbr_rejected(device, offset, value):
    data = bytearray(writer.make_mbr(PartitionPlanner.plan(device, 100)))
    data[offset] = value
    with pytest.raises(ForgeError, match="verification"):
        writer.read_mbr(io.BytesIO(data), device.size)


def test_partition_past_end_rejected(device):
    plan = PartitionPlanner.plan(device, 100)
    with pytest.raises(ForgeError, match="verification"):
        writer.read_mbr(io.BytesIO(writer.make_mbr(plan)), 1024**2)


def test_pinned_device_refuses_regular_file(tmp_path, device, guard):
    path = tmp_path / "regular"
    path.write_bytes(b"x")
    with pytest.raises(ForgeError, match="not a block device"):
        with writer.pinned_device(dataclasses.replace(device, path=str(path)), guard, write=True):
            pytest.fail("regular files must never pass production block-device pinning")


def test_source_rejects_symlinks_in_parents(tmp_path):
    root = tmp_path / "source"
    root.mkdir()
    secret = tmp_path / "elsewhere"
    secret.mkdir()
    (secret / "file").write_text("outside")
    (root / "linked").symlink_to(secret)
    with pytest.raises(OSError):
        with writer._source(root, "linked/file"):
            pytest.fail("symlink parent accepted")


@pytest.fixture
def simulated_disk(tmp_path, monkeypatch, device):
    # Private helper only: no production flag can authorize regular files.
    disk = tmp_path / "simulated-disk.bin"
    disk.write_bytes(b"G" * (8 * writer.MIB))
    volume = tmp_path / "volume.fat"
    volume.write_bytes(b"fixture\0" * (writer.MIB // 8))
    plan = Plan(device, 1, "WIN11", 2048, writer.MIB // 512, writer.MIB, 6 * writer.MIB)
    tiny_device = dataclasses.replace(device, size=8 * writer.MIB)
    checks = []
    monkeypatch.setattr(writer, "_check_fd", lambda fd, d: checks.append(fd))
    monkeypatch.setattr(writer.fcntl, "ioctl", lambda *args: 0)

    @contextlib.contextmanager
    def pin(*args, **kwargs):
        fd = os.open(disk, os.O_RDWR)
        try:
            yield fd
        finally:
            os.close(fd)

    monkeypatch.setattr(writer, "pinned_device", pin)
    return disk, volume, tiny_device, plan, checks


def test_simulated_full_write_flush_and_readback(simulated_disk, guard):
    disk, volume, device, plan, checks = simulated_disk
    progress = []
    writer.Writer(Runner(), guard=guard)._write_volume(
        volume, device, plan, lambda n, t: progress.append((n, t))
    )
    with disk.open("rb") as stream:
        assert writer.read_mbr(stream, device.size) == (writer.MIB, writer.MIB)
        stream.seek(writer.MIB)
        assert stream.read(writer.MIB) == volume.read_bytes()
        stream.seek(device.size - writer.MIB)
        assert stream.read() == bytes(writer.MIB)
    assert progress[-1] == (2 * writer.MIB, 2 * writer.MIB)
    assert len(checks) >= 5
    with pytest.raises(OSError):
        os.fstat(checks[-1])  # pinned descriptor always closed


def test_partial_writes_retried(simulated_disk, monkeypatch, guard):
    disk, volume, device, plan, checks = simulated_disk
    original = os.pwrite
    monkeypatch.setattr(writer.os, "pwrite", lambda fd, data, pos: original(fd, data[:7777], pos))
    writer.Writer(Runner(), guard=guard)._write_volume(volume, device, plan, None)
    assert len(checks) > 50
    with disk.open("rb") as stream:
        stream.seek(writer.MIB)
        assert (
            hashlib.sha256(stream.read(writer.MIB)).digest()
            == hashlib.sha256(volume.read_bytes()).digest()
        )


def test_disconnection_stops_before_mbr(simulated_disk, monkeypatch, guard):
    disk, volume, device, plan, _ = simulated_disk
    count = 0

    def check(fd, target):
        nonlocal count
        count += 1
        if count >= 3:
            raise ForgeError("device_changed")

    monkeypatch.setattr(writer, "_check_fd", check)
    with pytest.raises(ForgeError, match="device_changed"):
        writer.Writer(Runner(), guard=guard)._write_volume(volume, device, plan, None)
    assert disk.read_bytes()[510:512] != b"\x55\xaa"


def test_corrupt_readback_is_failure(simulated_disk, monkeypatch, guard):
    _, volume, device, plan, _ = simulated_disk
    original = os.pread
    monkeypatch.setattr(
        writer.os,
        "pread",
        lambda fd, length, offset: (
            b"x" * length if offset == writer.MIB else original(fd, length, offset)
        ),
    )
    with pytest.raises(ForgeError, match="readback mismatch"):
        writer.Writer(Runner(), guard=guard)._write_volume(volume, device, plan, None)


@pytest.mark.parametrize("operation", ["fsync", "ioctl"])
def test_sync_and_kernel_reread_failure(simulated_disk, monkeypatch, guard, operation):
    _, volume, device, plan, _ = simulated_disk

    def fail(*args):
        raise OSError("simulated flush failure")

    monkeypatch.setattr(writer.os if operation == "fsync" else writer.fcntl, operation, fail)
    with pytest.raises(OSError):
        writer.Writer(Runner(), guard=guard)._write_volume(volume, device, plan, None)


def test_create_dry_run_blocks_before_confirmation_or_writes(device, guard, tmp_path):
    media = PreparedMedia(tmp_path, 1, {"a": "b"}, "wim")
    with pytest.raises(ForgeError, match="dry_run_write"):
        writer.Writer(Runner(dry_run=True), guard=guard).create(
            media, device, PartitionPlanner.plan(device, 1), device.confirmation
        )
    guard.confirm.assert_not_called()
    guard.revalidate.assert_not_called()


def test_bad_confirmation_does_not_build(device, guard, tmp_path, monkeypatch):
    media = PreparedMedia(tmp_path, 1, {"a": "b"}, "wim")
    build = Mock()
    monkeypatch.setattr(writer.Writer, "_build_volume", build)
    with pytest.raises(ForgeError, match="confirmation"):
        writer.Writer(Runner(), guard=guard).create(
            media, device, PartitionPlanner.plan(device, 1), ""
        )
    build.assert_not_called()


def test_source_tree_manifest_tampering_detected(tmp_path, monkeypatch):
    (tmp_path / writer.MANIFEST).write_text('{"schema":1,"files":{"file":"wrong"}}')
    prepared = PreparedMedia(tmp_path, 5, {"file": "actual", writer.MANIFEST: "manifest"}, "wim")
    monkeypatch.setattr(writer, "inspect_tree", lambda *a: prepared)
    with pytest.raises(ForgeError, match="checksum mismatch"):
        writer._verified_tree(tmp_path, Runner())


def test_existing_media_without_manifest_is_structural_only(tmp_path, monkeypatch):
    prepared = PreparedMedia(tmp_path, 5, {"file": "actual"}, "wim")
    monkeypatch.setattr(writer, "inspect_tree", lambda *a: prepared)
    result = writer._verified_tree(tmp_path, Runner())
    assert not result.source_manifest
    assert not result.hardware_boot_tested


@pytest.mark.skipif(
    not all(
        shutil.which(tool)
        for tool in ("mkfs.vfat", "fsck.fat", "mcopy", "mmd", "wimlib-imagex", "genisoimage")
    ),
    reason="requires FAT, mtools and wimlib utilities",
)
def test_real_fat_build_with_synthetic_windows_tree(tmp_path, device):
    from test_external_media import create_synthetic_iso

    create_synthetic_iso(tmp_path)
    multilingual = tmp_path / "iso source" / "Español 安装"
    multilingual.mkdir()
    (multilingual / "documentación.txt").write_text("Unicode filename regression")
    prepared = inspect_tree(tmp_path / "iso source", Runner())
    build = tmp_path / "build"
    build.mkdir()
    volume = writer.Writer(Runner())._build_volume(
        prepared, PartitionPlanner.plan(device, prepared.total_bytes), build
    )
    assert volume.stat().st_size == 1024**3
    with volume.open("rb") as stream:
        assert stream.read(3) != bytes(3)


def test_growing_source_never_writes_beyond_partition(simulated_disk, monkeypatch, guard):
    disk, volume, device, plan, _ = simulated_disk
    original = writer.Writer._pwrite
    changed = False

    def extend_during_write(fd, block, position, target):
        nonlocal changed
        if position == writer.MIB and not changed:
            changed = True
            with volume.open("ab") as stream:
                stream.write(b"outside" * writer.MIB)
        original(fd, block, position, target)

    monkeypatch.setattr(writer.Writer, "_pwrite", staticmethod(extend_during_write))
    with pytest.raises(ForgeError, match="image length changed"):
        writer.Writer(Runner(), guard=guard)._write_volume(volume, device, plan, None)
    with disk.open("rb") as stream:
        stream.seek(2 * writer.MIB)
        assert stream.read(10) == b"G" * 10
    assert disk.read_bytes()[510:512] != b"\x55\xaa"


def test_create_freezes_and_reverifies_snapshot_before_device_open(
    tmp_path, monkeypatch, device, guard
):
    volume = tmp_path / "prepared.fat"
    volume.write_bytes(b"A" * writer.MIB)
    media = PreparedMedia(tmp_path, 1, {"file": "digest"}, "wim")
    plan = Plan(device, 1, "WIN11", 2048, 2048, writer.MIB, 1)
    monkeypatch.setattr(writer.PartitionPlanner, "plan", lambda *a: plan)
    monkeypatch.setattr(writer, "_check_hidden_sectors", Mock())
    monkeypatch.setattr(writer.os, "geteuid", lambda: 0)
    monkeypatch.setattr(writer, "unprivileged", contextlib.nullcontext)
    monkeypatch.setattr(writer.Writer, "_build_volume", lambda *a: volume)
    order = []

    class Reader:
        def __init__(self, stream, *args):
            self.stream = stream

        def extract(self, root):
            self.stream.seek(0)
            assert self.stream.read() == b"A" * writer.MIB
            order.append("frozen_checked")
            # User staging changed after snapshot; root-owned inode is unchanged.
            volume.write_bytes(b"B" * (2 * writer.MIB))

    monkeypatch.setattr(writer, "Fat32Reader", Reader)
    monkeypatch.setattr(writer, "_verified_tree", lambda *a: order.append("checksums_verified"))

    def write(self, source, *args):
        source.seek(0)
        assert source.read() == b"A" * writer.MIB
        order.append("write")

    monkeypatch.setattr(writer.Writer, "_write_volume", write)
    result = writer.Writer(Runner(), guard=guard).create(media, device, plan, device.confirmation)
    assert order == ["frozen_checked", "checksums_verified", "write"]
    assert result.source_manifest


def test_frozen_verification_failure_never_opens_device(tmp_path, monkeypatch, device, guard):
    volume = tmp_path / "prepared.fat"
    volume.write_bytes(b"A" * writer.MIB)
    media = PreparedMedia(tmp_path, 1, {"file": "digest"}, "wim")
    plan = Plan(device, 1, "WIN11", 2048, 2048, writer.MIB, 1)
    monkeypatch.setattr(writer.PartitionPlanner, "plan", lambda *a: plan)
    monkeypatch.setattr(writer, "_check_hidden_sectors", Mock())
    monkeypatch.setattr(writer.os, "geteuid", lambda: 0)
    monkeypatch.setattr(writer, "unprivileged", contextlib.nullcontext)
    monkeypatch.setattr(writer.Writer, "_build_volume", lambda *a: volume)
    reader = Mock()
    reader.return_value.extract.side_effect = ForgeError("verification", "corrupt frozen image")
    monkeypatch.setattr(writer, "Fat32Reader", reader)
    write = Mock()
    monkeypatch.setattr(writer.Writer, "_write_volume", write)
    with pytest.raises(ForgeError, match="corrupt frozen image"):
        writer.Writer(Runner(), guard=guard).create(media, device, plan, device.confirmation)
    write.assert_not_called()


@pytest.mark.parametrize(
    "failure", [ForgeError("verification"), OSError("sync failed"), KeyboardInterrupt()]
)
def test_write_failure_never_returns_success_and_closes_frozen_file(
    tmp_path, monkeypatch, device, guard, failure
):
    volume = tmp_path / "prepared.fat"
    volume.write_bytes(b"A" * writer.MIB)
    media = PreparedMedia(tmp_path, 1, {"file": "digest"}, "wim")
    plan = Plan(device, 1, "WIN11", 2048, 2048, writer.MIB, 1)
    monkeypatch.setattr(writer.PartitionPlanner, "plan", lambda *a: plan)
    monkeypatch.setattr(writer, "_check_hidden_sectors", Mock())
    monkeypatch.setattr(writer.os, "geteuid", lambda: 0)
    monkeypatch.setattr(writer, "unprivileged", contextlib.nullcontext)
    directories = []

    def build(self, media, plan, directory):
        directories.append(directory)
        return volume

    monkeypatch.setattr(writer.Writer, "_build_volume", build)
    monkeypatch.setattr(writer, "Fat32Reader", Mock())
    monkeypatch.setattr(writer, "_verified_tree", Mock())
    descriptors = []

    def write(self, source, *args):
        descriptors.append(source.fileno())
        raise failure

    monkeypatch.setattr(writer.Writer, "_write_volume", write)
    with pytest.raises(ForgeError, match="write_incomplete"):
        writer.Writer(Runner(), guard=guard).create(media, device, plan, device.confirmation)
    assert not directories[0].exists()
    with pytest.raises(OSError):
        os.fstat(descriptors[0])


def test_changed_frozen_hidden_sector_metadata_blocks_device_open(
    tmp_path, monkeypatch, device, guard
):
    volume = tmp_path / "prepared.fat"
    volume.write_bytes(bytes(writer.MIB))  # zero hidden sectors; planned start is 2048
    media = PreparedMedia(tmp_path, 1, {"file": "digest"}, "wim")
    plan = Plan(device, 1, "WIN11", 2048, 2048, writer.MIB, 1)
    monkeypatch.setattr(writer.PartitionPlanner, "plan", lambda *a: plan)
    monkeypatch.setattr(writer.os, "geteuid", lambda: 0)
    monkeypatch.setattr(writer, "unprivileged", contextlib.nullcontext)
    monkeypatch.setattr(writer.Writer, "_build_volume", lambda *a: volume)
    write, parse = Mock(), Mock()
    monkeypatch.setattr(writer.Writer, "_write_volume", write)
    monkeypatch.setattr(writer, "Fat32Reader", parse)
    with pytest.raises(ForgeError, match="hidden-sector count"):
        writer.Writer(Runner(), guard=guard).create(media, device, plan, device.confirmation)
    parse.assert_not_called()
    write.assert_not_called()


def test_source_fifo_rejected_without_blocking(tmp_path):
    os.mkfifo(tmp_path / "fifo")
    with pytest.raises(ForgeError, match="regular file"):
        with writer._source(tmp_path, "fifo"):
            pytest.fail("FIFO accepted")
