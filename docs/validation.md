# Validation status

Release: **0.1.0rc1 — preliminary; not hardware-qualified**.

Automated checks must be run from the current checkout; saved transcripts belong
to the revision and environment in which they were produced. Do not carry a test
count forward after changing tests. The [release evidence](release-evidence.md) records the checks actually executed
in this development environment.

| Area | Evidence required | Limit of the evidence |
| --- | --- | --- |
| Discovery and identity | Simulated lsblk/sysfs, missing data, changed diskseq, duplicate models | Does not reproduce every kernel/USB bridge |
| Safety | Root/EFI/home mounts, busy/RO/internal disks, bad confirmation, hotplug changes | Does not guarantee safety against a malicious root process |
| Dry-run | Write backend never entered; USB bytes unchanged in simulation | Local staging files are still created |
| Media | Missing/invalid x64 loader, WIM/ESD limits, hashes and SWM structure | Synthetic images are not Windows installation media |
| Drivers | UTF-8/UTF-16 INF, PCI ID 8086:467F, missing SYS/CAT | Neither signature nor actual driver compatibility validation |
| Writer | Simulated copy, write/flush/readback failure and cleanup | No actual USB flash controller tested |
| Installation | Wheel build and fresh virtualenv CLI invocation | Distro system tools still need separate installation |
| Static analysis | Ruff, Bandit, dependency audit | Findings can change as advisories and tools change |

## Hardware qualification still outstanding

A maintainer needs explicit access to an expendable USB and a machine on which
boot testing is authorized. Record the exact release, ISO source and SHA-256,
distribution and kernel, tool versions, USB model/size, motherboard/firmware,
partition layout, Secure Boot state and observed result. Redact serial numbers.

1. Test a legitimate Windows 11 x64 ISO containing a small WIM, a large WIM and a
   fitting ESD. Check all expected editions in Windows Setup.
2. Check fresh-device creation and independently verify files and FAT32 metadata.
3. Boot UEFI with Secure Boot enabled and disabled where policy permits; record
   loader acceptance and the Windows Setup screen separately.
4. Confirm Windows Setup sees both installer and driver directories. Load a
   vendor F6 package on suitable Intel RST/VMD hardware; confirm target SSD
   detection without installing or modifying that SSD.
5. Test reconnect, different USB ports, 64/128 GB devices and supported kernels.
   Perform unplug/power-loss tests only on disposable media and report partial
   outcomes without relying on the damaged filesystem.
6. Validate Mint, Ubuntu, Debian and Fedora individually. A package list is not
   distribution certification.

No HP OMEN, Kingston, Intel RST/VMD, Windows installation or Secure Boot success
is claimed by the software tests. ARM64, legacy BIOS, 4Kn disks, oversized ESD
conversion, ISO9660-only media, internal non-BMP filenames and in-place driver
addition are not supported in this release. Host ISO paths support full Unicode;
BMP internal paths with accents/Japanese are tested with mtools.

## Español

Estado: **0.1.0rc1 preliminar, sin cualificación en hardware**. Las pruebas
simulan discos y utilizan archivos temporales. Los resultados reales ejecutados
se detallan en el informe final; no se fija aquí un número que pueda quedar
obsoleto. Los casos sintéticos no equivalen a una ISO de Windows ni a una prueba
de arranque.

Antes de una versión estable hay que validar, con autorización y un USB
prescindible, las ISO y sus ediciones, el arranque UEFI/Secure Boot, las carpetas
de controladores y la detección del SSD con Intel RST/VMD. Registrar versión,
sumas de ISO, firmware, distribución, kernel y herramientas, omitiendo números
de serie. Probar por separado cada distribución anunciada. Ninguna prueba de
software acredita el hardware HP/Kingston del caso de referencia.
