"""Firmware reports contain read-only, redacted facts rather than raw command text."""

import json

import pytest

from winusb_forge.core import ForgeError
from winusb_forge.diagnostics import diagnose


class DiagnosticRunner:
    def __init__(self, *, secure="SecureBoot disabled", boot="", disks=None, fail=()):
        self.outputs = {
            "mokutil": secure,
            "efibootmgr": boot,
            "lsblk": json.dumps({"blockdevices": []} if disks is None else disks),
        }
        self.fail = fail
        self.calls = []

    def run(self, args, **kwargs):
        assert not kwargs.get("write", False)
        self.calls.append(args)
        if args[0] in self.fail:
            raise ForgeError("missing_tool", args[0])
        return self.outputs[args[0]]


def test_firmware_report_uefi_secure_boot_and_both_loaders(tmp_path):
    (tmp_path / "firmware/efi").mkdir(parents=True)
    runner = DiagnosticRunner(
        secure="SecureBoot enabled",
        boot="Boot0000* Windows Boot Manager HD(private-device-id)\nBoot0001* ubuntu",
        disks={
            "blockdevices": [
                {
                    "type": "disk",
                    "children": [
                        {"fstype": "vfat", "parttype": "C12A7328-F81F-11D2-BA4B-00A0C93EC93B"},
                        {"fstype": "ext4", "parttype": "other"},
                    ],
                }
            ]
        },
    )
    result = diagnose(runner, tmp_path)
    assert result["firmware"] == "UEFI"
    assert result["secure_boot"] == "enabled"
    assert result["windows_boot_entry"] is True
    assert result["linux_boot_entry"] is True
    assert result["filesystem_types"] == ["ext4", "vfat"]
    assert result["efi_partition_count"] == 1
    assert "private-device-id" not in json.dumps(result)
    assert runner.calls == [
        ["mokutil", "--sb-state"],
        ["efibootmgr"],
        ["lsblk", "--json", "--output", "TYPE,FSTYPE,PARTTYPE"],
    ]


@pytest.mark.parametrize(
    ("text", "expected"),
    [("SecureBoot disabled", "disabled"), ("not supported", "unknown")],
)
def test_secure_boot_unknown_is_not_reported_disabled(tmp_path, text, expected):
    result = diagnose(DiagnosticRunner(secure=text), tmp_path)
    assert result["firmware"] == "BIOS/unknown"
    assert result["secure_boot"] == expected
    assert result["windows_boot_entry"] is False
    assert result["linux_boot_entry"] is False


def test_missing_optional_tools_remain_observable(tmp_path):
    result = diagnose(DiagnosticRunner(fail=("mokutil", "efibootmgr", "lsblk")), tmp_path)
    assert result["secure_boot"] == "missing_tool"
    assert result["boot_entries"] == "missing_tool"
    assert result["disks"] == "unavailable"


@pytest.mark.parametrize("disks", [{}, {"blockdevices": None}, {"blockdevices": "bad"}])
def test_malformed_disk_report_unavailable(tmp_path, disks):
    result = diagnose(DiagnosticRunner(disks=disks), tmp_path)
    assert result["disks"] == "unavailable"


def test_mbr_efi_partition_detected(tmp_path):
    result = diagnose(DiagnosticRunner(disks={"blockdevices": [{"parttype": "0xef"}]}), tmp_path)
    assert result["efi_partition_count"] == 1


@pytest.mark.parametrize("nodes", [[None], [{"children": None}], [{"children": "bad"}]])
def test_malformed_nested_nodes_report_unavailable(tmp_path, nodes):
    result = diagnose(DiagnosticRunner(disks={"blockdevices": nodes}), tmp_path)
    assert result["disks"] == "unavailable"
