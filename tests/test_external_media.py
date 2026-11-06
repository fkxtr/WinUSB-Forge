"""Real archive/image tools, entirely synthetic files; no mounts or block devices."""

import os
import shutil
import struct
import subprocess
import xml.etree.ElementTree as ET

import pytest

from winusb_forge import media
from winusb_forge.core import Runner

pytestmark = pytest.mark.skipif(
    not all(shutil.which(tool) for tool in ("7z", "wimlib-imagex", "genisoimage")),
    reason="requires 7z, wimlib-imagex and genisoimage; uses synthetic media only",
)


def command(*args):
    return subprocess.run([str(arg) for arg in args], check=True, capture_output=True).stdout


def create_synthetic_iso(tmp_path, *, esd=False, large=False):
    root = tmp_path / "iso source"
    (root / "efi/boot").mkdir(parents=True)
    (root / "sources").mkdir()
    (root / "boot").mkdir()
    pe = bytearray(256)
    pe[:2] = b"MZ"
    struct.pack_into("<I", pe, 60, 64)
    pe[64:68] = b"PE\0\0"
    struct.pack_into("<H", pe, 68, 0x8664)
    struct.pack_into("<H", pe, 88, 0x20B)
    struct.pack_into("<H", pe, 156, 10)
    (root / "efi/boot/bootx64.efi").write_bytes(pe)
    (root / "boot/bcd").write_bytes(b"synthetic BCD (not bootable)")
    (root / "boot/boot.sdi").write_bytes(b"synthetic SDI (not bootable)")
    payload = tmp_path / "boot payload"
    payload.mkdir()
    (payload / "fixture.txt").write_text("nonproprietary integration fixture")
    command(
        "wimlib-imagex",
        "capture",
        payload,
        root / "sources/boot.wim",
        "WinPE fixture",
        "--check",
        "--compress=none",
    )
    command(
        "wimlib-imagex",
        "info",
        root / "sources/boot.wim",
        "1",
        "--image-property",
        "WINDOWS/ARCH=9",
    )
    if large:
        for index in range(3):
            (payload / f"resource-{index}.bin").write_bytes(os.urandom(700 * 1024))
    install = root / ("sources/install.esd" if esd else "sources/install.wim")
    options = ["--compress=LZMS", "--solid"] if esd else ["--compress=none"]
    command("wimlib-imagex", "capture", payload, install, "Edition one", "--check", *options)
    command("wimlib-imagex", "append", payload, install, "Edition two", "--check")
    for index in (1, 2):
        command("wimlib-imagex", "info", install, str(index), "--image-property", "WINDOWS/ARCH=9")
    iso = tmp_path / "Windows sintético ñ.iso"
    command("genisoimage", "-quiet", "-udf", "-J", "-R", "-o", iso, root)
    return iso


@pytest.mark.parametrize("esd", [False, True])
def test_real_udf_extract_and_wim_verify(tmp_path, esd):
    iso = create_synthetic_iso(tmp_path, esd=esd)
    result = media.Media(Runner()).prepare(iso, tmp_path / "prepared")
    assert result.image_kind == ("esd" if esd else "wim")
    image = result.root / f"sources/install.{result.image_kind}"
    xml = Runner().run(["wimlib-imagex", "info", str(image), "--xml"], encoding="utf-16")
    assert len(ET.fromstring(xml).findall("IMAGE")) == 2
    assert len(result.files) == 5


def test_real_split_preserves_all_indexes_and_verifies_parts(tmp_path, monkeypatch):
    iso = create_synthetic_iso(tmp_path, large=True)
    monkeypatch.setattr(media, "FAT32_MAX", 2 * 1024**2)
    monkeypatch.setattr(media, "SPLIT_MIB", 1)
    result = media.Media(Runner()).prepare(iso, tmp_path / "prepared")
    assert result.image_kind == "swm"
    assert not (result.root / "sources/install.wim").exists()
    parts = list((result.root / "sources").glob("install*.swm"))
    assert len(parts) > 1
    assert all(0 < path.stat().st_size <= media.FAT32_MAX for path in parts)
    xml = Runner().run(
        ["wimlib-imagex", "info", str(result.root / "sources/install.swm"), "--xml"],
        encoding="utf-16",
    )
    assert len(ET.fromstring(xml).findall("IMAGE")) == 2
