# Changelog

## 0.1.0rc1 — 2026-11-06

First preliminary implementation for Windows 11 x64 USB creation on Linux:

- USB discovery, live identity safeguards and explicit per-device confirmation.
- ISO inspection, FAT32-compatible paths, WIM splitting, fitting ESD support and
  pre-write rejection of oversized ESD.
- MBR type `0x0C` FAT32 layout, local image preparation, checked writes and readback.
- Complete user-supplied F6 driver directories and UTF-16 PCI identification.
- English/Spanish terminal commands, dry-run planning and read-only diagnostics.
- Automated tests, package metadata, CI and security/release documentation.

This candidate has no verified Windows hardware boot result. See docs/validation.md
for the evidence boundary and outstanding acceptance matrix. This is not a stable
release announcement.

## Español

Primera implementación preliminar: detección y protección de USB, análisis de ISO,
WIM/SWM y ESD compatible, FAT32 MBR tipo `0x0C`, controladores F6, CLI bilingüe,
planificación sin escritura de USB y diagnóstico de solo lectura. Incluye pruebas
automatizadas, empaquetado y documentación de seguridad. No se ha verificado el
arranque de Windows en hardware real; no es un anuncio de versión estable.
