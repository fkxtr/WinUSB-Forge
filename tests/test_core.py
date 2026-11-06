"""Process and privacy boundaries; no external program or real device is invoked."""

import json
import os
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from winusb_forge import core
from winusb_forge.core import ForgeError, Runner, record_event, unprivileged


def test_dry_run_refuses_before_executable_resolution(monkeypatch):
    monkeypatch.setattr(core.shutil, "which", lambda _: pytest.fail("resolved write command"))
    with pytest.raises(ForgeError, match="dry_run_write"):
        Runner(dry_run=True).run(["mkfs.vfat", "/dev/never"], write=True)


def test_runner_preserves_argument_boundaries_and_never_uses_shell(monkeypatch):
    calls = []
    monkeypatch.setattr(core.os, "geteuid", lambda: 1000)
    monkeypatch.setattr(core.shutil, "which", lambda _: "/usr/bin/tool")

    def run(args, **kwargs):
        calls.append((args, kwargs))
        return SimpleNamespace(stdout=b"complete")

    monkeypatch.setattr(core.subprocess, "run", run)
    value = "spaces; $(touch BAD) / unicode ñ"
    assert Runner().run(["tool", value, Path("a b")], input="data", pass_fds=(7,)) == "complete"
    args, kwargs = calls[0]
    assert args == ["/usr/bin/tool", value, "a b"]
    assert not kwargs.get("shell", False)
    assert kwargs["check"] is True
    assert kwargs["input"] == b"data"
    assert kwargs["pass_fds"] == (7,)
    assert kwargs["env"]["LC_ALL"] == "C.UTF-8"


def test_runner_missing_tool(monkeypatch):
    monkeypatch.setattr(core.shutil, "which", lambda _: None)
    with pytest.raises(ForgeError, match="missing_tool"):
        Runner().run(["unavailable"])


def test_runner_empty_command():
    with pytest.raises(ForgeError, match="invalid_command"):
        Runner().run([])


@pytest.mark.parametrize(
    ("failure", "code"),
    [
        (FileNotFoundError(), "missing_tool"),
        (subprocess.TimeoutExpired("tool", 2), "command_timeout"),
        (subprocess.CalledProcessError(7, "tool", stderr="private-secret"), "command_failed"),
    ],
)
def test_runner_failures_preserve_category_without_secret_output(monkeypatch, failure, code):
    monkeypatch.setattr(core.os, "geteuid", lambda: 1000)
    monkeypatch.setattr(core.shutil, "which", lambda _: "/usr/bin/tool")

    def failed(*args, **kwargs):
        raise failure

    monkeypatch.setattr(core.subprocess, "run", failed)
    with pytest.raises(ForgeError) as raised:
        Runner().run(["tool"])
    assert raised.value.code == code
    assert "private-secret" not in str(raised.value)


def test_root_rejects_user_writable_executable(monkeypatch, tmp_path):
    executable = tmp_path / "tool"
    executable.write_text("untrusted")
    executable.chmod(0o777)
    monkeypatch.setattr(core.os, "geteuid", lambda: 0)
    monkeypatch.setattr(core.shutil, "which", lambda _: str(executable))
    monkeypatch.setattr(core.subprocess, "run", lambda *a, **k: pytest.fail("ran unsafe tool"))
    with pytest.raises(ForgeError, match="unsafe_tool"):
        Runner().run(["tool"])


def test_normal_user_context_does_not_change_privileges(monkeypatch):
    monkeypatch.setattr(core.os, "geteuid", lambda: 1000)
    monkeypatch.setattr(core.os, "seteuid", lambda _: pytest.fail("changed normal privileges"))
    with unprivileged():
        assert True


def test_direct_root_without_sudo_user_refused(monkeypatch):
    monkeypatch.setattr(core.os, "geteuid", lambda: 0)
    monkeypatch.delenv("SUDO_UID", raising=False)
    with pytest.raises(ForgeError, match="sudo_user_required"):
        with unprivileged():
            pytest.fail("entered direct root context")


def test_sudo_context_restores_identity_on_error(monkeypatch):
    calls = []
    monkeypatch.setattr(core.os, "geteuid", lambda: 0)
    monkeypatch.setattr(core.os, "getegid", lambda: 0)
    monkeypatch.setattr(core.os, "getgroups", lambda: [0, 27])
    monkeypatch.setenv("SUDO_UID", "1001")
    monkeypatch.setenv("SUDO_GID", "1002")
    monkeypatch.setattr(core.os, "setgroups", lambda groups: calls.append(("groups", groups)))
    monkeypatch.setattr(core.os, "setegid", lambda gid: calls.append(("gid", gid)))
    monkeypatch.setattr(core.os, "seteuid", lambda uid: calls.append(("uid", uid)))
    with pytest.raises(RuntimeError, match="interrupted"):
        with unprivileged():
            raise RuntimeError("interrupted")
    assert calls == [
        ("groups", []),
        ("gid", 1002),
        ("uid", 1001),
        ("uid", 0),
        ("gid", 0),
        ("groups", [0, 27]),
    ]


def test_event_log_is_private_and_contains_only_declared_fields(tmp_path):
    path = tmp_path / "private/events.jsonl"
    record_event(path, "create", result="cancelled")
    record_event(path, "inspect", result="ok")
    events = [json.loads(line) for line in path.read_text().splitlines()]
    assert len(events) == 2
    assert events[0]["result"] == "cancelled"
    assert set(events[0]) == {"time", "version", "event", "result"}
    assert events[0]["time"].endswith("Z")
    assert path.stat().st_mode & 0o777 == 0o600
    assert path.parent.stat().st_mode & 0o777 == 0o700


def test_event_log_refuses_leaf_symlink_without_changing_target(tmp_path):
    target = tmp_path / "target"
    target.write_text("private original")
    link = tmp_path / "events"
    link.symlink_to(target)
    with pytest.raises((OSError, ForgeError)):
        record_event(link, "create", result="ok")
    assert target.read_text() == "private original"


def test_event_log_refuses_public_permissions_before_writing(tmp_path):
    path = tmp_path / "events"
    path.write_text("original")
    path.chmod(0o644)
    with pytest.raises(ForgeError, match="unsafe_log"):
        record_event(path, "create", result="ok")
    assert path.read_text() == "original"


def test_event_log_closes_descriptor_if_sync_fails(monkeypatch, tmp_path):
    actual_close = os.close
    closed = []

    def failed_sync(fd):
        raise OSError("sync failed")

    def close(fd):
        closed.append(fd)
        actual_close(fd)

    monkeypatch.setattr(core.os, "fsync", failed_sync)
    monkeypatch.setattr(core.os, "close", close)
    with pytest.raises(OSError, match="sync failed"):
        record_event(tmp_path / "events", "create", result="ok")
    assert len(closed) == 1


@pytest.mark.parametrize("uid,gid", [("oops", "1000"), ("1000", "oops"), ("1000", None)])
def test_invalid_sudo_identity_fails_closed(monkeypatch, uid, gid):
    monkeypatch.setattr(core.os, "geteuid", lambda: 0)
    monkeypatch.setenv("SUDO_UID", uid)
    if gid is None:
        monkeypatch.delenv("SUDO_GID", raising=False)
    else:
        monkeypatch.setenv("SUDO_GID", gid)
    with pytest.raises(ForgeError, match="sudo_user_required"):
        with unprivileged():
            pytest.fail("entered invalid identity context")


def test_undecodable_tool_output_is_actionable(monkeypatch):
    monkeypatch.setattr(core.os, "geteuid", lambda: 1000)
    monkeypatch.setattr(core.shutil, "which", lambda _: "/usr/bin/tool")
    monkeypatch.setattr(core.subprocess, "run", lambda *a, **k: SimpleNamespace(stdout=b"\xff"))
    with pytest.raises(ForgeError, match="command_encoding"):
        Runner().run(["tool"])


def test_tool_child_permanently_drops_real_root(monkeypatch):
    calls = []
    monkeypatch.setattr(core.os, "getuid", lambda: 0)
    monkeypatch.setattr(core.os, "geteuid", lambda: 1001)
    monkeypatch.setattr(core.os, "getegid", lambda: 1002)
    monkeypatch.setattr(core.shutil, "which", lambda _: "/usr/bin/tool")

    def run(*args, **kwargs):
        calls.append(kwargs)
        return SimpleNamespace(stdout=b"ok")

    monkeypatch.setattr(core.subprocess, "run", run)
    assert Runner().run(["tool"]) == "ok"
    assert calls[0]["user"] == 1001
    assert calls[0]["group"] == 1002


def test_event_log_fifo_rejected_without_blocking(tmp_path):
    path = tmp_path / "events"
    os.mkfifo(path, 0o600)
    with pytest.raises((ForgeError, OSError)):
        record_event(path, "create", result="ok")
