"""CLI checks use an injected media tree and device inventory; never live disks."""

import contextlib
import io
import json
import os
import sys
from types import SimpleNamespace

import pytest

from winusb_forge import cli
from winusb_forge.core import ForgeError
from winusb_forge.devices import Device


@pytest.fixture
def cli_boundary(monkeypatch, tmp_path):
    device = Device(
        path="/dev/test-usb",
        model="Test USB",
        serial="test-private-1234",
        size=16 * 1024**3,
        transport="usb",
        major_minor="8:16",
        diskseq=42,
        sys_path="/sys/mock/usb1/1-1",
        usb_ancestry=True,
        vendor="Fixture",
    )
    prepared = SimpleNamespace(
        root=tmp_path / "media", total_bytes=1024, files={"one": "digest"}, image_kind="wim"
    )
    events = []
    runners = []

    class Discovery:
        def __init__(self, runner):
            self.runner = runner

        def list(self):
            return [device]

        def select(self, path):
            assert path == device.path
            return device

    class Media:
        def __init__(self, runner):
            runners.append(runner)

        def prepare(self, iso, staging, sha256):
            prepared.root.mkdir(exist_ok=True)
            return prepared

    class ForbiddenWriter:
        def __init__(self, *args, **kwargs):
            pytest.fail("dry-run or refusal reached Writer")

    monkeypatch.setattr(cli, "DeviceDiscovery", Discovery)
    monkeypatch.setattr(cli, "Media", Media)
    monkeypatch.setattr(cli, "unprivileged", contextlib.nullcontext)
    monkeypatch.setattr(cli.os, "geteuid", lambda: 1000)
    monkeypatch.setattr(
        cli, "record_event", lambda path, event, result: events.append((event, result))
    )
    monkeypatch.setitem(sys.modules, "winusb_forge.writer", SimpleNamespace(Writer=ForbiddenWriter))
    monkeypatch.setattr(sys, "stdin", io.StringIO())
    actual_open = os.open

    def guarded_open(path, flags, *args, **kwargs):
        if str(path).startswith("/dev/"):
            pytest.fail(f"CLI opened device {path} flags={flags}")
        return actual_open(path, flags, *args, **kwargs)

    monkeypatch.setattr(os, "open", guarded_open)
    return SimpleNamespace(device=device, prepared=prepared, events=events, runners=runners)


@pytest.mark.parametrize("command", ["plan", "dry-run", "plan-alias"])
def test_preview_modes_never_instantiate_writer_or_open_block(cli_boundary, capsys, command):
    args = [
        "plan" if command == "plan" else "create",
        "--iso",
        "ISO ñ with spaces.iso",
        "--device",
        cli_boundary.device.path,
    ]
    if command != "plan":
        args.append("--dry-run" if command == "dry-run" else "--plan")
    assert cli.main(args) == 0
    output = capsys.readouterr().out
    assert "No device writes" in output
    assert "MBR/DOS" in output
    assert cli_boundary.runners[0].dry_run is True
    assert cli_boundary.events[-1][1] == "ok"


def test_inspection_does_not_require_root_or_writer(cli_boundary, capsys):
    assert cli.main(["inspect", "--iso", "image.iso"]) == 0
    assert "integrity verified" in capsys.readouterr().out
    assert cli_boundary.events[-1] == ("inspect", "ok")


def test_create_requires_root_before_media_parse(cli_boundary, capsys):
    assert cli.main(["create", "--iso", "image.iso", "--device", "/dev/test-usb"]) == 1
    assert "sudo" in capsys.readouterr().out
    assert cli_boundary.runners == []
    assert cli_boundary.events[-1] == ("create", "root_required")


def test_create_refuses_noninteractive_stdin_before_parsing_media(
    cli_boundary, monkeypatch, capsys
):
    monkeypatch.setattr(cli.os, "geteuid", lambda: 0)
    assert cli.main(["create", "--iso", "image.iso", "--device", "/dev/test-usb"]) == 1
    assert "interactive terminal" in capsys.readouterr().out
    assert cli_boundary.runners == []
    assert cli_boundary.events[-1] == ("create", "tty_required")


@pytest.mark.parametrize("answer", ["", "yes", "ERASE /dev/test-usb 41 17179869184"])
def test_incorrect_manual_identity_never_reaches_writer(cli_boundary, monkeypatch, answer):
    monkeypatch.setattr(cli.os, "geteuid", lambda: 0)
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr("builtins.input", lambda _: answer)
    monkeypatch.setattr(
        cli.os, "seteuid", lambda _: pytest.fail("elevated after wrong confirmation")
    )
    assert cli.main(["create", "--iso", "image.iso", "--device", "/dev/test-usb"]) == 1
    assert cli_boundary.events[-1][1] != "ok"


@pytest.mark.parametrize("failure", [KeyboardInterrupt, EOFError])
def test_confirmation_cancel_never_writes(cli_boundary, monkeypatch, failure, capsys):
    monkeypatch.setattr(cli.os, "geteuid", lambda: 0)
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)

    def cancel(_):
        raise failure()

    monkeypatch.setattr("builtins.input", cancel)
    monkeypatch.setattr(cli.os, "seteuid", lambda _: pytest.fail("elevated on cancellation"))
    assert cli.main(["create", "--iso", "image.iso", "--device", "/dev/test-usb"]) == 130
    assert "Cancelled" in capsys.readouterr().out
    assert cli_boundary.events[-1] == ("create", "cancelled")


def test_spanish_plan_and_no_color_when_piped(cli_boundary, capsys):
    assert (
        cli.main(["--lang", "es", "plan", "--iso", "imagen.iso", "--device", "/dev/test-usb"]) == 0
    )
    output = capsys.readouterr().out
    assert "Plan de preparación" in output
    assert "No se escribió en dispositivos" in output
    assert "\x1b" not in output


def test_metadata_escapes_are_rendered_inert(capsys):
    ui = cli.UI("en")
    ui.say("USB\x1b[2J\rhidden\ncommand")
    output = capsys.readouterr().out
    assert "\x1b" not in output
    assert "\r" not in output
    assert r"USB\x1b[2J\rhidden\ncommand" in output


def test_small_terminal_wraps_without_losing_text(monkeypatch, capsys):
    monkeypatch.setattr(cli.shutil, "get_terminal_size", lambda _: os.terminal_size((24, 12)))
    ui = cli.UI("en")
    ui.message("dry")
    lines = capsys.readouterr().out.splitlines()
    assert all(len(line) <= 24 for line in lines)
    assert "No device writes" in " ".join(lines)


def test_device_output_redacts_serial(cli_boundary, capsys):
    assert cli.main(["devices"]) == 0
    output = capsys.readouterr().out
    assert "test-private" not in output
    assert "1234" in output


def test_no_usb_is_successful_diagnostic(cli_boundary, monkeypatch, capsys):
    monkeypatch.setattr(cli.DeviceDiscovery, "list", lambda self: [])
    assert cli.main(["devices"]) == 0
    assert "No USB disks detected" in capsys.readouterr().out


def test_read_failure_is_not_success_and_detail_is_escaped(cli_boundary, monkeypatch, capsys):
    def fail(*args):
        raise ForgeError("iso_missing", "bad\x1b[2Jname")

    monkeypatch.setattr(cli.Media, "prepare", fail)
    assert cli.main(["inspect", "--iso", "missing.iso"]) == 1
    output = capsys.readouterr().out
    assert "Operation stopped" in output
    assert "\x1b" not in output
    assert "integrity verified" not in output


def test_diagnostic_export_private_and_no_overwrite(cli_boundary, monkeypatch, tmp_path):
    monkeypatch.setattr(cli, "diagnose", lambda runner: {"firmware": "UEFI"})
    target = tmp_path / "diagnostics.json"
    assert cli.main(["diagnose", "--export", str(target)]) == 0
    assert json.loads(target.read_text()) == {"firmware": "UEFI"}
    assert target.stat().st_mode & 0o777 == 0o600
    target.write_text("user data")
    assert cli.main(["diagnose", "--export", str(target)]) == 1
    assert target.read_text() == "user data"


def test_diagnostic_export_rejects_symlink(cli_boundary, monkeypatch, tmp_path):
    monkeypatch.setattr(cli, "diagnose", lambda runner: {"firmware": "UEFI"})
    original = tmp_path / "existing"
    original.write_text("user data")
    link = tmp_path / "report"
    link.symlink_to(original)
    assert cli.main(["diagnose", "--export", str(link)]) == 1
    assert original.read_text() == "user data"


def test_no_arguments_on_pipe_shows_help(cli_boundary, capsys):
    assert cli.main([]) == 0
    assert "usage: winusb-forge" in capsys.readouterr().out


def test_menu_exit_and_driver_guidance(cli_boundary, monkeypatch, capsys):
    monkeypatch.setattr("builtins.input", lambda _: "8")
    assert cli.interactive(cli.UI("en")) is None
    answers = iter(["5", "/drivers with spaces"])
    monkeypatch.setattr("builtins.input", lambda _: next(answers))
    assert cli.interactive(cli.UI("es")) == ["drivers", "inspect", "/drivers with spaces"]
    assert "--drivers" in capsys.readouterr().out
