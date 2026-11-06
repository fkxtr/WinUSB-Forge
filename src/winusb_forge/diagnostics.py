"""Read-only firmware diagnostics with deliberately minimal exports."""

from pathlib import Path

from . import __version__
from .core import ForgeError, Runner


def diagnose(runner: Runner, sys_root: Path = Path("/sys")) -> dict[str, object]:
    report: dict[str, object] = {
        "version": __version__,
        "firmware": "UEFI" if (sys_root / "firmware/efi").is_dir() else "BIOS/unknown",
    }
    for name, args in (
        ("secure_boot", ["mokutil", "--sb-state"]),
        ("boot_entries", ["efibootmgr"]),
    ):
        try:
            result = runner.run(args, timeout=30)
            if name == "secure_boot":
                report[name] = (
                    "enabled"
                    if "SecureBoot enabled" in result
                    else ("disabled" if "SecureBoot disabled" in result else "unknown")
                )
            else:
                report["windows_boot_entry"] = "Windows Boot Manager" in result
                report["linux_boot_entry"] = any(
                    word in result.casefold()
                    for word in ("ubuntu", "debian", "fedora", "linux", "mint")
                )
                report["boot_entry_note"] = "Labels only; loader integrity not verified"
        except ForgeError as error:
            report[name] = error.code
    try:
        import json

        data = json.loads(runner.run(["lsblk", "--json", "--output", "TYPE,FSTYPE,PARTTYPE"]))
        types: set[str] = set()
        esp_count = 0

        def walk(nodes: list[dict]) -> None:
            nonlocal esp_count
            if not isinstance(nodes, list):
                raise ValueError("invalid block list")
            for node in nodes:
                if not isinstance(node, dict):
                    raise ValueError("invalid block entry")
                if node.get("fstype"):
                    types.add(str(node["fstype"]))
                if str(node.get("parttype", "")).lower() in (
                    "0xef",
                    "c12a7328-f81f-11d2-ba4b-00a0c93ec93b",
                ):
                    esp_count += 1
                walk(node.get("children", []))

        walk(data["blockdevices"])
        report["filesystem_types"] = sorted(types)
        report["efi_partition_count"] = esp_count
    except (ForgeError, ValueError, KeyError, TypeError):
        report["disks"] = "unavailable"
    return report
