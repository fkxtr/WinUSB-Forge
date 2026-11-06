# Security and privacy

## Supported release

0.1.0rc1 is preliminary and has not been qualified on real USB hardware. There is
no claim of universal compatibility or absence of defects. Only the latest
reviewed candidate is intended to receive fixes while the first release is under
development.

## Report a vulnerability

Do not publish exploit details that could cause wrong-device writes in a public
issue. Use GitHub's private **Report a vulnerability** feature for this repository
if enabled. If it is unavailable, open an issue asking for a private contact
without attaching exploit details, credentials, proprietary media or logs. No
response deadline or preconfigured private reporting channel is claimed here.

## Disk safety model

- Only explicitly selected whole USB disks with sufficient live identity evidence
  can enter the writer. Internal, busy, mounted, read-only and ambiguous devices
  are rejected. Root, boot and home filesystems are covered by mounted-descendant
  rejection, including nested device relationships.
- A plan and device-specific typed confirmation precede destructive writes. There
  is no assume-yes/force bypass. The writer revalidates identity and uses a pinned,
  exclusively opened block descriptor. Device names and serials alone are unsafe.
- Untrusted media is inspected and the FAT32 image is prepared under the invoking
  normal user's identity before writing. Root without a known `sudo` origin user
  is rejected. Use trusted installed code when invoking it with `sudo`.
- The USB is not mounted by the writer. Raw writes, flushes and readback are checked;
  failures do not produce success. The previous data cannot be rolled back.
- Dry-run performs local preparation only and cannot enter the device writer.
- The program does not install Windows, alter the internal SSD, change firmware,
  enroll Secure Boot keys or execute a bootloader repair command.

Exclusive opens and identity checks reduce accidents; they do not defend against
another malicious privileged process or compromised firmware/kernel. Keep other
disk-management tools closed and disable competing automount actions where needed.
Use legitimate media from a trusted source. PE architecture and WIM verification
do not authenticate Microsoft signatures or prove that an ISO is free of malware.
A trusted SHA-256 confirms only correspondence to that reference digest.

## Privacy and dependencies

There is no telemetry or network activity in normal application operation. No
Windows product keys, passwords or GitHub credentials are requested. Operation
logs store timestamps, version and fixed event/error codes, not command arguments,
file contents or raw tool output. The location is
`~/.local/state/winusb-forge/events.jsonl` for the invoking user, or the directory
selected with `XDG_STATE_HOME`. A reduced
`diagnose --export PATH` report omits full serials and private file paths; inspect
it before sharing. The local terminal can show the paths and device identity
needed to make a safe selection.

The Python runtime has no third-party dependencies. System tools parse untrusted
files and remain part of the security boundary; install maintained distribution
packages. Dependency audit results are time-bound and do not assess every distro
binary. Never disable TLS, package signatures or artifact checksums when preparing
a development environment.

## Español

0.1.0rc1 es preliminar y no está validada en USB real. Para vulnerabilidades usa
la función privada de GitHub si está habilitada. Si no lo está, solicita un canal
privado sin publicar detalles de explotación ni datos personales.

Solo se escribe en un disco USB completo con identidad viva suficiente,
confirmación explícita y descriptor exclusivo. Se rechazan discos internos,
montados, ocupados, de solo lectura o ambiguos. Se prepara el medio con permisos
del usuario original de `sudo` y se reservan privilegios para el acceso al disco.
No se monta el USB, no se modifica el SSD ni el firmware y no hay reversión tras
una escritura. Dry-run nunca entra en el escritor de dispositivos.

Las protecciones no defienden contra otro proceso root malicioso, un kernel o
firmware comprometido. La verificación PE/WIM no autentica firmas de Microsoft ni
certifica ausencia de malware. Las herramientas externas deben estar actualizadas.

No hay telemetría, red ni recopilación de claves. Los registros guardan códigos
fijos, fecha y versión en `~/.local/state/winusb-forge/events.jsonl`, sin argumentos,
contenido privado o salida cruda. El informe reducido omite rutas privadas y
series completas; revísalo antes de compartirlo.
