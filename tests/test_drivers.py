from pathlib import Path

import pytest

from winusb_forge.core import ForgeError
from winusb_forge.drivers import add_drivers, decode_inf, inspect_drivers

INF = """[Version]
Signature="$Windows NT$"
CatalogFile=iaStorVD.cat
[SourceDisksFiles]
iaStorVD.sys=1
[Devices]
%Device%=Install,PCI\\VEN_8086&DEV_467F
"""


def package(root: Path, encoding="utf-8"):
    root.mkdir(parents=True, exist_ok=True)
    (root / "iaStorVD.inf").write_bytes(INF.encode(encoding))
    (root / "iaStorVD.sys").write_bytes(b"fixture binary")
    (root / "iaStorVD.cat").write_bytes(b"fixture catalogue")
    return root


@pytest.mark.parametrize(
    "encoding", ["utf-8", "utf-8-sig", "utf-16", "utf-16-le", "utf-16-be", "cp1252"]
)
def test_inf_encodings(tmp_path, encoding):
    info = inspect_drivers(package(tmp_path, encoding))
    assert info.pci_ids == ("8086:467F",)
    assert info.name == "Intel RST VMD"


@pytest.mark.parametrize("missing", ["iaStorVD.inf", "iaStorVD.sys", "iaStorVD.cat"])
def test_incomplete_driver_package(tmp_path, missing):
    package(tmp_path)
    (tmp_path / missing).unlink()
    with pytest.raises(ForgeError):
        inspect_drivers(tmp_path)


def test_pci_no_match(tmp_path):
    package(tmp_path)
    (tmp_path / "iaStorVD.inf").write_text(
        INF.replace("PCI\\VEN_8086&DEV_467F", "USB\\VID_1234&PID_5678")
    )
    assert inspect_drivers(tmp_path).pci_ids == ()


def test_invalid_inf(tmp_path):
    package(tmp_path)
    (tmp_path / "iaStorVD.inf").write_text("not an INF")
    with pytest.raises(ForgeError):
        inspect_drivers(tmp_path)


def test_copy_complete_tree_with_unicode(tmp_path):
    source = package(tmp_path / "controladores extraídos")
    (source / "subdirectory").mkdir()
    (source / "subdirectory/extra.dll").write_bytes(b"required helper")
    target = tmp_path / "media"
    target.mkdir()
    info = add_drivers(source, target)
    assert len(info.files) == 4
    for name in info.files:
        assert (target / "DRIVERS/STORAGE" / name).read_bytes() == (source / name).read_bytes()


def test_existing_drivers_not_overwritten(tmp_path):
    source = package(tmp_path / "source")
    target = tmp_path / "media"
    (target / "Drivers").mkdir(parents=True)
    with pytest.raises(ForgeError):
        add_drivers(source, target)


def test_driver_symlink_rejected(tmp_path):
    package(tmp_path)
    (tmp_path / "link").symlink_to("iaStorVD.sys")
    with pytest.raises(ForgeError):
        inspect_drivers(tmp_path)


@pytest.mark.parametrize("data", [b"", b"\xff\xfe\x00", b"a\x00b"])
def test_invalid_inf_encoding(data):
    with pytest.raises(ForgeError):
        decode_inf(data)


def test_oversized_inf_rejected_without_reading_entire_file(tmp_path):
    package(tmp_path)
    with (tmp_path / "iaStorVD.inf").open("wb") as stream:
        stream.truncate(32 * 1024**2)
    with pytest.raises(ForgeError, match="exceeds 16 MiB"):
        inspect_drivers(tmp_path)


def test_source_component_symlink_rejected(tmp_path):
    from winusb_forge.drivers import _open_source

    package(tmp_path / "real")
    (tmp_path / "alias").symlink_to("real", target_is_directory=True)
    with pytest.raises(OSError):
        _open_source(tmp_path, "alias/iaStorVD.sys")
