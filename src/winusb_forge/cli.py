"""A compact bilingual terminal interface shared by scripted and interactive use."""

from __future__ import annotations

import argparse
import json
import os
import pwd
import shutil
import sys
import tempfile
import textwrap
from pathlib import Path

from . import __version__
from .core import ForgeError, Runner, record_event, unprivileged
from .devices import Device, DeviceDiscovery, PartitionPlanner, Plan, SafetyGuard
from .diagnostics import diagnose
from .drivers import add_drivers, inspect_drivers
from .media import Media, inspect_tree
from .messages import ERROR_TEXT, terminal_text

TEXT = {
    "tagline": (
        "Windows installation media · Linux · UEFI x64",
        "Medios de instalación Windows · Linux · UEFI x64",
    ),
    "preliminary": (
        "Release candidate — hardware boot validation pending.",
        "Versión candidata — pendiente de validar el arranque en hardware.",
    ),
    "none": ("No USB disks detected.", "No se detectaron discos USB."),
    "blocked": ("Blocked", "Bloqueado"),
    "available": ("Available", "Disponible"),
    "inspect": (
        "Inspecting media and verifying Windows images…",
        "Analizando el medio y verificando las imágenes de Windows…",
    ),
    "valid": (
        "Media structure and image integrity verified.",
        "Estructura del medio e integridad de imágenes verificadas.",
    ),
    "plan": ("Preparation plan", "Plan de preparación"),
    "erase": ("ALL DATA ON THIS DISK WILL BE LOST.", "SE PERDERÁN TODOS LOS DATOS DE ESTE DISCO."),
    "layout": (
        "MBR/DOS · one FAT32 partition · type 0x0C",
        "MBR/DOS · una partición FAT32 · tipo 0x0C",
    ),
    "content": ("Content", "Contenido"),
    "files": ("files", "archivos"),
    "partition": ("New partition", "Partición nueva"),
    "unused": ("Unallocated capacity", "Capacidad sin asignar"),
    "existing": ("Existing partitions", "Particiones actuales"),
    "steps": (
        "Validate → build FAT32 image → verify → recheck identity → write → sync → read back",
        "Validar → construir FAT32 → verificar → comprobar identidad → "
        "escribir → sincronizar → releer",
    ),
    "dry": (
        "Plan complete. No device writes or writable mounts were performed. "
        "Temporary local staging was used.",
        "Plan terminado. No se escribió en dispositivos ni se montaron volúmenes en escritura. "
        "Se usó almacenamiento temporal local.",
    ),
    "confirm": ("To erase this disk, type exactly", "Para borrar este disco, escribe exactamente"),
    "success": (
        "Media verification passed. Safe to disconnect. Hardware boot not tested.",
        "Verificación del medio superada. Puedes desconectarlo. Arranque en hardware no probado.",
    ),
    "verified": (
        "Stored manifest, FAT32 layout and Windows images verified. Hardware boot not tested.",
        "Manifiesto guardado, estructura FAT32 e imágenes de Windows verificados. "
        "Arranque en hardware no probado.",
    ),
    "structural": (
        "Structure and Windows images verified; no original checksum manifest is available.",
        "Estructura e imágenes verificadas; no hay manifiesto original para comparar sumas.",
    ),
    "drivers": ("Driver files located", "Archivos del controlador localizados"),
    "pci": (
        "PCI matches indicate possible compatibility, not a guarantee.",
        "Las coincidencias PCI indican posible compatibilidad, sin garantizarla.",
    ),
    "load": (
        "In Windows Setup, choose Load driver and browse DRIVERS/STORAGE.",
        "En Windows Setup, elige Cargar controlador y busca DRIVERS/STORAGE.",
    ),
    "driver_add": (
        "Drivers are added during creation using --drivers. Recreate the USB to include them.",
        "Los controladores se añaden al crear el medio con --drivers. "
        "Recrea el USB para incluirlos.",
    ),
    "cancel": (
        "Cancelled. No further operations will run.",
        "Cancelado. No se ejecutarán más operaciones.",
    ),
    "partial": (
        "If writing had started, this USB is incomplete: recreate it before use.",
        "Si había comenzado la escritura, el USB está incompleto: recréalo antes de usarlo.",
    ),
    "error": ("Operation stopped", "Operación detenida"),
    "log_failed": (
        "Could not save the private event log.",
        "No se pudo guardar el registro privado de eventos.",
    ),
    "menu": (
        "Create Windows USB|Inspect Windows ISO|Detect USB devices|Verify existing USB|"
        "Add storage drivers|Linux / Dual Boot Diagnostics|Help|Exit",
        "Crear USB de Windows|Inspeccionar ISO de Windows|Detectar dispositivos USB|"
        "Verificar USB existente|Añadir controladores de almacenamiento|"
        "Diagnóstico Linux / arranque dual|Ayuda|Salir",
    ),
    "choice": ("Choose 1–8", "Elige 1–8"),
    "iso_prompt": ("ISO path", "Ruta de la ISO"),
    "dev_prompt": ("Whole USB disk path", "Ruta del disco USB completo"),
    "driver_prompt": ("Extracted driver directory", "Carpeta del controlador extraído"),
    "progress": ("Writing verified image", "Escribiendo imagen verificada"),
    "prepare_fat": (
        "Preparing and checking the temporary FAT32 image…",
        "Preparando y comprobando la imagen FAT32 temporal…",
    ),
    "verifying": ("Verifying USB content…", "Verificando el contenido del USB…"),
    "root_required": (
        "Run create/verify with sudo from your normal user account.",
        "Ejecuta create/verify con sudo desde tu cuenta de usuario habitual.",
    ),
    "tty_required": (
        "Destructive confirmation requires an interactive terminal.",
        "La confirmación de borrado requiere una terminal interactiva.",
    ),
}


def clean(value: object) -> str:
    """Device metadata and filenames must never inject terminal escapes."""
    return terminal_text(str(value))


class UI:
    def __init__(self, lang: str):
        self.lang = lang
        self.width = max(24, min(100, shutil.get_terminal_size((80, 24)).columns))
        self.color = (
            sys.stdout.isatty()
            and "NO_COLOR" not in os.environ
            and os.environ.get("TERM") != "dumb"
        )
        self.last_percent = -1

    def tr(self, key: str) -> str:
        pair = TEXT.get(key) or ERROR_TEXT.get(key)
        return pair[1 if self.lang == "es" else 0] if pair else key

    def say(self, text: object = "", *, accent: bool = False) -> None:
        text = clean(text)
        rendered = "\n".join(textwrap.wrap(text, self.width, break_long_words=True))
        print(f"\033[38;5;67m{rendered}\033[0m" if accent and self.color else rendered)

    def message(self, key: str) -> None:
        self.say(self.tr(key))

    def ask(self, key: str) -> str:
        return input(f"{self.tr(key)}: ").strip()

    def progress(self, done: int, total: int) -> None:
        percentage = min(100, int(done * 100 / total)) if total else 0
        if percentage != self.last_percent:
            self.last_percent = percentage
            if sys.stdout.isatty():
                print(
                    f"\r{self.tr('progress')}: {percentage:3d}%",
                    end="\n" if percentage == 100 else "",
                    flush=True,
                )


def parser(lang: str = "en") -> argparse.ArgumentParser:
    es = lang == "es"
    p = argparse.ArgumentParser(prog="winusb-forge", description=TEXT["tagline"][es])
    p.add_argument("--version", action="version", version=__version__)
    p.add_argument("--lang", choices=("en", "es"), default=lang, help="Idioma / Language")
    if es:
        p._optionals.title = "opciones"
        p._actions[0].help = "mostrar esta ayuda y salir"
        p._actions[1].help = "mostrar la versión y salir"
    subs = p.add_subparsers(dest="command", title="comandos" if es else "commands")
    subs.add_parser("devices", help="Detectar discos USB" if es else "Detect USB disks")
    for command in ("inspect", "plan", "create"):
        sub = subs.add_parser(command)
        sub.add_argument("--iso", required=True, type=Path)
        sub.add_argument(
            "--sha256", help="SHA-256 de referencia" if es else "Trusted reference SHA-256"
        )
        if command != "inspect":
            sub.add_argument("--device", required=True)
            sub.add_argument("--drivers", type=Path)
            sub.add_argument("--label", default="WIN11")
        if command == "create":
            sub.add_argument("--dry-run", "--plan", dest="dry_run", action="store_true")
    sub = subs.add_parser("verify")
    sub.add_argument("--device", required=True)
    sub = subs.add_parser("drivers")
    ds = sub.add_subparsers(dest="drivers_command", required=True)
    ds.add_parser("inspect").add_argument("path", type=Path)
    subs.add_parser("diagnose").add_argument("--export", type=Path)
    return p


def show_device(ui: UI, device: Device) -> None:
    ui.say(f"{device.path} · {device.vendor} {device.model} · {device.size / 10**9:.1f} GB")
    ui.say(
        f"USB · diskseq={device.diskseq} · serial=…{device.serial[-4:] if device.serial else '?'}"
    )


def show_plan(ui: UI, plan: Plan) -> None:
    ui.message("plan")
    show_device(ui, plan.device)
    ui.message("erase")
    ui.say(f"{ui.tr('existing')}: {len(plan.device.partitions)}")
    for part in plan.device.partitions:
        ui.say(f"  {part.path} · {part.fstype or '?'} · {part.size / 10**9:.2f} GB")
    ui.message("layout")
    for key, size in (
        ("content", plan.content_bytes),
        ("partition", plan.partition_bytes),
        ("unused", plan.unallocated_bytes),
    ):
        ui.say(f"{ui.tr(key)}: {size / 1024**3:.2f} GiB")
    ui.message("steps")


def execute(args: argparse.Namespace, ui: UI) -> None:
    runner = Runner(dry_run=bool(getattr(args, "dry_run", False) or args.command == "plan"))
    discovery = DeviceDiscovery(runner)
    guard = SafetyGuard(discovery)
    if args.command == "devices":
        with unprivileged():
            devices = [d for d in discovery.list() if d.transport == "usb"]
        if not devices:
            ui.message("none")
        for device in devices:
            show_device(ui, device)
            try:
                guard.validate(device)
                ui.message("available")
            except ForgeError as error:
                ui.say(f"{ui.tr('blocked')}: {ui.tr(error.code)}")
    elif args.command == "drivers":
        with unprivileged():
            info = inspect_drivers(args.path)
        ui.message("drivers")
        for pci in info.pci_ids:
            ui.say(f"PCI: {pci}")
        ui.message("pci")
        ui.message("load")
    elif args.command == "diagnose":
        with unprivileged():
            report = diagnose(runner)
            if args.export:
                # Never overwrite user files; exported fields exclude identifiers.
                fd = os.open(
                    args.export, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600
                )
                with os.fdopen(fd, "w") as stream:
                    json.dump(report, stream, indent=2)
                    stream.write("\n")
        for name, value in report.items():
            ui.say(f"{name}: {value}")
    elif args.command == "verify":
        if os.geteuid() != 0:
            raise ForgeError("root_required")
        from .writer import Writer

        device = discovery.select(args.device)
        ui.message("verifying")
        verification = Writer(runner, discovery, guard).verify(device)
        ui.message("verified" if verification.source_manifest else "structural")
    elif args.command in ("inspect", "plan", "create"):
        actually_write = args.command == "create" and not args.dry_run
        if actually_write and os.geteuid() != 0:
            raise ForgeError("root_required")
        if actually_write and not sys.stdin.isatty():
            raise ForgeError("tty_required")
        with unprivileged():
            with tempfile.TemporaryDirectory(prefix="winusb-forge-") as temporary:
                ui.message("inspect")
                prepared = Media(runner).prepare(args.iso, Path(temporary) / "media", args.sha256)
                if args.command == "inspect":
                    ui.message("valid")
                    ui.say(
                        f"{len(prepared.files)} {ui.tr('files')} · "
                        f"{prepared.total_bytes / 1024**3:.2f} GiB · {prepared.image_kind.upper()}"
                    )
                    return
                if args.drivers:
                    add_drivers(args.drivers, prepared.root)
                    prepared = inspect_tree(prepared.root, runner)
                device = discovery.select(args.device)
                guard.validate(device)
                plan = PartitionPlanner.plan(device, prepared.total_bytes, args.label)
                show_plan(ui, plan)
                if not actually_write:
                    ui.message("dry")
                    return
                ui.say(f"{ui.tr('confirm')}: {device.confirmation}")
                answer = input("> ")
                guard.confirm(device, answer)
                ui.message("prepare_fat")
                # Restore only for the writer entry point; writer drops privileges
                # again while constructing and checking the local FAT32 image.
                uid = os.geteuid()
                os.seteuid(0)
                try:
                    from .writer import Writer

                    Writer(runner, discovery, guard).create(
                        prepared, device, plan, answer, ui.progress
                    )
                finally:
                    os.seteuid(uid)
                ui.message("success")
                if args.drivers:
                    ui.message("load")


def interactive(ui: UI) -> list[str] | None:
    ui.say("WinUSB Forge", accent=True)
    ui.message("tagline")
    ui.message("preliminary")
    for index, item in enumerate(ui.tr("menu").split("|"), 1):
        ui.say(f"{index}. {item}")
    selection = ui.ask("choice")
    commands = {"3": ["devices"], "6": ["diagnose"], "7": ["--help"]}
    if selection == "8":
        return None
    if selection in commands:
        return commands[selection]
    if selection in ("1", "2"):
        cmd = ["create" if selection == "1" else "inspect", "--iso", ui.ask("iso_prompt")]
        if selection == "1":
            execute(parser(ui.lang).parse_args(["devices"]), ui)
            cmd += ["--device", ui.ask("dev_prompt")]
        return cmd
    if selection == "4":
        return ["verify", "--device", ui.ask("dev_prompt")]
    if selection == "5":
        ui.message("driver_add")
        return ["drivers", "inspect", ui.ask("driver_prompt")]
    raise ForgeError("selection")


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    lang = "es" if os.environ.get("LANG", "").startswith("es") else "en"
    if "--lang" in argv:
        index = argv.index("--lang")
        if index + 1 < len(argv) and argv[index + 1] in ("en", "es"):
            lang = argv[index + 1]
    p = parser(lang)
    args = p.parse_args(argv)
    ui = UI(args.lang)
    result = "ok"
    try:
        if not args.command:
            if not sys.stdin.isatty():
                p.print_help()
                return 0
            chosen = interactive(ui)
            if chosen is None:
                return 0
            args = p.parse_args(chosen)
        execute(args, ui)
        return 0
    except (EOFError, KeyboardInterrupt):
        result = "cancelled"
        ui.message("cancel")
        if args.command == "create" and not args.dry_run:
            ui.message("partial")
        return 130
    except (ForgeError, OSError) as error:
        result = error.code if isinstance(error, ForgeError) else type(error).__name__
        ui.say(f"{ui.tr('error')}: {ui.tr(result)}")
        if isinstance(error, ForgeError) and error.detail:
            ui.say(error.detail)
        if args.command == "create" and not args.dry_run:
            ui.message("partial")
        return 1
    finally:
        try:
            with unprivileged():
                home = Path(pwd.getpwuid(os.geteuid()).pw_dir)
                state = Path(os.environ.get("XDG_STATE_HOME", str(home / ".local/state")))
                record_event(
                    state / "winusb-forge/events.jsonl",
                    args.command or "menu",
                    result=result,
                )
        except (OSError, ForgeError, KeyError):
            # Logging failure does not turn successful disk verification into failure.
            ui.message("log_failed")
