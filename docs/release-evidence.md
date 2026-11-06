# Release candidate evidence — 2026-11-06

Version: **0.1.0rc1**. Scope: this Linux cloud checkout, using Python 3.12.14.
These observations describe the current development session. GitHub Actions has
been configured but has not been observed running remotely. Publication and a
new cloud-task restore are not established by these checks.

| Check | Observed result | Boundary |
| --- | --- | --- |
| Automated suite | 229 passed; 0 skipped | Simulated devices and temporary files; no real block-device writes |
| Ruff lint | Passed | Source/style rules, not proof of disk safety |
| Ruff formatting | Passed | Formatting consistency |
| Bandit | Passed | Static security findings only |
| mypy | Passed with `src --ignore-missing-imports` | Python type analysis |
| Python dependency advisory audit | 45 exact external package versions; no known vulnerabilities reported | Time-bound advisory result; excludes only this unpublished dependency-free project |
| Source packaging | Source archive built; required English/Spanish/security/docs/tests/tooling included | Archive-content verification |
| Clean wheel installation | Installed without dependencies or network in a fresh virtualenv; ran from `/tmp` | Independent of the editable checkout |
| Installed functional CLI | Inspected a generated UDF ISO with a two-index WIM using a Unicode path | Synthetic PE/BCD/WIM files, not bootable Windows |
| Interactive terminal | Spanish menu exercised at 40 columns; exit completed normally | No destructive choice selected |
| CLI command surface | English/Spanish help and create help executed | Documented argument syntax verified |
| Native tools | Synthetic WIM/SWM and FAT32 image checks | Generated fixtures are not Windows media |
| Hardware boot | Not run | No USB, Windows installer, Secure Boot or reference hardware qualification |

The external package audit includes pip 26.3. It was updated after an earlier
inventory found an advisory; the 45-package final query returned no known
vulnerabilities. This does not audit distribution-provided native binaries or
prove the absence of undisclosed defects.

Available native tool versions: 7-Zip 25.01, wimlib-imagex 1.14.4, dosfstools 4.2,
mtools 4.0.48, util-linux 2.41.5 and genisoimage 1.1.11. They were provisioned from
signature-verified Debian packages in this environment. Installation and runtime
instructions should continue to use each target distribution's maintained tools.
The signed `trixie-security` and `trixie-updates` channels were also checked.
`libntfs-3g89t64` was updated to `1:2022.10.3-5+deb13u3`; its packaged Debian
Security Team changelog identifies memory-safety fixes. This channel/update review
is separate from a full native vulnerability-database audit, which was not run.

The installed wimlib split/verify manuals were consulted. Access to Microsoft's
`learn.microsoft.com` was denied by the network proxy (HTTP 403), so those online
pages were not claimed as retrieved. See [references](references.md).

Safety review priorities included wrong-device selection, stale identity, mounted
or busy disks, hotplug, shell argument handling, untrusted filesystem paths,
privilege separation, dry-run, copy/flush/readback failures and false success.
Fixes and regression coverage are reflected in the current source/tests; this is
not a certification that the application is free of errors.

Run the documented development commands to obtain fresh evidence for a changed
revision. Hardware qualification remains a separate gate in
[validation.md](validation.md). A passing test count does not authorize dropping
the candidate label.

## Español

Evidencia de 0.1.0rc1 en este entorno Linux, Python 3.12.14: 229 pruebas superadas,
ninguna omitida; Ruff, formato, Bandit y mypy satisfactorios. Auditoría de 45
versiones exactas de paquetes Python externos sin vulnerabilidades conocidas
reportadas, tras actualizar pip a 26.3. Solo se excluye el propio proyecto local,
aún no publicado y sin dependencias. La auditoría no cubre binarios de la
distribución ni defectos desconocidos.

Se construyó y revisó el paquete fuente con documentación bilingüe y se ejecutó
la ayuda real de la CLI. Las verificaciones WIM/SWM y FAT32 utilizan fixtures
sintéticos. No se han probado USB reales, instalación de Windows, firmware
Secure Boot ni el hardware del caso de referencia. La CI remota y la publicación
no se han verificado. La consulta a Microsoft fue bloqueada con HTTP 403; sí se
consultaron los manuales locales de wimlib.

El wheel se instaló sin red ni dependencias en un virtualenv limpio y se ejecutó
desde `/tmp`: inspeccionó una ISO UDF sintética con WIM de dos índices y ruta
Unicode. Se comprobó el menú español en una terminal de 40 columnas. Los canales
firmados de seguridad de Debian aportaron una actualización de `libntfs-3g89t64`
a `1:2022.10.3-5+deb13u3`; esto no equivale a una auditoría completa de CVE nativos.

La revisión priorizó selección de disco, cambio de identidad, permisos, rutas,
fallos de copia/sincronización/verificación y mensajes de éxito incorrectos.
Estas evidencias no certifican ausencia de errores ni justifican una versión
estable sin completar las pruebas físicas.
