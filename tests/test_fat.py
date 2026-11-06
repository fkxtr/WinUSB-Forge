"""Corrupt-FAT regressions use sparse regular files, never block devices."""

import struct

import pytest

from winusb_forge.core import ForgeError
from winusb_forge.fat import Fat32Reader

SECTOR = 512
RESERVED = 32
FAT_SECTORS = 550
DATA_SECTOR = RESERVED + 2 * FAT_SECTORS
TOTAL = DATA_SECTOR + 70000


def put(stream, offset, data):
    stream.seek(offset)
    stream.write(data)


def entry(name=b"HELLO   TXT", cluster=3, length=5, attributes=0x20):
    record = bytearray(32)
    record[:11] = name
    record[11] = attributes
    struct.pack_into("<H", record, 20, cluster >> 16)
    struct.pack_into("<H", record, 26, cluster & 0xFFFF)
    struct.pack_into("<I", record, 28, length)
    return record


def set_fat(stream, cluster, value, mirrored=True):
    for index in range(2 if mirrored else 1):
        put(
            stream,
            (RESERVED + index * FAT_SECTORS) * SECTOR + cluster * 4,
            struct.pack("<I", value),
        )


@pytest.fixture
def volume(tmp_path):
    path = tmp_path / "volume.img"
    with path.open("w+b") as stream:
        stream.truncate(TOTAL * SECTOR)
        boot = bytearray(512)
        boot[510:512] = b"\x55\xaa"
        struct.pack_into("<H", boot, 11, 512)
        boot[13] = 1
        struct.pack_into("<H", boot, 14, RESERVED)
        boot[16] = 2
        struct.pack_into("<I", boot, 32, TOTAL)
        struct.pack_into("<I", boot, 36, FAT_SECTORS)
        struct.pack_into("<I", boot, 44, 2)
        put(stream, 0, boot)
        set_fat(stream, 0, 0xFFFFFF8)
        set_fat(stream, 1, 0xFFFFFFF)
        set_fat(stream, 2, 0xFFFFFFF)
        set_fat(stream, 3, 0xFFFFFFF)
        put(stream, DATA_SECTOR * SECTOR, entry())
        put(stream, (DATA_SECTOR + 1) * SECTOR, b"hello")
    return path


def extract(volume, tmp_path):
    destination = tmp_path / "extracted"
    destination.mkdir()
    with volume.open("rb") as stream:
        Fat32Reader(stream, 0, volume.stat().st_size).extract(destination)
    return destination


def test_extract_regular_file(volume, tmp_path):
    assert (extract(volume, tmp_path) / "HELLO.TXT").read_bytes() == b"hello"


@pytest.mark.parametrize("value", [0, 1, 0xFFFFFF7, 70002])
def test_invalid_clusters(volume, tmp_path, value):
    with volume.open("r+b") as stream:
        set_fat(stream, 3, value)
    with pytest.raises(ForgeError):
        extract(volume, tmp_path)


def test_cluster_cycle(volume, tmp_path):
    with volume.open("r+b") as stream:
        set_fat(stream, 3, 3)
    with pytest.raises(ForgeError):
        extract(volume, tmp_path)


def test_crosslinked_files(volume, tmp_path):
    with volume.open("r+b") as stream:
        put(stream, DATA_SECTOR * SECTOR + 32, entry(b"SECOND  TXT"))
    with pytest.raises(ForgeError, match="cross-linked"):
        extract(volume, tmp_path)


def test_fat_mirrors_disagree(volume, tmp_path):
    with volume.open("r+b") as stream:
        set_fat(stream, 3, 0xFFFFFF8, mirrored=False)
    with pytest.raises(ForgeError, match="mirrors"):
        extract(volume, tmp_path)


@pytest.mark.parametrize("length", [0, 513])
def test_file_length_mismatch(volume, tmp_path, length):
    with volume.open("r+b") as stream:
        put(stream, DATA_SECTOR * SECTOR, entry(length=length))
    with pytest.raises(ForgeError):
        extract(volume, tmp_path)


@pytest.mark.parametrize("name", [b"..      TXT", b"BAD/NAME   ", b"CON     TXT"])
def test_unsafe_filename(volume, tmp_path, name):
    with volume.open("r+b") as stream:
        put(stream, DATA_SECTOR * SECTOR, entry(name))
    with pytest.raises(ForgeError):
        extract(volume, tmp_path)


def test_case_collision(volume, tmp_path):
    with volume.open("r+b") as stream:
        put(stream, DATA_SECTOR * SECTOR + 32, entry(b"hello   txt", 0, 0))
    with pytest.raises(ForgeError):
        extract(volume, tmp_path)


def test_empty_file(volume, tmp_path):
    with volume.open("r+b") as stream:
        put(stream, DATA_SECTOR * SECTOR + 32, entry(b"EMPTY   TXT", 0, 0))
    assert (extract(volume, tmp_path) / "EMPTY.TXT").read_bytes() == b""


def lfn(name, short):
    checksum = 0
    for value in short:
        checksum = (((checksum & 1) << 7) + (checksum >> 1) + value) & 255
    encoded = name.encode("utf-16-le") + b"\0\0"
    count = (len(encoded) + 25) // 26
    encoded = encoded.ljust(count * 26, b"\xff")
    result = bytearray()
    for ordinal in range(count, 0, -1):
        record = bytearray(32)
        record[0] = ordinal | (0x40 if ordinal == count else 0)
        record[11] = 0x0F
        record[13] = checksum
        part = encoded[(ordinal - 1) * 26 : ordinal * 26]
        record[1:11], record[14:26], record[28:32] = part[:10], part[10:22], part[22:]
        result.extend(record)
    return result


def test_unicode_long_filename(volume, tmp_path):
    name = "Instalación 日本語 😀.txt"
    short = b"INSTAL~1TXT"
    with volume.open("r+b") as stream:
        put(stream, DATA_SECTOR * SECTOR, lfn(name, short) + entry(short))
    with pytest.raises(ForgeError, match="unsafe_path"):
        extract(volume, tmp_path)


def test_bad_lfn_checksum(volume, tmp_path):
    short = b"HELLO   TXT"
    data = lfn("hello world.txt", short)
    data[13] ^= 1
    with volume.open("r+b") as stream:
        put(stream, DATA_SECTOR * SECTOR, data + entry(short))
    with pytest.raises(ForgeError, match="metadata"):
        extract(volume, tmp_path)


def test_lfn_traversal(volume, tmp_path):
    short = b"HELLO   TXT"
    with volume.open("r+b") as stream:
        put(stream, DATA_SECTOR * SECTOR, lfn("../escape", short) + entry(short))
    with pytest.raises(ForgeError):
        extract(volume, tmp_path)
    assert not (tmp_path / "escape").exists()


def test_not_fat32(volume, tmp_path):
    with volume.open("r+b") as stream:
        put(stream, 17, b"\x01\x00")
    with pytest.raises(ForgeError):
        extract(volume, tmp_path)


def test_truncated_boot(tmp_path):
    volume = tmp_path / "broken.img"
    volume.write_bytes(b"\0" * 100)
    with pytest.raises(ForgeError):
        extract(volume, tmp_path)


def test_nested_directory(volume, tmp_path):
    with volume.open("r+b") as stream:
        put(stream, DATA_SECTOR * SECTOR + 32, entry(b"SOURCES    ", 4, 0, 0x10))
        set_fat(stream, 4, 0xFFFFFFF)
        data = (
            entry(b".          ", 4, 0, 0x10)
            + entry(b"..         ", 0, 0, 0x10)
            + entry(b"EMPTY   TXT", 0, 0)
        )
        put(stream, (DATA_SECTOR + 2) * SECTOR, data)
    assert (extract(volume, tmp_path) / "SOURCES" / "EMPTY.TXT").exists()


def test_existing_destination_refused(volume, tmp_path):
    destination = tmp_path / "destination"
    destination.mkdir()
    (destination / "keep").write_text("untouched")
    with volume.open("rb") as stream, pytest.raises(ForgeError):
        Fat32Reader(stream, 0, volume.stat().st_size).extract(destination)
    assert (destination / "keep").read_text() == "untouched"


def test_real_mtools_roundtrip(tmp_path):
    """Exercise real FAT tools with a disposable file; no mounts or block I/O."""
    import shutil
    import subprocess

    for command in ("mkfs.vfat", "mmd", "mcopy"):
        if shutil.which(command) is None:
            pytest.skip("optional FAT integration tools not installed")
    volume = tmp_path / "roundtrip.fat"
    with volume.open("wb") as stream:
        stream.truncate(128 * 1024**2)
    subprocess.run(["mkfs.vfat", "-F", "32", str(volume)], check=True)
    for directory in (
        "Fuentes",
        "Fuentes/Instalación 日本語",
        "Fuentes/Instalación 日本語/archivos",
    ):
        subprocess.run(["mmd", "-i", str(volume), "::/" + directory], check=True)
    cases = {
        "Fuentes/Instalación 日本語/archivos/Windows install 日本語.bin": bytes(range(256)) * 1000,
        "Fuentes/Instalación 日本語/archivos/empty.txt": b"",
        "123456789.txt": b"exact thirteen UTF16 units",
        "WINUSB-FORGE.json": b'{"schema": 1}',
    }
    for index, (name, content) in enumerate(cases.items()):
        source = tmp_path / str(index)
        source.write_bytes(content)
        subprocess.run(["mcopy", "-i", str(volume), str(source), "::/" + name], check=True)
    destination = extract(volume, tmp_path)
    for name, content in cases.items():
        assert (destination / name).read_bytes() == content


def test_invalid_fsinfo(volume, tmp_path):
    with volume.open("r+b") as stream:
        put(stream, 48, struct.pack("<H", 1))
    with pytest.raises(ForgeError, match="FSInfo"):
        extract(volume, tmp_path)


def test_backup_boot_mismatch(volume, tmp_path):
    with volume.open("r+b") as stream:
        put(stream, 50, struct.pack("<H", 6))
    with pytest.raises(ForgeError, match="backup"):
        extract(volume, tmp_path)
