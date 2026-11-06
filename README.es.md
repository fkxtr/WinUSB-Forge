# WinUSB Forge

**A reliable Windows USB installer creator for Linux**

Crea un instalador de Windows 11 x64 para UEFI desde tu propia ISO, con un plan de
particionado revisable, confirmación explícita de identidad, gestión de imágenes
para FAT32 y verificación del contenido. [English documentation](README.md).

**La versión 0.1.0rc1 es preliminar.** Las pruebas automatizadas y sintéticas no
prueban que un USB arranque Windows. El proyecto no ha verificado un USB real,
una instalación de Windows, firmware Secure Boot ni el hardware HP/Kingston del
caso de referencia. Consulta [validación y límites](docs/validation.md) y
[evidencias registradas](docs/release-evidence.md).
La creación borra el USB seleccionado: guarda antes una copia de sus datos.

## Requisitos e instalación

Linux, Python 3.11 o posterior, una ISO legítima de Windows 11 x64 y un USB cuyos
datos puedas borrar. Esta versión admite discos USB con sectores lógicos de
512 bytes e identidad `diskseq` proporcionada por Linux. Rechaza discos internos,
montados, ocupados, protegidos contra escritura o con identidad incompleta.
El número de serie por sí solo no acredita la identidad de un disco.

Herramientas necesarias: `lsblk`, `7z`, `wimlib-imagex`, `mkfs.vfat`, `fsck.fat`,
`mcopy` y `mmd`. Los diagnósticos pueden utilizar además `mokutil` y `efibootmgr`.
No hay dependencias Python de terceros en ejecución. Instala paquetes mantenidos
por tu distribución y mantenlos actualizados.

Debian / Ubuntu / Linux Mint:

```sh
sudo apt install python3 python3-venv util-linux p7zip-full wimtools dosfstools mtools
```

Fedora; los nombres dependen de su versión:

```sh
sudo dnf install python3 util-linux 7zip wimlib-utils dosfstools mtools
```

El programa admite `7z` o `7zz` y usa el ejecutable instalado. No sustituyas un
paquete ausente por un binario de procedencia desconocida.

Instalación desde un checkout revisado; no se afirma que exista una publicación
en PyPI:

```sh
git clone https://github.com/fkxtr/WinUSB-Forge.git
cd WinUSB-Forge
python3 -m venv .venv
.venv/bin/python -m pip install .
.venv/bin/winusb-forge --lang es --help
```

Reserva espacio temporal local para el contenido extraído y los fragmentos WIM.
Construir la imagen exige además dos veces el tamaño de partición previsto, más
el contenido preparado y 64 MiB: la segunda imagen es una copia privada fijada
y verificada de nuevo antes de abrir el USB. La inspección puede exigir dos veces
el tamaño extraído de la ISO; son comprobaciones conservadoras del espacio máximo. El espacio del USB y el
espacio temporal son requisitos distintos. Con las dependencias instaladas, el
programa funciona sin conexión. No descarga Windows ni controladores.

## Primer uso

```sh
.venv/bin/winusb-forge --lang es
```

El menú permite crear el USB, inspeccionar la ISO, descubrir dispositivos,
verificar el medio, inspeccionar/incluir controladores, consultar diagnósticos de
Linux y acceder a la ayuda. La CLI y el menú comparten las protecciones. Los
colores son opcionales y no se necesita una biblioteca de terminal. `Ctrl+C`
cancela; si la escritura ya comenzó, habrá que recrear el USB.

Primero inspecciona como usuario normal:

```sh
.venv/bin/winusb-forge --lang es devices
.venv/bin/winusb-forge --lang es inspect --iso '/ruta/Windows 11 x64.iso'
.venv/bin/winusb-forge --lang es drivers inspect '/ruta/Controladores F6 extraídos'
.venv/bin/winusb-forge --lang es diagnose
```

En los ejemplos siguientes, sustituye todo `/dev/disk/by-id/usb-TU_DISPOSITIVO`
por la ruta real del disco USB completo. No elijas un enlace `-part1`. Comprueba
modelo y capacidad frente al dispositivo físico. Cierra los exploradores de
archivos y desmonta explícitamente las particiones antes de planificar: el
programa no desmonta sistemas de archivos existentes silenciosamente.

```sh
.venv/bin/winusb-forge --lang es plan \
  --iso '/ruta/Windows 11 x64.iso' \
  --device /dev/disk/by-id/usb-TU_DISPOSITIVO

.venv/bin/winusb-forge --lang es create --dry-run \
  --iso '/ruta/Windows 11 x64.iso' \
  --device /dev/disk/by-id/usb-TU_DISPOSITIVO \
  --drivers '/ruta/Controladores F6 extraídos'
```

`plan`, `create --plan` y `create --dry-run` pueden escribir archivos temporales
locales para analizar y transformar el medio. Nunca particionan ni escriben el
USB ni lo montan en modo escritura. No son modos sin E/S local. Puedes añadir
`--sha256` con una suma SHA-256 confiable de 64 caracteres para verificar la ISO.

La creación exige `sudo` desde el usuario normal; se rechaza root sin ese usuario
de origen. Para crear desde el menú, inicia `sudo .venv/bin/winusb-forge --lang es`.
También exige escribir la frase exacta que muestra el programa,
que incluye la identidad del disco. No existe una opción de aceptación
automática. No reutilices una frase de una ejecución anterior.

```sh
sudo .venv/bin/winusb-forge --lang es create \
  --iso '/ruta/Windows 11 x64.iso' \
  --device /dev/disk/by-id/usb-TU_DISPOSITIVO \
  --drivers '/ruta/Controladores F6 extraídos' \
  --label WIN11

sudo .venv/bin/winusb-forge --lang es verify \
  --device /dev/disk/by-id/usb-TU_DISPOSITIVO
```

Usa rutas absolutas para la ISO al cambiar de usuario. La verificación abre el
USB para lectura y no lo repara. Superar la comprobación de estructura e
integridad no acredita un arranque real, una firma aceptada por Secure Boot ni
una instalación satisfactoria de Windows.

## Diseño del medio, FAT32, WIM y ESD

El diseño utiliza MBR/DOS y una partición primaria FAT32 LBA de tipo `0x0C`, con
etiqueta `WIN11`. El tamaño se calcula según el contenido preparado y un margen,
con un límite de 32 GiB. En unidades de 64, 128 o más GB, el espacio restante se
deja sin asignar y aparece en el plan. No se crea una partición EFI System
adicional, una partición NTFS ni un cargador de terceros.

Se comprueba que `efi/boot/bootx64.efi` sea un ejecutable PE x64 y que existan
`sources/boot.wim` y una imagen de instalación admitida. La ISO debe usar UDF,
el formato óptico oficial de Windows; no se admiten imágenes solo ISO9660. La
ruta de la ISO admite Unicode completo. Los nombres internos de medios y drivers
admiten Unicode BMP, incluidos acentos y japonés, pero se rechazan caracteres
no BMP como emoji antes de escribir porque mtools no los conserva de forma segura. FAT32 acepta como máximo
4 GiB menos 1 byte por archivo. Si `install.wim` supera el límite, wimlib genera
`install.swm`, `install2.swm`, etc., juntos en `sources`. El WIM original no se
copia junto a los fragmentos. Se verifican sus tamaños y su lectura con wimlib.
Un `install.esd` que cabe se copia; uno demasiado grande se rechaza antes de
modificar el USB. No se promete una conversión de ediciones no implementada.

Windows ARM64, BIOS Legacy e imágenes modificadas quedan fuera del alcance.
Windows 10 no está validado. Secure Boot depende del firmware y de Microsoft:
el programa copia el cargador aportado, no certifica sus firmas, no registra
claves, no desactiva Secure Boot y no elude requisitos de TPM o licencia.

## Controladores Intel RST/VMD y arranque dual

Aporta la carpeta completa del paquete F6 extraído y obtenido del fabricante.
El analizador de INF reconoce UTF-8 y UTF-16, incluido el caso `8086:467F`.
Comprueba la presencia de SYS/CAT necesarios y conserva el árbol de directorios
en `DRIVERS/STORAGE`. Una coincidencia PCI es un indicio, no una garantía de
compatibilidad ni de firma. No se distribuyen ni descargan drivers propietarios.

En la pantalla de selección de disco de Windows Setup, pulsa **Cargar
controlador**, abre `DRIVERS/STORAGE` en el USB y selecciona el controlador x64
adecuado del fabricante. Esta versión no inyecta drivers en `boot.wim`. Para
incluirlos usa `--drivers` al crear el USB; no se admite añadirlos en el sitio a
un USB ya preparado.

`diagnose` consulta información de Linux y UEFI cuando las herramientas y
permisos lo permiten. La información inaccesible se presenta como no disponible.
Nunca cambia el orden de arranque, instala GRUB ni modifica el SSD. Consulta las
[notas de arranque dual](docs/dual-boot.md).

## Errores, recuperación y privacidad

Un fallo crítico detiene las operaciones posteriores. Si hay interrupción,
desconexión, diferencia de integridad o error de sincronización, el USB queda
incompleto: no lo uses para arrancar; resuelve la causa, reconecta, inspecciona y
créalo de nuevo. No desconectes el USB durante la escritura o verificación.

Si faltan herramientas, instala el paquete de tu distribución. Si el disco está
ocupado, cierra sus aplicaciones y desmonta sus particiones sin forzarlo. Si la
identidad cambia, vuelve a descubrir y seleccionar el dispositivo. Si falla la
ISO, verifica su suma con la fuente oficial. Si el ESD es demasiado grande,
obtén una ISO compatible: no renombres ESD a WIM. Si falta espacio, utiliza un
USB con capacidad suficiente y libera espacio temporal local. Los mensajes de
permiso no justifican ejecutar las operaciones de lectura con privilegios.

No hay telemetría, solicitudes de red, entrada de credenciales ni recopilación
de claves de Windows. Los registros guardan códigos fijos, fecha y versión en
`~/.local/state/winusb-forge/events.jsonl` (o en `XDG_STATE_HOME`), sin contenido de
archivos ni credenciales.
`diagnose --export RUTA` genera un informe reducido; revísalo antes de publicarlo.
Consulta [SECURITY.md](SECURITY.md) y la sección española de los documentos técnicos.

## Desarrollo y publicación

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

CI utiliza dispositivos simulados y archivos temporales, y nunca formatea discos
reales. La auditoría incluye versiones exactas de todas las distribuciones Python
externas instaladas; solo excluye el proyecto local, aún no publicado y sin
dependencias, cubierto por revisión y análisis estático. Debe actualizarse en
cada publicación. Estas comprobaciones no sustituyen las pruebas físicas. Consulta
[arquitectura](docs/architecture.md), [validación](docs/validation.md),
[publicación](docs/releasing.md), [CONTRIBUTING.md](CONTRIBUTING.md) y
[CHANGELOG.md](CHANGELOG.md).

El código original se distribuye bajo licencia [MIT](LICENSE). Las herramientas
externas, los medios de Windows y los drivers conservan sus propias licencias.
