"""Bilingual, actionable error summaries and terminal-safe technical details."""

ERROR_TEXT: dict[str, tuple[str, str]] = {
    "command_encoding": (
        "A tool returned unreadable text. Check its version and the input image.",
        "Una herramienta devolvió texto ilegible. Comprueba su versión y la imagen de entrada.",
    ),
    "architecture": (
        "Unsupported architecture. Use an official Windows x64 ISO.",
        "Arquitectura incompatible. Usa una ISO oficial de Windows x64.",
    ),
    "capacity": (
        "The content does not fit the supported USB layout. Check capacity and image size.",
        "El contenido no cabe en el diseño admitido. Comprueba la capacidad y el "
        "tamaño de la imagen.",
    ),
    "checksum": (
        "The ISO checksum does not match. Check the trusted reference before continuing.",
        "La suma de la ISO no coincide. Comprueba la referencia fiable antes de continuar.",
    ),
    "command_failed": (
        "A required tool failed. Check its installation and the input files.",
        "Una herramienta necesaria ha fallado. Comprueba su instalación y los archivos de entrada.",
    ),
    "command_timeout": (
        "A tool exceeded its time limit. Check storage access and available resources.",
        "Una herramienta superó el tiempo límite. Comprueba el almacenamiento y los recursos.",
    ),
    "confirmation": (
        "Confirmation did not match the selected device. No USB write was authorized.",
        "La confirmación no coincide con el dispositivo. No se autorizó la escritura en el USB.",
    ),
    "device_busy": (
        "The device is in use. Close applications and unmount its filesystems, then retry.",
        "El dispositivo está ocupado. Cierra las aplicaciones y desmonta sus sistemas de archivos.",
    ),
    "device_changed": (
        "The device identity changed. Select the USB again before continuing.",
        "La identidad del dispositivo cambió. Vuelve a seleccionar el USB antes de continuar.",
    ),
    "device_data": (
        "Device information is incomplete or invalid. Check lsblk and udev availability.",
        "La información del dispositivo es incompleta o inválida. Comprueba lsblk y udev.",
    ),
    "device_identity": (
        "The USB identity cannot be verified safely. Use a device with a stable unique identity.",
        "No se puede verificar la identidad del USB. Usa un dispositivo con "
        "identidad única estable.",
    ),
    "device_internal": (
        "Internal and non-USB disks are protected. Select a whole USB disk.",
        "Los discos internos y no USB están protegidos. Selecciona un disco USB completo.",
    ),
    "device_missing": (
        "The USB disk was not found. Reconnect it and run devices again.",
        "No se encontró el disco USB. Vuelve a conectarlo y ejecuta devices de nuevo.",
    ),
    "device_path": (
        "Select an absolute path to a whole USB disk, not a partition.",
        "Selecciona una ruta absoluta a un disco USB completo, no a una partición.",
    ),
    "device_read_only": (
        "The device is write-protected. Check its physical lock and kernel status.",
        "El dispositivo está protegido contra escritura. Comprueba su bloqueo físico y su estado.",
    ),
    "device_sector": (
        "This release requires a USB with 512-byte logical sectors.",
        "Esta versión requiere un USB con sectores lógicos de 512 bytes.",
    ),
    "driver_invalid": (
        "The driver package is incomplete or unsupported. Supply its full extracted "
        "INF/SYS/CAT tree.",
        "El paquete de controladores está incompleto o no se admite. Aporta todos "
        "sus INF, SYS y CAT.",
    ),
    "dry_run_write": (
        "A write was blocked by dry-run. Stop and report this unexpected operation.",
        "Dry-run bloqueó una escritura. Detén el proceso e informa de esta operación inesperada.",
    ),
    "esd_too_large": (
        "This ESD exceeds FAT32. Use an official ISO containing a WIM image instead.",
        "Este ESD supera el límite FAT32. Usa una ISO oficial que contenga una imagen WIM.",
    ),
    "file_too_large": (
        "A file exceeds the FAT32 limit. Only install.wim can be split automatically.",
        "Un archivo supera el límite FAT32. Solo install.wim se puede dividir automáticamente.",
    ),
    "invalid_command": (
        "An internal command is invalid. Stop and report this error.",
        "Un comando interno no es válido. Detén el proceso e informa de este error.",
    ),
    "iso_changed": (
        "The ISO changed during inspection. Use an unchanged local copy and retry.",
        "La ISO cambió durante el análisis. Usa una copia local sin cambios y vuelve a intentarlo.",
    ),
    "iso_invalid": (
        "The media is incomplete, corrupt or unsupported. Check the ISO and its trusted checksum.",
        "El medio está incompleto, dañado o no se admite. Comprueba la ISO y su "
        "suma de referencia.",
    ),
    "iso_missing": (
        "The ISO is missing or empty. Select an existing, readable regular ISO file.",
        "La ISO no existe o está vacía. Selecciona un archivo ISO regular existente y legible.",
    ),
    "label": (
        "Use a label of 1–11 uppercase letters, digits or underscores.",
        "Usa una etiqueta de 1 a 11 letras mayúsculas, cifras o guiones bajos.",
    ),
    "missing_tool": (
        "A required tool is missing. Install the dependency listed in the technical detail.",
        "Falta una herramienta necesaria. Instala la dependencia indicada en el detalle técnico.",
    ),
    "partition_invalid": (
        "The partition plan is invalid. Rebuild the plan from the current ISO and USB.",
        "El plan de particiones no es válido. Calcula otro plan con la ISO y el USB actuales.",
    ),
    "permissions": (
        "This operation needs USB write permission. Follow the documented sudo invocation.",
        "Esta operación necesita permiso de escritura USB. Usa la invocación sudo documentada.",
    ),
    "root_required": (
        "This operation needs device access. Run it with sudo from your regular user account.",
        "Esta operación necesita acceso al dispositivo. Ejecútala con sudo desde tu "
        "cuenta habitual.",
    ),
    "selection": (
        "The selection is not valid. Choose one of the displayed options.",
        "La selección no es válida. Elige una de las opciones mostradas.",
    ),
    "space": (
        "There is not enough temporary disk space. Choose a larger staging location.",
        "No hay suficiente espacio temporal. Elige una ubicación de preparación con más capacidad.",
    ),
    "split_failed": (
        "The Windows image could not be split safely. Check free space and the original ISO.",
        "No se pudo dividir la imagen de forma segura. Comprueba el espacio libre y "
        "la ISO original.",
    ),
    "staging_space": (
        "There is not enough space to build and verify the USB image. Free temporary disk space.",
        "Falta espacio para crear y verificar la imagen USB. Libera espacio en el disco temporal.",
    ),
    "sudo_user_required": (
        "Start from a regular user account with sudo so image tools can run without "
        "root privileges.",
        "Inicia desde una cuenta habitual con sudo para analizar imágenes sin privilegios root.",
    ),
    "tty_required": (
        "Destructive confirmation requires an interactive terminal. Run create from a terminal.",
        "La confirmación destructiva requiere una terminal interactiva. Ejecuta "
        "create en una terminal.",
    ),
    "unsafe_log": (
        "The log location has unsafe permissions or ownership. Choose a private log location.",
        "La ubicación del registro no tiene permisos o propietario seguros. Elige "
        "una ubicación privada.",
    ),
    "unsafe_path": (
        "A path is unsafe or incompatible with FAT32. Check names, links and duplicate filenames.",
        "Una ruta no es segura o compatible con FAT32. Comprueba nombres, enlaces y duplicados.",
    ),
    "unsafe_tool": (
        "An elevated command resolves to an untrusted executable. Install it in a "
        "root-owned location.",
        "Un comando elevado usa un ejecutable no fiable. Instálalo en una ubicación "
        "propiedad de root.",
    ),
    "verification": (
        "Media verification failed. Do not use this USB installer; recreate it from a trusted ISO.",
        "La verificación falló. No uses este instalador USB; créalo de nuevo desde una ISO fiable.",
    ),
    "write_failed": (
        "A device write failed. The USB is incomplete; check the connection and "
        "recreate the medium.",
        "Falló una escritura. El USB está incompleto; comprueba la conexión y "
        "vuelve a crear el medio.",
    ),
    "write_incomplete": (
        "USB creation did not finish. Recreate the medium before using it; existing "
        "data may be lost.",
        "La creación del USB no terminó. Créalo de nuevo antes de usarlo; puede "
        "haber datos perdidos.",
    ),
}


def terminal_text(value: object, *, limit: int = 500) -> str:
    """Escape controls, ANSI sequences and bidi controls in untrusted detail strings."""
    text = str(value)
    escaped = "".join(char if char.isprintable() else ascii(char)[1:-1] for char in text)
    return escaped[:limit] + ("…" if len(escaped) > limit else "")
