# Architecture and disk-safety boundaries

`core.py` contains checked subprocess execution, structured errors, temporary
privilege dropping and privacy-oriented event logging. External commands receive
argument arrays; shell evaluation is not used. Error details are for the local
terminal, while persistent event logs contain fixed codes.

`devices.py` interprets `lsblk --json`, sysfs and stable device links. It binds a
selection to kernel device identity, checks the physical USB ancestry and rejects
read-only disks, mounted descendants, active holders and incomplete information.
The planner allocates one MBR type `0x0C` FAT32 partition with capacity margin and
reports unused capacity. `diskseq` changes distinguish a newly attached device
from a previous occupant of the same `/dev` path.

`media.py` extracts and inspects the ISO in a temporary local staging area. It
checks portable FAT32 paths, case collisions, the x64 PE loader, required Windows
files, WIM readability and per-file size. WIM splitting happens before any USB
write. `drivers.py` inspects INF encodings and packages and preserves the supplied
directory tree. A SHA-256 manifest binds staged files to copied content.

`writer.py` prepares FAT32 in a regular temporary image with dosfstools and
mtools. A private root-owned anonymous snapshot is then verified again before
opening the USB and copying through a pinned block-device descriptor. The peak
check requires twice the partition size, plus staged content and 64 MiB, beyond
the source tree. Exclusive opening,
live identity checks, flushes and readback are part of the write boundary. It does
not mount the USB, so there is no USB mount to leave behind after a copy failure.
It has no rollback of overwritten data: failures leave an incomplete target.

`cli.py` owns menu and command dispatch, language selection, readable plans,
confirmation and progress. Read-only commands run as a normal user. Creation and
raw-device verification require `sudo` from a normal user; the process drops back
to that user's identity for untrusted archive/media processing and staging. Native
subprocesses also permanently drop real-user and group privileges and use a
UTF-8 locale, so they cannot regain root. A
root login without the original invoking user is rejected. No flag bypasses the
safety guard or confirmation. `diagnostics.py` is read-only and independent of
USB preparation.

The development backend uses injected command/device interfaces and temporary
regular files. It must never turn a simulated device into an actual `/dev` write.
Tests demonstrate software behavior under their model; the hardware matrix is a
separate release prerequisite.

## Español

El núcleo separa lectura, preparación local y escritura privilegiada. El análisis
de ISO y drivers trabaja con los permisos del usuario que llamó a `sudo`. La
selección se vincula a información viva de `lsblk` y sysfs, incluyendo `diskseq`;
una ruta o un número de serie no bastan. Las identidades incompletas se rechazan.

La imagen FAT32 se construye en un archivo temporal con dosfstools y mtools.
Una copia anónima privada se fija y verifica de nuevo antes de abrir el USB.
Los subprocesos nativos pierden permanentemente los permisos root y utilizan
una configuración regional UTF-8.
Solo después de validar el contenido y confirmar la identidad se escribe mediante
un descriptor exclusivo del disco. Se sincroniza y relee el contenido. No se
monta el USB. No existe reversión de los datos borrados: un fallo de escritura
exige recrear el medio. El diagnóstico de arranque es una función independiente
y nunca modifica firmware o particiones.

Las pruebas usan interfaces inyectadas, dispositivos simulados y archivos
regulares temporales. No acreditan el comportamiento de un USB o firmware real.
