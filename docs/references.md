# Technical references

- [Microsoft: Install Windows from a USB flash drive](https://learn.microsoft.com/en-us/windows-hardware/manufacture/desktop/install-windows-from-a-usb-flash-drive)
- [Microsoft: Split a Windows image](https://learn.microsoft.com/en-us/windows-hardware/manufacture/desktop/split-a-windows-image--wim--file-to-span-across-multiple-dvds)
- [Intel: F6 driver loading](https://www.intel.com/content/www/us/en/support/articles/000091139/memory-and-storage.html)
- [wimlib: wimlib-imagex split](https://wimlib.net/man1/wimlib-imagex-split.html)
- [wimlib: wimlib-imagex verify](https://wimlib.net/man1/wimlib-imagex-verify.html)
- Linux kernel `diskseq` and block-device ioctl documentation, and installed
  `lsblk`, `mkfs.fat`, `fsck.fat`, `mcopy` and `mmd` manual pages.

On 2026-11-06 this development environment's network proxy rejected access to
`learn.microsoft.com` with HTTP 403. The Microsoft/Intel links identify the
intended authoritative references; they are not a claim that those pages were
retrieved in this session. The installed wimlib 1.14.4 split/verify manuals were consulted locally. They
confirm that a fragment can exceed the requested size when a single resource is
larger, which is why output sizes must be checked. Split verification uses
`--ref=install*.swm`. The available toolchain was 7-Zip 25.01, dosfstools 4.2,
mtools 4.0.48, util-linux 2.41.5 and genisoimage 1.1.11. Hardware behavior remains
unverified as described in validation.md.

## Español

Las fuentes originales anteriores son las referencias técnicas previstas. El
proxy del entorno rechazó `learn.microsoft.com` con HTTP 403 el 2026-11-06; no se
afirma haber leído esas páginas durante esta sesión. Se consultaron localmente los manuales de división y verificación de wimlib
1.14.4: un recurso grande puede superar el tamaño solicitado de fragmento, por
lo que es obligatorio comprobar cada tamaño de salida. El arranque en hardware
sigue pendiente.
