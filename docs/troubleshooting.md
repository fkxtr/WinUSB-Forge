# Troubleshooting and recovery

| Message or symptom | Action |
| --- | --- |
| Required tool missing | Install the package providing the named command from your distribution; do not disable the check. |
| Device not detected | Reconnect it, run `devices`, and verify it is a whole USB disk with kernel identity information. |
| Device is protected or busy | Close applications and explicitly unmount its partitions. Active swap/holders require deliberate system administration; do not force past them. |
| Identity changed | Cancel the old selection and discover the devices again. Never reuse an earlier confirmation. |
| ISO cannot be read or inspected | Check the path and a trusted SHA-256; obtain a fresh legitimate ISO if it is corrupt. |
| Unsupported architecture | Use Windows 11 x64; a renamed ARM64 loader does not make an ISO compatible. |
| ESD exceeds FAT32 limit | Use a compatible ISO. Renaming ESD to WIM is not a conversion. This release does not convert oversized ESD. |
| File too large or invalid FAT path | The media cannot be represented safely in the supported layout. Do not omit the file or bypass the check. |
| USB capacity insufficient | Choose a larger USB. The image must fit the planner's maximum supported partition size. |
| Temporary disk full | Free local storage for extraction, fragments and a complete filesystem image, then restart. |
| Driver package incomplete | Extract the whole vendor package, including INF, SYS, CAT and referenced files. |
| Permission denied | Inspect as normal user. Only creation and raw USB verification use `sudo` from that user. |
| Write, flush or verification failed | Treat the USB as incomplete; resolve the cause, reconnect and recreate it. |
| Secure Boot rejects the installer | Check official media and vendor firmware guidance. File presence does not prove trusted signatures; do not disable security automatically. |
| SSD absent in Windows Setup | Obtain the appropriate F6 driver from the hardware vendor and load it in Setup. A matching PCI ID is not a guarantee. |

Do not unplug during writing or readback. There is no rollback after overwriting
partition metadata or content. The previous files are not preserved. Failed
verification must never be interpreted as a partially successful installer.
The writer uses an unmounted device; it does not leave a USB mount behind.

If filing an issue, include the version, command name (redact personal paths),
error code, distribution and relevant tool versions. A reduced report can be
created with `winusb-forge diagnose --export report.json`. Review the report
before posting. Do not attach an ISO, driver package, secrets or raw serials.

## Español

Ante una herramienta ausente, instala el paquete de tu distribución. Ante un
dispositivo ocupado, cierra sus aplicaciones y desmonta sus particiones sin
forzar. Si cambia la identidad, descúbrelo de nuevo y cancela la selección vieja.
Una ISO corrupta requiere comprobar su suma y sustituirla por una copia legítima.
Un ESD demasiado grande no se arregla cambiando su extensión.

Reserva espacio local además de capacidad en el USB. Aporta paquetes F6 completos
con sus archivos auxiliares. Usa `sudo` desde tu usuario solo al crear o verificar
el dispositivo. Si la escritura, sincronización o verificación falla, el medio
está incompleto: resuelve la causa y créalo de nuevo. No existe reversión de los
datos borrados. No desconectes durante escritura o relectura.

Para una incidencia incluye versión, código de error y versiones del sistema;
revisa el informe exportado antes de compartirlo y elimina datos personales.
Nunca adjuntes ISO, controladores, credenciales ni números de serie completos.
