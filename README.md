# WinUSB Forge

**A reliable Windows USB installer creator for Linux**

Prepare a Windows 11 x64 installer for UEFI from your own Windows ISO, with a
reviewable partition plan, explicit device confirmation, FAT32 image handling and
content verification. [Documentación en español](README.es.md).

**Version 0.1.0rc1 is preliminary.** Automated and synthetic tests do not establish
that a USB boots Windows. No real USB, Windows installation, Secure Boot firmware
or reference HP/Kingston hardware has been verified by this project. Review
[validation and limitations](docs/validation.md) and
[recorded release evidence](docs/release-evidence.md) before using it with a device.
Creating media erases the selected USB. Back up its contents first.

## Requirements and installation

Linux, Python 3.11+, a legitimate Windows 11 x64 ISO, and an expendable USB drive.
The first version accepts USB disks with 512-byte logical sectors and Linux
`diskseq` identity information. Internal disks, mounted or busy disks, read-only
disks and incomplete identity information are rejected. A serial alone is never
used as proof of identity.

Runtime tools: `lsblk`, `7z`, `wimlib-imagex`, `mkfs.vfat`, `fsck.fat`, `mcopy` and
`mmd`. Diagnostics can additionally use `mokutil` and `efibootmgr`. Python has no
third-party runtime dependencies. Use distribution-maintained packages and keep
them updated. Package names vary by distribution; verify tool availability with
`command -v` if a package is unavailable.

Debian / Ubuntu / Linux Mint:

```sh
sudo apt install python3 python3-venv util-linux p7zip-full wimtools dosfstools mtools
```

Fedora (package names depend on the release):

```sh
sudo dnf install python3 util-linux 7zip wimlib-utils dosfstools mtools
```

The application accepts `7z` or `7zz` and uses the installed command. Do not
install an unverified binary to work around a missing distribution package.

Install from a reviewed checkout; no package is claimed to be published on PyPI:

```sh
git clone https://github.com/fkxtr/WinUSB-Forge.git
cd WinUSB-Forge
python3 -m venv .venv
.venv/bin/python -m pip install .
.venv/bin/winusb-forge --help
```

Allow local temporary space for the extracted ISO and WIM fragments when
splitting. Image construction also needs twice the planned partition size plus
the staged content size and 64 MiB: the second image is a private frozen snapshot,
verified again before opening the USB. Inspection can require twice the extracted
ISO size. These are conservative checks for peak working space. The USB capacity check is separate from
local free-space requirements. The program works offline once its dependencies
are installed. It does not download Windows or drivers.

## First use

```sh
.venv/bin/winusb-forge
.venv/bin/winusb-forge --lang es
```

The menu exposes creation, ISO inspection, USB discovery, verification, storage
driver inspection/inclusion, read-only Linux diagnostics and help. Both CLI and
menu use the same safety checks. Colors are optional; no terminal library is
required. `Ctrl+C` cancels the operation. Cancellation during writing leaves an
incomplete USB that must be recreated.

Start with discovery and inspection as your normal user:

```sh
.venv/bin/winusb-forge devices
.venv/bin/winusb-forge inspect --iso '/path/Windows 11 x64.iso'
.venv/bin/winusb-forge drivers inspect '/path/Extracted F6 drivers'
.venv/bin/winusb-forge diagnose
```

For the following examples, replace the entire `/dev/disk/by-id/usb-YOUR_DEVICE`
placeholder with the actual whole-disk path reported for your USB. Do not select
a `-part1` link. Check model and capacity against the physical device. Close file
managers and explicitly unmount its partitions before planning; the application
does not silently unmount existing filesystems.

```sh
.venv/bin/winusb-forge plan \
  --iso '/path/Windows 11 x64.iso' \
  --device /dev/disk/by-id/usb-YOUR_DEVICE

.venv/bin/winusb-forge create --dry-run \
  --iso '/path/Windows 11 x64.iso' \
  --device /dev/disk/by-id/usb-YOUR_DEVICE \
  --drivers '/path/Extracted F6 drivers'
```

`plan`, `create --plan` and `create --dry-run` can create temporary local staging
files to inspect and transform media. They never partition or write the USB and
never mount it for writing. They are not zero-disk-I/O modes. Add `--sha256` with a
trusted 64-character SHA-256 digest to verify the ISO before preparing it.

The privileged creation command and typed confirmation are required before
writing. Run it through `sudo` from a normal user; a direct root login is rejected.
To create from the menu, start the menu with `sudo .venv/bin/winusb-forge`. There is no assume-yes option. The exact phrase shown includes the device
identity; do not reuse a phrase from a previous run.

```sh
sudo .venv/bin/winusb-forge create \
  --iso '/path/Windows 11 x64.iso' \
  --device /dev/disk/by-id/usb-YOUR_DEVICE \
  --drivers '/path/Extracted F6 drivers' \
  --label WIN11

sudo .venv/bin/winusb-forge verify --device /dev/disk/by-id/usb-YOUR_DEVICE
```

Use an absolute ISO path when changing user. Verification opens the target for
reading; it does not repair it. A passed structural/content check does not prove
firmware acceptance, Microsoft signature trust or successful Windows installation.

## Media layout and Windows images

The default layout is MBR/DOS with one primary FAT32 LBA partition, MBR type
`0x0C`, labeled `WIN11`. Its size is calculated from staged content plus a margin,
with a 32 GiB ceiling. Larger USB drives are supported within this layout; the
remaining capacity stays unallocated and is shown in the plan. There is no
additional EFI System Partition, NTFS partition or third-party bootloader.

The UEFI removable-media loader is `efi/boot/bootx64.efi`. Its PE machine type is
checked for x64. The ISO must use UDF (the official Windows optical-media format) and contain
`sources/boot.wim` and a supported install image. ISO9660-only media is rejected.
Host ISO paths may contain Unicode. Internal media and driver filenames support
BMP Unicode such as accents and Japanese; non-BMP characters such as emoji are
rejected before writing because mtools cannot safely preserve them. FAT32 permits at most 4 GiB minus 1 byte per file. Oversized `install.wim`
is split with wimlib into `install.swm`, `install2.swm`, etc., kept together in
`sources`; the original is not copied alongside the parts. Fragment sizes and
WIM readability are checked. A fitting `install.esd` is copied; an oversized ESD
is rejected before the USB is changed. No edition-conversion workaround is
claimed. Windows ARM64, legacy BIOS and modified Windows images are outside the
supported scope; Windows 10 compatibility has not been validated.

Secure Boot remains under firmware and Microsoft policy. The program copies the
user's loader; it does not certify its signature, enroll keys, bypass TPM or
licensing requirements, or disable Secure Boot.

## Storage drivers and dual boot

Supply the complete extracted F6 package from your hardware vendor. INF parsing
recognizes UTF-8 and UTF-16, including the regression ID `8086:467F`. Required
SYS/CAT presence is checked, and the directory tree is copied to
`DRIVERS/STORAGE`. A PCI match is evidence to investigate, not a compatibility or
signature guarantee. No proprietary driver is bundled or downloaded.

At the Windows Setup disk-selection screen, choose **Load driver**, browse to the
USB's `DRIVERS/STORAGE` directory and select the vendor's appropriate x64 driver.
This release does not inject drivers into `boot.wim`. To include drivers, provide
`--drivers` during creation; modifying an already-created USB in place is not a
supported operation.

`diagnose` reads Linux/UEFI information where permissions and tools permit it.
Unavailable information is reported as unavailable. It never changes boot order,
installs GRUB or alters an SSD. [Dual-boot notes](docs/dual-boot.md) explain the
boundary between diagnosis and repair.

## Failure handling and privacy

Critical failures stop subsequent operations. A write interruption, unplugged
USB, integrity mismatch or flush failure means the medium is incomplete: do not
boot or rely on it; reconnect, inspect and recreate it after resolving the cause.
Do not disconnect while writing or verification is active. See
[troubleshooting](docs/troubleshooting.md).

There is no telemetry, network call, credential input or Windows key collection.
Operation logs contain fixed event/error codes, date and version at
`~/.local/state/winusb-forge/events.jsonl` (or under `XDG_STATE_HOME`), avoiding file
contents and credentials. Before sharing any report,
review it for information about your machine. `diagnose --export PATH` exports
a reduced diagnostic report. See [security and privacy](SECURITY.md).

## Development and release evidence

```sh
.venv/bin/python -m pip install -e '.[dev]'
.venv/bin/python -m pytest
.venv/bin/ruff check .
.venv/bin/ruff format --check .
.venv/bin/bandit -r src
.venv/bin/mypy src --ignore-missing-imports
.venv/bin/python -m compileall -q src tests
.venv/bin/python -m build
mkdir -p build
.venv/bin/python scripts/audit_requirements.py > build/audit-requirements.txt
.venv/bin/pip-audit --strict --no-deps --disable-pip -r build/audit-requirements.txt
```

CI tests simulated devices and temporary regular files; it never formats a real
block device. The audit inventory includes every installed external Python distribution at
its exact version; only the unpublished, dependency-free local project is excluded
from the advisory lookup and covered by code review/static analysis instead.
Dependency auditing and tool versions need to be refreshed for each release. Passing these checks is a prerequisite, not a hardware qualification.
See [architecture](docs/architecture.md), [release checklist](docs/releasing.md),
[CONTRIBUTING.md](CONTRIBUTING.md) and [CHANGELOG.md](CHANGELOG.md).

Original project code is under the [MIT license](LICENSE). External tools,
Windows installation media and vendor drivers retain their respective licenses.
