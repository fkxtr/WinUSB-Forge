import shutil
import struct
from pathlib import Path

import pytest

from winusb_forge import media
from winusb_forge.core import ForgeError


def loader(machine=0x8664):
    value = bytearray(256)
    value[:2] = b"MZ"
    struct.pack_into("<I", value, 60, 64)
    value[64:68] = b"PE\0\0"
    struct.pack_into("<H", value, 68, machine)
    struct.pack_into("<H", value, 88, 0x20B)
    struct.pack_into("<H", value, 156, 10)
    return bytes(value)


def fixture_tree(root, image="wim"):
    for name, data in {
        "efi/boot/bootx64.efi": loader(),
        "boot/bcd": b"BCD fixture",
        "boot/boot.sdi": b"SDI fixture",
        "sources/boot.wim": b"boot fixture",
        f"sources/install.{image}": b"install fixture",
    }.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    return root


class ImageRunner:
    def __init__(self, source=None):
        self.source = source
        self.calls = []
        self.arch = "9"
        self.fail_split = False

    def run(self, args, **kwargs):
        self.calls.append(args)
        if args[:2] == ["7z", "l"]:
            return "\n\n".join(
                f"Path = {path.relative_to(self.source).as_posix()}\n"
                f"Size = {path.stat().st_size}\nAttributes = A"
                for path in self.source.rglob("*")
                if path.is_file()
            )
        if args[:2] == ["7z", "x"]:
            destination = Path(next(arg[2:] for arg in args if arg.startswith("-o")))
            shutil.copytree(self.source, destination, dirs_exist_ok=True)
        if args[:2] == ["wimlib-imagex", "info"]:
            return (
                f"<WIM><IMAGE INDEX='1'><WINDOWS><ARCH>{self.arch}</ARCH></WINDOWS></IMAGE></WIM>"
            )
        if args[:2] == ["wimlib-imagex", "split"]:
            if self.fail_split:
                raise ForgeError("split_failed")
            Path(args[3]).write_bytes(b"split one")
            Path(args[3]).with_name("install2.swm").write_bytes(b"split two")
        return ""


@pytest.mark.parametrize("image", ["wim", "esd", "swm"])
def test_inspect_supported_images(tmp_path, image):
    result = media.inspect_tree(fixture_tree(tmp_path, image), ImageRunner())
    assert result.image_kind == image
    assert len(result.files) == 5
    assert result.total_bytes > 256


@pytest.mark.parametrize(
    "missing",
    [
        "efi/boot/bootx64.efi",
        "sources/boot.wim",
        "sources/install.wim",
        "boot/bcd",
        "boot/boot.sdi",
    ],
)
def test_missing_required_files(tmp_path, missing):
    fixture_tree(tmp_path)
    (tmp_path / missing).unlink()
    with pytest.raises(ForgeError):
        media.inspect_tree(tmp_path, ImageRunner())


@pytest.mark.parametrize(
    "name",
    [
        "/etc/passwd",
        "../escape",
        "foo/../escape",
        "NUL.txt",
        "a:b",
        "a\\b",
        "trailing.",
        "a//b",
        "bad\nfile",
    ],
)
def test_reject_unsafe_names(name):
    with pytest.raises(ForgeError):
        media.safe_relative(name)


def test_unicode_and_spaces(tmp_path):
    source = fixture_tree(tmp_path / "árbol fuente")
    iso = tmp_path / "Windows legítimo.iso"
    iso.write_bytes(b"fake ISO for simulated extractor")
    result = media.Media(ImageRunner(source)).prepare(iso, tmp_path / "prepared")
    assert result.image_kind == "wim"


def test_sha256_mismatch_stops_before_extract(tmp_path):
    iso = tmp_path / "image.iso"
    iso.write_bytes(b"untrusted")
    runner = ImageRunner()
    with pytest.raises(ForgeError):
        media.Media(runner).prepare(iso, tmp_path / "stage", "0" * 64)
    assert not runner.calls


def test_missing_iso(tmp_path):
    with pytest.raises(ForgeError):
        media.Media(ImageRunner()).prepare(tmp_path / "missing.iso", tmp_path / "stage")


def test_wrong_pe_architecture(tmp_path):
    fixture_tree(tmp_path)
    (tmp_path / "efi/boot/bootx64.efi").write_bytes(loader(0xAA64))
    with pytest.raises(ForgeError):
        media.inspect_tree(tmp_path, ImageRunner())


def test_wrong_windows_architecture(tmp_path):
    runner = ImageRunner()
    runner.arch = "12"
    with pytest.raises(ForgeError):
        media.inspect_tree(fixture_tree(tmp_path), runner)


def test_reject_symlink(tmp_path):
    fixture_tree(tmp_path)
    (tmp_path / "link").symlink_to("sources/boot.wim")
    with pytest.raises(ForgeError):
        media.scan_tree(tmp_path)


def test_case_collision(tmp_path):
    fixture_tree(tmp_path)
    (tmp_path / "Sources").mkdir()
    with pytest.raises(ForgeError):
        media.scan_tree(tmp_path)


def test_missing_split_part(tmp_path):
    fixture_tree(tmp_path, "swm")
    (tmp_path / "sources/install3.swm").write_bytes(b"part three")
    with pytest.raises(ForgeError):
        media.inspect_tree(tmp_path, ImageRunner())


def test_complete_split_image(tmp_path):
    fixture_tree(tmp_path, "swm")
    (tmp_path / "sources/install2.swm").write_bytes(b"part two")
    runner = ImageRunner()
    assert media.inspect_tree(tmp_path, runner).image_kind == "swm"
    assert any(
        arg.endswith("install2.swm")
        for call in runner.calls
        for arg in call
        if arg.startswith("--ref=")
    )


def test_reject_mixed_images(tmp_path):
    fixture_tree(tmp_path)
    (tmp_path / "sources/install.esd").write_bytes(b"extra image")
    with pytest.raises(ForgeError):
        media.inspect_tree(tmp_path, ImageRunner())


@pytest.mark.parametrize("image", ["wim", "esd"])
def test_oversized_image(tmp_path, monkeypatch, image):
    monkeypatch.setattr(media, "FAT32_MAX", 1024)
    source = fixture_tree(tmp_path / "source", image)
    (source / f"sources/install.{image}").write_bytes(b"x" * 2048)
    iso = tmp_path / "image.iso"
    iso.write_bytes(b"fixture")
    runner = ImageRunner(source)
    if image == "esd":
        with pytest.raises(ForgeError):
            media.Media(runner).prepare(iso, tmp_path / "stage")
        assert not any(call[:2] == ["wimlib-imagex", "split"] for call in runner.calls)
    else:
        result = media.Media(runner).prepare(iso, tmp_path / "stage")
        assert result.image_kind == "swm"
        assert not (result.root / "sources/install.wim").exists()
        assert (result.root / "sources/install2.swm").exists()


def test_split_failure_keeps_original_and_stops(tmp_path, monkeypatch):
    monkeypatch.setattr(media, "FAT32_MAX", 1024)
    source = fixture_tree(tmp_path / "source")
    (source / "sources/install.wim").write_bytes(b"x" * 2048)
    iso = tmp_path / "image.iso"
    iso.write_bytes(b"fixture")
    runner = ImageRunner(source)
    runner.fail_split = True
    with pytest.raises(ForgeError):
        media.Media(runner).prepare(iso, tmp_path / "stage")
    assert (tmp_path / "stage/sources/install.wim").exists()


@pytest.mark.parametrize(
    "listing",
    [
        "Path = ../escape\nSize = 10",
        "Path = link\nSymbolic Link = /etc/passwd\nSize = 10",
        "Path = link\nAttributes = lrwxrwxrwx\nSize = 10",
        "Path = A/file\nSize = 1\n\nPath = a/second\nSize = 2",
        "Path = same\nSize = 1\n\nPath = SAME\nSize = 2",
        "Path = file\nSize = -1",
        "",
    ],
)
def test_archive_validation(listing):
    with pytest.raises(ForgeError):
        media._archive_entries(listing)


def test_manifest_detects_content_changes(tmp_path):
    fixture_tree(tmp_path)
    before = media.inspect_tree(tmp_path, ImageRunner())
    (tmp_path / "boot/bcd").write_bytes(b"changed")
    after = media.inspect_tree(tmp_path, ImageRunner())
    assert before.files["boot/bcd"] != after.files["boot/bcd"]


def test_xml_dtd_rejected(tmp_path):
    class DtdRunner(ImageRunner):
        def run(self, args, **kwargs):
            if args[:2] == ["wimlib-imagex", "info"]:
                return '<!DOCTYPE WIM [<!ENTITY x "expanded">]><WIM>&x;</WIM>'
            return super().run(args, **kwargs)

    with pytest.raises(ForgeError, match="unsafe or oversized"):
        media.inspect_tree(fixture_tree(tmp_path), DtdRunner())


def test_iso_mutation_during_extraction_is_rejected(tmp_path):
    source = fixture_tree(tmp_path / "source")
    iso = tmp_path / "image.iso"
    iso.write_bytes(b"original")

    class ChangingRunner(ImageRunner):
        def run(self, args, **kwargs):
            if args[:2] == ["7z", "l"]:
                assert args[-1].startswith("/proc/self/fd/")
                assert kwargs["pass_fds"]
                iso.write_bytes(b"modified")
            return super().run(args, **kwargs)

    with pytest.raises(ForgeError, match="iso_changed"):
        media.Media(ChangingRunner(source)).prepare(iso, tmp_path / "stage", media.file_digest(iso))


def test_windows_uppercase_collision_rejected(tmp_path):
    (tmp_path / "ı").write_bytes(b"dotless i")
    (tmp_path / "I").write_bytes(b"capital i")
    with pytest.raises(ForgeError):
        media.scan_tree(tmp_path)


def test_non_bmp_media_name_rejected_before_fat_conversion():
    with pytest.raises(ForgeError):
        media.safe_relative("emoji-😀.txt")
