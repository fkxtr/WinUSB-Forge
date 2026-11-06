"""Explicit process boundary, privilege context and private event records."""

from __future__ import annotations

import contextlib
import json
import os
import shutil
import stat

# All subprocess calls below use an argv list and never invoke a shell.
import subprocess  # nosec B404
import time
from collections.abc import Iterator, Sequence
from pathlib import Path

from . import __version__


class ForgeError(Exception):
    def __init__(self, code: str, detail: str = "") -> None:
        self.code = code
        self.detail = detail
        super().__init__(f"{code}: {detail}" if detail else code)


class Runner:
    """No shell, no implicit sudo and no disk mutation during planning."""

    def __init__(self, *, dry_run: bool = False) -> None:
        self.dry_run = dry_run

    def run(
        self,
        args: Sequence[str | Path],
        *,
        input: str | None = None,
        write: bool = False,
        pass_fds: tuple[int, ...] = (),
        timeout: int = 3600,
        encoding: str = "utf-8",
    ) -> str:
        if write and self.dry_run:
            raise ForgeError("dry_run_write")
        argv = [str(arg) for arg in args]
        if not argv:
            raise ForgeError("invalid_command")
        executable = shutil.which(argv[0])
        if executable is None and argv[0] == "7z":
            executable = shutil.which("7zz")
        if executable is None:
            raise ForgeError("missing_tool", argv[0])
        if os.geteuid() == 0:
            # Elevated execution never trusts writable PATH entries or binaries.
            for path in (Path(executable).resolve(), *Path(executable).resolve().parents):
                metadata = path.stat()
                if metadata.st_uid != 0 or metadata.st_mode & 0o022:
                    raise ForgeError("unsafe_tool", argv[0])
        argv[0] = executable
        env = dict(os.environ)
        env.update(LC_ALL="C.UTF-8", LANG="C.UTF-8")
        # User mtools configuration must not disable filesystem checks.
        for name in tuple(env):
            if name.startswith("MTOOLS") or (
                os.getuid() == 0
                and (
                    name.startswith("LD_")
                    or name in {"ENV", "BASH_ENV", "PYTHONPATH", "PYTHONHOME"}
                )
            ):
                del env[name]
        env["MTOOLSRC"] = "/dev/null"
        try:
            # Executable path is checked above; every argument remains separate.
            result = subprocess.run(  # nosec B603
                argv,
                input=input.encode(encoding) if input is not None else None,
                capture_output=True,
                shell=False,
                check=True,
                env=env,
                pass_fds=pass_fds,
                timeout=timeout,
                user=os.geteuid() if os.getuid() == 0 else None,
                group=os.getegid() if os.getuid() == 0 else None,
            )
        except FileNotFoundError as error:
            raise ForgeError("missing_tool", argv[0]) from error
        except subprocess.TimeoutExpired as error:
            raise ForgeError("command_timeout", Path(argv[0]).name) from error
        except subprocess.CalledProcessError as error:
            # Do not echo untrusted image contents, paths or secrets into reports.
            raise ForgeError(
                "command_failed", f"{Path(argv[0]).name} (exit {error.returncode})"
            ) from error
        try:
            return result.stdout.decode(encoding)
        except UnicodeError as error:
            raise ForgeError("command_encoding", Path(argv[0]).name) from error


@contextlib.contextmanager
def unprivileged() -> Iterator[None]:
    """Drop sudo effective privileges for archive tools; restore for disk I/O only.

    Real UID remains root so restoration is possible. This limits accidental tool
    writes; it is not a sandbox against malicious native parsers. Trust the ISO.
    """
    uid, gid = os.geteuid(), os.getegid()
    groups = os.getgroups()
    try:
        target = int(os.environ.get("SUDO_UID", "0")) if uid == 0 else uid
        target_gid = int(os.environ["SUDO_GID"]) if uid == 0 else gid
    except (ValueError, KeyError) as error:
        raise ForgeError("sudo_user_required") from error
    if uid == 0 and target <= 0:
        raise ForgeError("sudo_user_required")
    if uid == 0 and target > 0:
        if target_gid <= 0:
            raise ForgeError("sudo_user_required")
        os.setgroups([])
        os.setegid(target_gid)
        os.seteuid(target)
        try:
            yield
        finally:
            os.seteuid(uid)
            os.setegid(gid)
            os.setgroups(groups)
    else:
        yield


def record_event(path: Path, event: str, *, result: str) -> None:
    """Only fixed event codes; no argv, paths, serials, file data or environment."""
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    flags = os.O_WRONLY | os.O_CREAT | os.O_APPEND | os.O_NOFOLLOW | os.O_NONBLOCK
    fd = os.open(path, flags, 0o600)
    try:
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode) or st.st_uid != os.geteuid() or st.st_mode & 0o077:
            raise ForgeError("unsafe_log")
        payload = {
            "time": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "version": __version__,
            "event": event,
            "result": result,
        }
        pending = memoryview((json.dumps(payload) + "\n").encode())
        while pending:
            written = os.write(fd, pending)
            if written <= 0:
                raise OSError("short log write")
            pending = pending[written:]
        os.fsync(fd)
    finally:
        os.close(fd)
