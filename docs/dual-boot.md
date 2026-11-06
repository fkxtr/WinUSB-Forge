# Linux and dual-boot diagnostics

`winusb-forge diagnose` is read-only. It checks firmware mode through sysfs,
consults the installed diagnostic tools when available and reports only what can
be observed. Missing EFI variables, insufficient permissions or unavailable
`mokutil`/`efibootmgr` do not establish that Secure Boot is disabled or that a boot
entry is absent. Containers usually cannot inspect host firmware reliably.

USB creation does not resize Linux, prepare an SSD partition, install Windows or
restore a boot menu. Before a separate Windows installation, back up data and
recovery keys and follow your distribution and hardware vendor documentation.
An encrypted disk or a BitLocker-protected Windows installation needs additional
planning outside this tool.

For a missing menu, these are inspection commands, not repairs:

```sh
lsblk --fs
efibootmgr -v
mokutil --sb-state
```

Firmware entries and a GRUB configuration are different layers. Reinstalling a
bootloader or generating its configuration without identifying the correct
system can make recovery harder. This project deliberately supplies no universal
`grub-install`, `update-grub` or `efibootmgr -o` recipe. Use the recovery instructions
for the installed distribution and its actual UEFI partition, and obtain separate
authorization before changing boot configuration. The program never runs those
repair commands.

## Español

`diagnose` consulta el modo firmware y las herramientas disponibles. Un permiso
insuficiente, variables EFI inaccesibles o una herramienta ausente no prueban que
Secure Boot esté desactivado ni que falte una entrada. Los contenedores pueden
carecer de acceso al firmware real.

Crear el USB no redimensiona Linux, modifica el SSD, instala Windows ni repara
GRUB. Haz copias de seguridad y guarda las claves de recuperación antes de una
instalación independiente. `lsblk --fs`, `efibootmgr -v` y `mokutil --sb-state`
son consultas. La reparación depende de la distribución, la partición UEFI y el
sistema instalado; no hay una receta universal segura. WinUSB Forge nunca ejecuta
comandos para reinstalar GRUB o cambiar el orden de arranque.
