#!/usr/bin/env python3

"""Profile-driven, cross-platform OpenHarmony QEMU launcher.

The module exposes a small command-line entry point (:func:`main`) plus a set of
pure helper functions so that product wrappers (``qemu_run.sh`` / ``qemu_run.cmd``)
can delegate all lifecycle logic to a single, profile-driven implementation.
"""

from __future__ import annotations

import argparse
import contextlib
import datetime as dt
import errno
import hashlib
import json
import os
import platform
import re
import shlex
import shutil
import signal
import socket
import stat
import subprocess
import sys
import tarfile
import tempfile
import time
import types
import zipfile
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any, Dict, Iterable, List, NoReturn, Optional, Sequence, Tuple


# --- Module-level constants ---------------------------------------------------

FORMAT_VERSION = 2
COMMANDS = {"run", "create", "list", "status", "stop", "reset", "delete", "diagnose", "print-command"}
EXIT_CLI = 2
EXIT_QEMU = 3
EXIT_IMAGE = 4
EXIT_BUSY = 5
EXIT_INSTANCE = 6
EXIT_START = 7
EXIT_PLATFORM = 8
MAX_ARCHIVE_FILES = 10000
MAX_ARCHIVE_BYTES = 64 * 1024 * 1024 * 1024
QCOW2_CREATE_OPTIONS = "cluster_size=65536,lazy_refcounts=off"


# --- Exceptions and generic helpers ------------------------------------------


class LauncherError(RuntimeError):
    def __init__(self, message: str, code: int = 1):
        super().__init__(message)
        self.code = code


def fail(message: str, code: int = 1) -> NoReturn:
    raise LauncherError(message, code)


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def canonical(path: Path) -> Path:
    return path.expanduser().resolve(strict=False)


def path_is_within(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def atomic_write_json(path: Path, data: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + f".tmp.{os.getpid()}")
    with temporary.open("w", encoding="utf-8", newline="\n") as stream:
        json.dump(data, stream, indent=2, sort_keys=True)
        stream.write("\n")
    os.chmod(temporary, 0o600)
    os.replace(temporary, path)


def run_checked(argv: Sequence[str], *, code: int = 1, text: bool = True) -> subprocess.CompletedProcess:
    try:
        result = subprocess.run(list(argv), capture_output=True, text=text, check=False)
    except OSError as error:
        fail(f"cannot execute {argv[0]}: {error}", code)
    if result.returncode != 0:
        stderr = (result.stderr or "").strip()
        fail(f"command failed ({result.returncode}): {display_command(argv)}" + (f"\n{stderr}" if stderr else ""), code)
    return result


def display_command(argv: Sequence[str]) -> str:
    if os.name == "nt":
        return subprocess.list2cmdline(list(argv))
    return shlex.join(list(argv))


def parse_version(value: str) -> Tuple[int, ...]:
    match = re.search(r"(\d+)(?:\.(\d+))?(?:\.(\d+))?", value)
    if not match:
        return (0,)
    return tuple(int(part or 0) for part in match.groups())


def normalize_arch(value: str) -> str:
    lowered = value.lower()
    if lowered in {"amd64", "x86_64", "x64"}:
        return "x86_64"
    if lowered in {"arm64", "aarch64"}:
        return "aarch64"
    if lowered.startswith("arm"):
        return "arm"
    return lowered


def host_os() -> str:
    name = platform.system().lower()
    return {"darwin": "macos", "windows": "windows", "linux": "linux"}.get(name, name)


def repo_root_from_launcher() -> Path:
    # .../vendor/ohemu/common/qemu_launcher_lib/launcher.py -> source root
    return Path(__file__).resolve().parents[5]


# --- Profile loading and validation ------------------------------------------


def load_profile(path: Path) -> Dict[str, Any]:
    path = canonical(path)
    try:
        with path.open("r", encoding="utf-8") as stream:
            profile = json.load(stream)
    except (OSError, json.JSONDecodeError) as error:
        fail(f"cannot load profile {path}: {error}", EXIT_CLI)
    required = {
        "schema_version", "id", "product_name", "guest_arch", "port_slot", "qemu_binaries",
        "default_image_paths", "default_instance_root", "machine_args", "cpu", "smp", "memory_mib",
        "kernel", "initrd", "graphics", "network", "drives", "bootargs",
    }
    missing = sorted(required - profile.keys())
    if missing:
        fail(f"profile {path} is missing keys: {', '.join(missing)}", EXIT_CLI)
    if profile["schema_version"] != 1:
        fail(f"unsupported profile schema: {profile['schema_version']}", EXIT_CLI)
    if not re.fullmatch(r"[a-z0-9_]+", str(profile["id"])):
        fail("profile id must contain lowercase letters, digits, and underscores", EXIT_CLI)
    _validate_profile_drives(profile)
    profile["_path"] = str(path)
    return profile


def _validate_profile_drives(profile: Dict[str, Any]) -> None:
    drives = profile["drives"]
    if not isinstance(drives, list) or not drives:
        fail("profile must declare at least one drive", EXIT_CLI)
    seen = set()
    required_keys = ("id", "file", "base_format", "drive_options", "device", "device_options")
    for drive in drives:
        for key in required_keys:
            if key not in drive:
                fail(f"drive entry is missing '{key}'", EXIT_CLI)
        if drive["id"] in seen or not re.fullmatch(r"[a-z0-9_]+", drive["id"]):
            fail(f"invalid or duplicate drive id: {drive['id']}", EXIT_CLI)
        seen.add(drive["id"])


def required_image_names(profile: Dict[str, Any]) -> List[str]:
    return [profile["kernel"], profile["initrd"]] + [drive["file"] for drive in profile["drives"]]


def directory_matches(path: Path, profile: Dict[str, Any]) -> bool:
    return path.is_dir() and all((path / name).is_file() for name in required_image_names(profile))


# --- Archive extraction -------------------------------------------------------

def validate_archive_member(name: str) -> Path:
    if "\\" in name:
        fail(f"archive member uses a backslash path: {name}", EXIT_IMAGE)
    posix = PurePosixPath(name)
    windows = PureWindowsPath(name)
    if posix.is_absolute() or windows.is_absolute() or windows.drive or ".." in posix.parts:
        fail(f"unsafe archive member path: {name}", EXIT_IMAGE)
    return Path(*posix.parts)


def extract_archive(archive: Path) -> Path:
    archive = canonical(archive)
    digest = hashlib.sha256()
    with archive.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    key = digest.hexdigest()[:20]
    root = cache_root()
    target = root / key
    if (target / ".ready").is_file():
        return target
    root.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f".{key}.", dir=str(root)))
    try:
        _extract_archive_into(archive, staging)
        (staging / ".ready").write_text(f"source={archive}\n", encoding="utf-8")
        if target.exists():
            shutil.rmtree(staging)
        else:
            os.replace(staging, target)
        return target
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise


def _extract_archive_into(archive: Path, staging: Path) -> None:
    if zipfile.is_zipfile(archive):
        with zipfile.ZipFile(archive) as package:
            _extract_zip_archive(package, staging)
    elif tarfile.is_tarfile(archive):
        with tarfile.open(archive) as package:
            _extract_tar_archive(package, staging)
    else:
        fail(f"unsupported image archive: {archive}", EXIT_IMAGE)


def _enforce_archive_limits(count: int, total: int) -> None:
    if count > MAX_ARCHIVE_FILES or total > MAX_ARCHIVE_BYTES:
        fail("image archive exceeds extraction limits", EXIT_IMAGE)


def _extract_zip_archive(package: "zipfile.ZipFile", staging: Path) -> None:
    count = 0
    total = 0
    for info in package.infolist():
        count += 1
        total += info.file_size
        _enforce_archive_limits(count, total)
        relative = validate_archive_member(info.filename)
        mode = (info.external_attr >> 16) & 0xFFFF
        if stat.S_ISLNK(mode):
            fail(f"archive symlink is not allowed: {info.filename}", EXIT_IMAGE)
        destination = staging / relative
        if info.is_dir():
            destination.mkdir(parents=True, exist_ok=True)
        else:
            destination.parent.mkdir(parents=True, exist_ok=True)
            with package.open(info) as source, destination.open("wb") as output:
                shutil.copyfileobj(source, output)


def _extract_tar_archive(package: "tarfile.TarFile", staging: Path) -> None:
    count = 0
    total = 0
    for info in package:
        count += 1
        total += max(0, info.size)
        _enforce_archive_limits(count, total)
        relative = validate_archive_member(info.name)
        if not (info.isdir() or info.isfile()):
            fail(f"archive member type is not allowed: {info.name}", EXIT_IMAGE)
        destination = staging / relative
        if info.isdir():
            destination.mkdir(parents=True, exist_ok=True)
        else:
            destination.parent.mkdir(parents=True, exist_ok=True)
            source = package.extractfile(info)
            if source is None:
                fail(f"cannot extract archive member: {info.name}", EXIT_IMAGE)
            with source, destination.open("wb") as output:
                shutil.copyfileobj(source, output)


# --- Image directory discovery -----------------------------------------------


def cache_root() -> Path:
    system = host_os()
    if system == "windows":
        base = Path(os.environ.get("LOCALAPPDATA", tempfile.gettempdir())) / "OpenHarmony" / "QEMU" / "Cache"
    elif system == "macos":
        base = Path.home() / "Library" / "Caches" / "OpenHarmony" / "QEMU"
    else:
        base = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache")) / "openharmony-qemu"
    return base / "packages"


def resolve_image_dir(value: Optional[str], profile: Dict[str, Any], repo_root: Path) -> Tuple[Path, bool]:
    candidates: List[Tuple[Path, bool]] = []
    explicit = value or os.environ.get("OHOS_IMG")
    if explicit:
        requested = canonical(Path(explicit))
        if not requested.exists():
            fail(f"image path does not exist: {requested}", EXIT_IMAGE)
        if requested.is_file():
            requested = extract_archive(requested)
        candidates.append((requested, True))
    else:
        for item in profile["default_image_paths"]:
            candidates.append((canonical(repo_root / item), False))
        candidates.append((canonical(Path.cwd()), False))

    for root, was_explicit in candidates:
        match = _match_image_candidate(root, profile, was_explicit)
        if match is not None:
            return match
    expected = ", ".join(required_image_names(profile))
    fail(f"cannot find a complete {profile['id']} image set; required: {expected}", EXIT_IMAGE)


def _match_image_candidate(root: Path, profile: Dict[str, Any], was_explicit: bool) -> Optional[Tuple[Path, bool]]:
    if directory_matches(root, profile):
        return root, was_explicit
    if directory_matches(root / "images", profile):
        return canonical(root / "images"), was_explicit
    if was_explicit and root.is_dir():
        return _resolve_explicit_image_dir(root, profile)
    return None


def _resolve_explicit_image_dir(root: Path, profile: Dict[str, Any]) -> Optional[Tuple[Path, bool]]:
    matches: List[Path] = []
    for current, dirs, _files in os.walk(root):
        current_path = Path(current)
        if len(current_path.relative_to(root).parts) > 3:
            dirs[:] = []
            continue
        if directory_matches(current_path, profile):
            matches.append(canonical(current_path))
            dirs[:] = []
    if len(matches) == 1:
        return matches[0], True
    if len(matches) > 1:
        fail("image path is ambiguous:\n  " + "\n  ".join(str(item) for item in matches), EXIT_IMAGE)
    return None


# --- Executable discovery and QEMU capabilities ------------------------------


def find_executable(names: Iterable[str], explicit: Optional[str], directory: Optional[str]) -> str:
    if explicit:
        path = canonical(Path(explicit))
        if path.is_file():
            return str(path)
        fail(f"executable does not exist: {path}", EXIT_QEMU)
    suffixes = [".exe", ""] if host_os() == "windows" else [""]
    for name in names:
        for suffix in suffixes:
            candidate_name = name if name.lower().endswith(suffix) else name + suffix
            resolved = _resolve_executable(candidate_name, directory)
            if resolved:
                return resolved
    fail(f"cannot find executable; tried: {', '.join(names)}", EXIT_QEMU)


def _resolve_executable(name: str, directory: Optional[str]) -> Optional[str]:
    if directory:
        candidate = canonical(Path(directory) / name)
        if candidate.is_file():
            return str(candidate)
    found = shutil.which(name)
    return str(canonical(Path(found))) if found else None


def qemu_capabilities(qemu: str, profile: Dict[str, Any]) -> Dict[str, Any]:
    version_output = run_checked([qemu, "--version"], code=EXIT_QEMU).stdout.splitlines()[0]
    version = parse_version(version_output)
    minimum = parse_version(profile.get("minimum_qemu_version", "0"))
    if version < minimum:
        fail(f"QEMU {version_output} is older than required {profile['minimum_qemu_version']}", EXIT_QEMU)
    accel_result = run_checked([qemu, "-accel", "help"], code=EXIT_QEMU)
    display_result = run_checked([qemu, "-display", "help"], code=EXIT_QEMU)
    accel_text = (accel_result.stdout or "") + "\n" + (accel_result.stderr or "")
    display_text = (display_result.stdout or "") + "\n" + (display_result.stderr or "")
    accelerators = {line.strip().split()[0] for line in accel_text.splitlines() if line.strip() and "supported" not in line.lower()}
    displays = {line.strip().split()[0] for line in display_text.splitlines() if line.strip() and "available" not in line.lower() and not line.startswith("qemu:")}
    return {"version": version_output, "accelerators": accelerators, "displays": displays}


def machine_value(profile: Dict[str, Any]) -> str:
    args = profile["machine_args"]
    if len(args) < 2:
        fail("profile machine_args must contain option and value", EXIT_CLI)
    return args[1]


# --- Accelerator and display selection ---------------------------------------


def probe_accelerator(qemu: str, profile: Dict[str, Any], accelerator: str) -> Tuple[bool, str]:
    accel_arg = accelerator if accelerator != "tcg" else "tcg,thread=multi"
    argv = [
        qemu, "-machine", machine_value(profile), "-cpu", profile["cpu"],
        "-accel", accel_arg, "-S", "-nodefaults", "-display", "none",
    ]
    try:
        process = subprocess.Popen(argv, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
    except OSError as error:
        return False, str(error)
    try:
        return_code = process.wait(timeout=0.5)
        stderr = (process.stderr.read() if process.stderr else "").strip()
        return False, stderr or f"probe exited with {return_code}"
    except subprocess.TimeoutExpired:
        _terminate_probe_process(process)
        return True, "probe initialized successfully"


def _terminate_probe_process(process: subprocess.Popen) -> None:
    process.terminate()
    try:
        process.wait(timeout=2)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()


def select_accelerator(requested: str, qemu: str, profile: Dict[str, Any], capabilities: Dict[str, Any]) -> Tuple[str, List[str]]:
    system = host_os()
    host_arch = normalize_arch(platform.machine())
    guest_arch = normalize_arch(profile["guest_arch"])
    compatible = host_arch == guest_arch or (host_arch == "aarch64" and guest_arch == "arm")
    preferred = {"linux": "kvm", "macos": "hvf", "windows": "whpx"}.get(system)
    if requested != "auto":
        candidates = [requested]
    else:
        candidates = ([preferred] if preferred and compatible else []) + ["tcg"]
    reasons: List[str] = []
    for candidate in candidates:
        ok, reason = _probe_accelerator_candidate(candidate, qemu, profile, capabilities, system)
        reasons.append(reason)
        if ok:
            return candidate, reasons
    fail("no usable accelerator; " + "; ".join(reasons), EXIT_PLATFORM)


def _probe_accelerator_candidate(
    candidate: str, qemu: str, profile: Dict[str, Any], capabilities: Dict[str, Any], system: str,
) -> Tuple[bool, str]:
    if candidate not in capabilities["accelerators"]:
        return False, f"{candidate}: not compiled in QEMU"
    if candidate == "kvm" and system == "linux" and not os.access("/dev/kvm", os.R_OK | os.W_OK):
        return False, "kvm: /dev/kvm is not readable and writable"
    ok, reason = probe_accelerator(qemu, profile, candidate)
    return ok, f"{candidate}: {reason}"


def has_desktop_session(system: str) -> bool:
    if system == "linux":
        return bool(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))
    if system == "macos":
        return not bool(os.environ.get("SSH_CONNECTION"))
    if system == "windows":
        return os.environ.get("SESSIONNAME", "").lower() != "services"
    return False


def select_display(requested: str, profile: Dict[str, Any], capabilities: Dict[str, Any]) -> str:
    if not profile["graphics"].get("supported", False):
        if requested not in {"auto", "none"}:
            fail(f"profile {profile['id']} does not provide a graphics device", EXIT_PLATFORM)
        return "none"
    available = capabilities["displays"]
    if requested != "auto":
        if requested == "vnc" or requested in available:
            return requested
        fail(f"display backend '{requested}' is not available; QEMU provides: {', '.join(sorted(available))}", EXIT_PLATFORM)
    system = host_os()
    if has_desktop_session(system):
        order = {
            "linux": ["gtk", "sdl", "vnc", "none"],
            "macos": ["cocoa", "sdl", "gtk", "vnc", "none"],
            "windows": ["sdl", "gtk", "vnc", "none"],
        }.get(system, ["vnc", "none"])
    else:
        order = ["vnc", "none"]
    for candidate in order:
        if candidate == "vnc" or candidate in available:
            return candidate
    return "none"


# --- File locking ------------------------------------------------------------


class FileLock:
    def __init__(self, path: Path):
        self.path = path
        self.stream = None

    def __enter__(self) -> "FileLock":
        self.acquire()
        return self

    def __exit__(self, _type: Any, _value: Any, _traceback: Any) -> None:
        self.release()

    def acquire(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.stream = self.path.open("a+b")
        self.stream.seek(0)
        if self.stream.read(1) == b"":
            self.stream.seek(0)
            self.stream.write(b"0")
            self.stream.flush()
        self.stream.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(self.stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as error:
            self.stream.close()
            self.stream = None
            if error.errno in {errno.EACCES, errno.EAGAIN, errno.EDEADLK, 13, 36}:
                fail(f"instance is busy (lock: {self.path})", EXIT_BUSY)
            raise

    def release(self) -> None:
        if self.stream is None:
            return
        try:
            if os.name == "nt":
                import msvcrt
                self.stream.seek(0)
                msvcrt.locking(self.stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.stream.fileno(), fcntl.LOCK_UN)
        finally:
            self.stream.close()
            self.stream = None


# --- Instance lifecycle and validation ---------------------------------------


def image_signature(path: Path) -> Dict[str, Any]:
    details = path.stat()
    return {
        "path": str(canonical(path)),
        "size": details.st_size,
        "mtime_ns": details.st_mtime_ns,
        "device": details.st_dev,
        "inode": details.st_ino,
    }


def qemu_img_info(qemu_img: str, path: Path, code: int = EXIT_IMAGE) -> Dict[str, Any]:
    output = run_checked([qemu_img, "info", "--output=json", str(path)], code=code).stdout
    try:
        return json.loads(output)
    except json.JSONDecodeError as error:
        fail(f"qemu-img returned invalid JSON for {path}: {error}", code)


def uses_lazy_refcounts(info: Dict[str, Any]) -> bool:
    return bool(info.get("format-specific", {}).get("data", {}).get("lazy-refcounts", False))


def validate_base_images(profile: Dict[str, Any], image_dir: Path, qemu_img: str) -> None:
    for name in (profile["kernel"], profile["initrd"]):
        path = image_dir / name
        if not path.is_file():
            fail(f"missing image file: {path}", EXIT_IMAGE)
    for drive in profile["drives"]:
        path = image_dir / drive["file"]
        if not path.is_file():
            fail(f"missing base image: {path}", EXIT_IMAGE)
        info = qemu_img_info(qemu_img, path)
        if info.get("format") != drive["base_format"]:
            fail(f"base image {path} has format {info.get('format')}, expected {drive['base_format']}", EXIT_IMAGE)


def manifest_data(profile: Dict[str, Any], instance_id: str, image_dir: Path) -> Dict[str, Any]:
    return {
        "format_version": FORMAT_VERSION,
        "profile_id": profile["id"],
        "instance_id": instance_id,
        "image_root": str(image_dir),
        "created_at": utc_now(),
        "base_images": {
            drive["id"]: dict(image_signature(image_dir / drive["file"]), format=drive["base_format"])
            for drive in profile["drives"]
        },
    }


def legacy_signature(path: Path) -> Optional[str]:
    if os.name == "nt" or not shutil.which("stat"):
        return None
    result = subprocess.run(["stat", "-Lc", "%d:%i:%s:%y", str(path)], capture_output=True, text=True, check=False)
    return result.stdout.strip() if result.returncode == 0 else None


def migrate_v1_manifest(instance_dir: Path, profile: Dict[str, Any], instance_id: str, image_dir: Path) -> bool:
    old = instance_dir / "manifest.env"
    if not old.is_file():
        return False
    values: Dict[str, str] = {}
    for line in old.read_text(encoding="utf-8").splitlines():
        if "=" in line:
            key, value = line.split("=", 1)
            values[key] = value
    if values.get("FORMAT_VERSION") != "1" or values.get("INSTANCE_ID") != instance_id:
        fail(f"unsupported legacy manifest: {old}", EXIT_INSTANCE)
    if canonical(Path(values.get("BASE_DIR", ""))) != image_dir:
        fail("legacy instance references a different base directory; reset is required", EXIT_INSTANCE)
    for drive in profile["drives"]:
        expected = values.get(f"{drive['id'].upper()}_SIG")
        actual = legacy_signature(image_dir / drive["file"])
        if actual is None or expected != actual:
            fail(f"base image changed for legacy instance: {drive['file']}; reset is required", EXIT_INSTANCE)
    atomic_write_json(instance_dir / "manifest.json", manifest_data(profile, instance_id, image_dir))
    return True


def validate_instance(instance_dir: Path, profile: Dict[str, Any], instance_id: str, image_dir: Path, qemu_img: str) -> None:
    manifest_path = instance_dir / "manifest.json"
    if not manifest_path.is_file():
        migrate_v1_manifest(instance_dir, profile, instance_id, image_dir)
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        fail(f"cannot read instance manifest {manifest_path}: {error}; reset is required", EXIT_INSTANCE)
    if manifest.get("format_version") != FORMAT_VERSION or manifest.get("profile_id") != profile["id"]:
        fail("instance manifest version/profile mismatch; reset is required", EXIT_INSTANCE)
    if manifest.get("instance_id") != instance_id or canonical(Path(manifest.get("image_root", ""))) != image_dir:
        fail("instance ID or image root mismatch; reset is required", EXIT_INSTANCE)
    for drive in profile["drives"]:
        _validate_instance_drive(instance_dir, image_dir, qemu_img, drive, manifest)


def _validate_instance_drive(
    instance_dir: Path, image_dir: Path, qemu_img: str,
    drive: Dict[str, Any], manifest: Dict[str, Any],
) -> None:
    expected = manifest.get("base_images", {}).get(drive["id"])
    actual = dict(image_signature(image_dir / drive["file"]), format=drive["base_format"])
    if expected != actual:
        fail(f"base image changed: {drive['file']}; reset is required", EXIT_INSTANCE)
    overlay = instance_dir / f"{drive['id']}.qcow2"
    if not overlay.is_file():
        fail(f"missing overlay: {overlay}; reset is required", EXIT_INSTANCE)
    info = qemu_img_info(qemu_img, overlay, EXIT_INSTANCE)
    if info.get("format") != "qcow2":
        fail(f"overlay is not qcow2: {overlay}", EXIT_INSTANCE)
    full_backing = info.get("full-backing-filename") or info.get("backing-filename")
    if canonical(Path(full_backing or "")) != canonical(image_dir / drive["file"]):
        fail(f"unexpected backing file for {overlay}; reset is required", EXIT_INSTANCE)
    run_checked([qemu_img, "check", "-q", "-f", "qcow2", str(overlay)], code=EXIT_INSTANCE)
    _disable_lazy_refcounts(qemu_img, overlay, info)


def _disable_lazy_refcounts(qemu_img: str, overlay: Path, info: Dict[str, Any]) -> None:
    if not uses_lazy_refcounts(info):
        return
    run_checked([
        qemu_img, "amend", "-q", "-f", "qcow2", "-o", "lazy_refcounts=off", str(overlay),
    ], code=EXIT_INSTANCE)
    updated = qemu_img_info(qemu_img, overlay, EXIT_INSTANCE)
    if uses_lazy_refcounts(updated):
        fail(f"cannot disable lazy refcounts for {overlay}", EXIT_INSTANCE)
    run_checked([qemu_img, "check", "-q", "-f", "qcow2", str(overlay)], code=EXIT_INSTANCE)
    print(f"Migrated overlay to lazy_refcounts=off: {overlay}")


def create_staging(instance_root: Path, profile: Dict[str, Any], instance_id: str, image_dir: Path, qemu_img: str) -> Path:
    instance_root.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f".{instance_id}.create.", dir=str(instance_root)))
    try:
        for drive in profile["drives"]:
            base = canonical(image_dir / drive["file"])
            overlay = staging / f"{drive['id']}.qcow2"
            run_checked([
                qemu_img, "create", "-q", "-f", "qcow2", "-F", drive["base_format"],
                "-b", str(base), "-o", QCOW2_CREATE_OPTIONS, str(overlay),
            ], code=EXIT_INSTANCE)
            os.chmod(overlay, 0o600)
        atomic_write_json(staging / "manifest.json", manifest_data(profile, instance_id, image_dir))
        validate_instance(staging, profile, instance_id, image_dir, qemu_img)
        return staging
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise


def ensure_instance(instance_root: Path, profile: Dict[str, Any], instance_id: str, image_dir: Path, qemu_img: str, reset: bool) -> Path:
    instance_dir = instance_root / instance_id
    if reset:
        staging = create_staging(instance_root, profile, instance_id, image_dir, qemu_img)
        _install_staging_instance(instance_root, instance_id, staging)
        print(f"Reset instance {instance_id}: {instance_dir}")
    elif not instance_dir.exists():
        staging = create_staging(instance_root, profile, instance_id, image_dir, qemu_img)
        os.replace(staging, instance_dir)
        print(f"Created instance {instance_id}: {instance_dir}")
    else:
        validate_instance(instance_dir, profile, instance_id, image_dir, qemu_img)
    return instance_dir


def _install_staging_instance(instance_root: Path, instance_id: str, staging: Path) -> None:
    instance_dir = instance_root / instance_id
    backup = instance_root / f".{instance_id}.backup.{os.getpid()}"
    try:
        if instance_dir.exists():
            os.replace(instance_dir, backup)
        os.replace(staging, instance_dir)
    except Exception:
        if backup.exists() and not instance_dir.exists():
            os.replace(backup, instance_dir)
        shutil.rmtree(staging, ignore_errors=True)
        raise
    shutil.rmtree(backup, ignore_errors=True)


# --- State roots and derived resources ---------------------------------------


def default_state_root(profile: Dict[str, Any], repo_root: Path, image_dir: Path, _explicit_images: bool) -> Path:
    defaults = [canonical(repo_root / path) for path in profile["default_image_paths"]]
    if image_dir in defaults:
        return canonical(repo_root / profile["default_instance_root"])
    image_key = hashlib.sha256(str(image_dir).encode("utf-8")).hexdigest()[:16]
    system = host_os()
    if system == "windows":
        base = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "OpenHarmony" / "QEMU" / "State"
    elif system == "macos":
        base = Path.home() / "Library" / "Application Support" / "OpenHarmony" / "QEMU"
    else:
        base = Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local" / "state")) / "openharmony-qemu"
    return canonical(base / "instances" / profile["id"] / image_key)


def runtime_root(profile: Dict[str, Any], instance_root: Path, explicit: Optional[str]) -> Path:
    if explicit:
        return canonical(Path(explicit))
    user = str(os.getuid()) if hasattr(os, "getuid") else os.environ.get("USERNAME", "user")
    key = hashlib.sha256(str(instance_root).encode("utf-8")).hexdigest()[:12]
    return canonical(Path(tempfile.gettempdir()) / f"ohos-qemu-{user}" / key / profile["id"])


def derive_resources(profile: Dict[str, Any], instance_id: str) -> Dict[str, Any]:
    number = int(instance_id, 10)
    offset = int(profile["port_slot"]) * 100
    hdc = 5555 + offset + number
    vnc_display = 21 + offset + number
    gdb = 1234 + offset + number
    sn = f"{instance_id}23456789"
    mac = f"52:54:{int(profile['port_slot']):02x}:58:00:{number:02x}"
    for label, value in (("HDC", hdc), ("GDB", gdb), ("VNC TCP", 5900 + vnc_display)):
        if not 1 <= value <= 65535:
            fail(f"{label} port is outside 1..65535: {value}", EXIT_CLI)
    if not re.fullmatch(r"([0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}", mac):
        fail(f"invalid MAC address: {mac}", EXIT_CLI)
    if not re.fullmatch(r"[A-Za-z0-9_.-]{1,64}", sn):
        fail(f"invalid serial number: {sn}", EXIT_CLI)
    return {"number": number, "hdc_port": hdc, "vnc_display": vnc_display, "gdb_port": gdb, "sn": sn, "mac": mac}


def port_available(port: int) -> bool:
    with contextlib.closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as probe:
        probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            probe.bind(("127.0.0.1", port))
            return True
        except OSError:
            return False


def qmp_endpoint(run_dir: Path, profile: Dict[str, Any], resources: Dict[str, Any]) -> Dict[str, Any]:
    if host_os() == "windows":
        return {"type": "tcp", "host": "127.0.0.1", "port": 45000 + int(profile["port_slot"]) * 100 + resources["number"]}
    path = run_dir / "qmp.sock"
    length = len(os.fsencode(path))
    if length >= 108:
        fail(f"QMP socket path is {length} bytes (must be less than 108); use --runtime-root", EXIT_PLATFORM)
    return {"type": "unix", "path": str(path)}


def process_alive(pid: Any) -> bool:
    try:
        value = int(pid)
        if value <= 0:
            return False
        os.kill(value, 0)
        return True
    except (ValueError, TypeError, OSError):
        return False


def read_runtime(run_dir: Path) -> Dict[str, Any]:
    path = run_dir / "runtime.json"
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


# --- QMP communication --------------------------------------------------------


def qmp_connect(endpoint: Dict[str, Any], timeout: float = 1.0) -> socket.socket:
    if endpoint.get("type") == "unix":
        client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        address: Any = endpoint["path"]
    else:
        client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        address = (endpoint["host"], int(endpoint["port"]))
    client.settimeout(timeout)
    client.connect(address)
    return client


def qmp_is_ready(endpoint: Dict[str, Any]) -> bool:
    try:
        with qmp_connect(endpoint) as client:
            stream = client.makefile("rb")
            greeting = json.loads(stream.readline().decode("utf-8"))
            return "QMP" in greeting
    except (OSError, ValueError):
        return False


def qmp_read_response(stream: Any) -> Dict[str, Any]:
    while True:
        line = stream.readline()
        if not line:
            fail("QMP connection closed before a response was received", EXIT_BUSY)
        try:
            message = json.loads(line.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            continue
        if "return" in message or "error" in message:
            return message


def qmp_command(endpoint: Dict[str, Any], command: str) -> None:
    try:
        with qmp_connect(endpoint, 2.0) as client:
            stream = client.makefile("rwb", buffering=0)
            greeting = json.loads(stream.readline().decode("utf-8"))
            if "QMP" not in greeting:
                fail("invalid QMP greeting", EXIT_BUSY)
            stream.write(b'{"execute":"qmp_capabilities"}\r\n')
            capability_response = qmp_read_response(stream)
            if "error" in capability_response:
                fail(f"QMP capabilities failed: {capability_response['error']}", EXIT_BUSY)
            stream.write(json.dumps({"execute": command}).encode("utf-8") + b"\r\n")
            response = qmp_read_response(stream)
            if "error" in response:
                fail(f"QMP command '{command}' failed: {response['error']}", EXIT_BUSY)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        fail(f"cannot send QMP command '{command}': {error}", EXIT_BUSY)


# --- Instance state inspection -----------------------------------------------


def instance_state(instance_dir: Path, run_dir: Path) -> Tuple[str, Dict[str, Any]]:
    if not instance_dir.is_dir():
        return "ABSENT", {}
    runtime = read_runtime(run_dir)
    endpoint = runtime.get("qmp", {})
    if runtime and process_alive(runtime.get("qemu_pid")) and endpoint and qmp_is_ready(endpoint):
        return "RUNNING", runtime
    if (instance_dir / "manifest.json").is_file() or (instance_dir / "manifest.env").is_file():
        return "READY", runtime
    return "INVALID", runtime


def lock_is_busy(path: Path) -> bool:
    """Probe an existing instance lock without creating state for read-only commands."""
    if not path.is_file():
        return False
    try:
        lock = FileLock(path)
        lock.acquire()
        lock.release()
        return False
    except LauncherError as error:
        if error.code == EXIT_BUSY:
            return True
        raise


# --- QEMU command building ---------------------------------------------------


def render_bootargs(profile: Dict[str, Any], resources: Dict[str, Any]) -> str:
    replacements = {"${INSTANCE_SN}": resources["sn"]}
    values = []
    for raw in profile["bootargs"]:
        value = str(raw)
        for key, replacement in replacements.items():
            value = value.replace(key, replacement)
        if "${" in value:
            fail(f"unresolved bootarg placeholder: {value}", EXIT_CLI)
        values.append(value)
    return " ".join(values)


def _display_args(display: str, profile: Dict[str, Any], resources: Dict[str, Any]) -> List[str]:
    device_args = list(profile["graphics"].get("device_args", []))
    if display == "vnc":
        return device_args + ["-vnc", f"127.0.0.1:{resources['vnc_display']}"]
    if display in {"gtk", "sdl"}:
        return device_args + ["-display", f"{display},gl=off"]
    if display == "cocoa":
        return device_args + ["-display", "cocoa"]
    return ["-display", "none"]


def _serial_args(args: argparse.Namespace, run_dir: Path) -> List[str]:
    if args.background or args.supervise:
        return ["-chardev", f"file,id=serial0,path={run_dir / 'serial.log'}", "-serial", "chardev:serial0"]
    return ["-serial", "mon:stdio"]


def _network_args(args: argparse.Namespace, network: str, profile: Dict[str, Any], resources: Dict[str, Any]) -> List[str]:
    if network == "user":
        return [
            "-netdev", f"user,id=net0,hostfwd=tcp:127.0.0.1:{resources['hdc_port']}-:5555",
            "-device", f"{profile['network']['device']},netdev=net0,mac={resources['mac']}",
        ]
    if network == "bridge":
        if host_os() != "linux":
            fail("bridge networking is supported only on Linux", EXIT_PLATFORM)
        return [
            "-netdev", f"bridge,id=net0,br={args.bridge}",
            "-device", f"{profile['network']['device']},netdev=net0,mac={resources['mac']}",
        ]
    return []


def _drive_args(profile: Dict[str, Any], instance_dir: Path, args: argparse.Namespace) -> List[str]:
    argv: List[str] = []
    for drive in profile["drives"]:
        overlay = instance_dir / f"{drive['id']}.qcow2"
        options = list(drive["drive_options"]) + [f"file={overlay}", "format=qcow2", f"cache={args.disk_cache}"]
        argv += ["-drive", ",".join(options)]
        argv += ["-device", ",".join([drive["device"]] + list(drive["device_options"]))]
    return argv


def _qmp_args(endpoint: Dict[str, Any]) -> List[str]:
    if endpoint["type"] == "unix":
        return ["-qmp", f"unix:{endpoint['path']},server=on,wait=off"]
    return ["-qmp", f"tcp:{endpoint['host']}:{endpoint['port']},server=on,wait=off"]


def build_command(
    qemu: str,
    profile: Dict[str, Any],
    image_dir: Path,
    instance_dir: Path,
    run_dir: Path,
    accelerator: str,
    display: str,
    network: str,
    resources: Dict[str, Any],
    endpoint: Dict[str, Any],
    args: argparse.Namespace,
) -> List[str]:
    argv = [qemu]
    argv += list(profile["machine_args"])
    argv += ["-accel", accelerator if accelerator != "tcg" else "tcg,thread=multi"]
    argv += ["-cpu", str(profile["cpu"]), "-smp", str(profile["smp"]), "-m", str(profile["memory_mib"])]
    argv += ["-kernel", str(image_dir / profile["kernel"]), "-initrd", str(image_dir / profile["initrd"])]
    argv += list(profile.get("common_args", []))
    argv += _display_args(display, profile, resources)
    argv += list(profile.get("input_args", []))
    argv += _serial_args(args, run_dir)
    argv += _network_args(args, network, profile, resources)
    argv += _drive_args(profile, instance_dir, args)
    argv += _qmp_args(endpoint)
    argv += ["-pidfile", str(run_dir / "qemu.pid"), "-name", f"ohos-{profile['id']}-{args.instance}"]
    if args.gdb_wait:
        argv += ["-gdb", f"tcp:127.0.0.1:{resources['gdb_port']}", "-S"]
    argv += ["-append", render_bootargs(profile, resources)]
    argv += list(args.qemu_arg)
    return argv


def print_summary(
    profile: Dict[str, Any], image_dir: Path, instance_dir: Path, run_dir: Path,
    accelerator: str, display: str, network: str, resources: Dict[str, Any], qemu: str, version: str,
) -> None:
    print(f"Profile:    {profile['id']} ({profile['guest_arch']})")
    print(f"Host:       {host_os()} / {normalize_arch(platform.machine())}")
    print(f"QEMU:       {qemu} ({version})")
    print(f"Accel:      {accelerator}")
    print(f"Display:    {display}")
    print(f"Network:    {network}")
    print(f"Images:     {image_dir}")
    print(f"Instance:   {instance_dir}")
    print(f"Runtime:    {run_dir}")
    print(f"SN/MAC:     {resources['sn']} / {resources['mac']}")
    if network != "none":
        print(f"HDC:        127.0.0.1:{resources['hdc_port']}")
    if display == "vnc":
        print(f"VNC:        127.0.0.1:{5900 + resources['vnc_display']} (display :{resources['vnc_display']})")


# --- Process spawning --------------------------------------------------------


def spawn_qemu(argv: List[str], run_dir: Path, endpoint: Dict[str, Any], metadata: Dict[str, Any], background: bool) -> int:
    run_dir.mkdir(parents=True, exist_ok=True)
    if endpoint.get("type") == "unix":
        with contextlib.suppress(FileNotFoundError):
            Path(endpoint["path"]).unlink()
    with contextlib.suppress(FileNotFoundError):
        (run_dir / "qemu.pid").unlink()
    stdout: Any = None
    stderr: Any = None
    log_stream = None
    if background:
        log_stream = (run_dir / "qemu.log").open("ab")
        stdout = log_stream
        stderr = subprocess.STDOUT
    try:
        process = subprocess.Popen(argv, stdin=subprocess.DEVNULL if background else None, stdout=stdout, stderr=stderr)
    except OSError as error:
        if log_stream:
            log_stream.close()
        fail(f"cannot start QEMU: {error}", EXIT_START)
    metadata.update({"qemu_pid": process.pid, "started_at": utc_now(), "qmp": endpoint, "command": argv})
    atomic_write_json(run_dir / "runtime.json", metadata)
    try:
        return process.wait()
    except KeyboardInterrupt:
        return _terminate_qemu(process)
    finally:
        if log_stream:
            log_stream.close()
        metadata.update({"exited_at": utc_now(), "exit_code": process.returncode})
        atomic_write_json(run_dir / "runtime.json", metadata)


def _terminate_qemu(process: subprocess.Popen) -> int:
    with contextlib.suppress(ProcessLookupError):
        process.send_signal(signal.SIGINT)
    try:
        return process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.terminate()
        return process.wait(timeout=5)


def launch_background(argv: List[str], run_dir: Path) -> None:
    child_args = [item for item in argv if item != "--background"] + ["--supervise"]
    run_dir.mkdir(parents=True, exist_ok=True)
    supervisor_log = (run_dir / "supervisor.log").open("ab")
    kwargs: Dict[str, Any] = {"stdin": subprocess.DEVNULL, "stdout": supervisor_log, "stderr": subprocess.STDOUT}
    if os.name == "nt":
        kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS
    else:
        kwargs["start_new_session"] = True
    process = subprocess.Popen([sys.executable, str(Path(__file__).resolve().parents[1] / "qemu_launcher.py")] + child_args, **kwargs)
    supervisor_log.close()
    deadline = time.monotonic() + 8
    while time.monotonic() < deadline:
        if process.poll() is not None:
            fail(f"background supervisor exited with {process.returncode}; see {run_dir / 'supervisor.log'}", EXIT_START)
        runtime = read_runtime(run_dir)
        if runtime.get("qemu_pid") and qmp_is_ready(runtime.get("qmp", {})):
            print(f"Background supervisor PID: {process.pid}")
            print(f"QEMU PID: {runtime['qemu_pid']}")
            print(f"Log: {run_dir / 'qemu.log'}")
            return
        time.sleep(0.1)
    fail(f"background QEMU did not become ready; see {run_dir / 'supervisor.log'}", EXIT_START)


# --- Command dispatch --------------------------------------------------------


def json_or_text(args: argparse.Namespace, value: Dict[str, Any], text: Sequence[str]) -> None:
    if args.json:
        print(json.dumps(value, indent=2, sort_keys=True))
    else:
        print("\n".join(text))


def determine_command(args: argparse.Namespace) -> str:
    compatibility = [("list_compat", "list"), ("status_compat", "status"), ("delete_compat", "delete")]
    selected = [command for attr, command in compatibility if getattr(args, attr)]
    if len(selected) > 1:
        fail("only one of --list, --status, and --delete may be used", EXIT_CLI)
    if selected:
        return selected[0]
    if args.create_only:
        return "reset" if args.reset_before_run else "create"
    return args.command or "run"


def _build_context(args: argparse.Namespace, original_argv: List[str]) -> types.SimpleNamespace:
    if not re.fullmatch(r"[0-9]{2}", args.instance):
        fail("instance ID must contain exactly two digits (00..99)", EXIT_CLI)
    repo_root = repo_root_from_launcher()
    profile = load_profile(Path(args.profile))
    command = determine_command(args)
    display_request = args.display or os.environ.get("QEMU_DISPLAY", "auto")
    image_dir, explicit_images = resolve_image_dir(args.images, profile, repo_root)
    instance_root = canonical(Path(args.instance_root)) if args.instance_root else default_state_root(profile, repo_root, image_dir, explicit_images)
    if path_is_within(instance_root, image_dir) or path_is_within(image_dir, instance_root):
        fail("image directory and instance root cannot contain one another", EXIT_CLI)
    run_root = runtime_root(profile, instance_root, args.runtime_root or os.environ.get("QEMU_RUNTIME_ROOT"))
    instance_dir = instance_root / args.instance
    run_dir = run_root / args.instance
    resources = derive_resources(profile, args.instance)
    lock_path = instance_root / ".locks" / f"{args.instance}.lock"
    return types.SimpleNamespace(
        args=args,
        original_argv=original_argv,
        profile=profile,
        command=command,
        display_request=display_request,
        image_dir=image_dir,
        explicit_images=explicit_images,
        instance_root=instance_root,
        run_root=run_root,
        instance_dir=instance_dir,
        run_dir=run_dir,
        resources=resources,
        lock_path=lock_path,
    )


def _discover_qemu_img(args: argparse.Namespace) -> str:
    qemu_img_dir = args.qemu_dir or (str(Path(args.qemu_binary).expanduser().parent) if args.qemu_binary else None)
    return find_executable(["qemu-img"], args.qemu_img, qemu_img_dir)


def _assert_ports_available(network: str, display: str, resources: Dict[str, Any], endpoint: Dict[str, Any]) -> None:
    for port, label in ((resources["hdc_port"], "HDC"),):
        if network != "none" and not port_available(port):
            fail(f"{label} port {port} is already in use", EXIT_BUSY)
    if display == "vnc" and not port_available(5900 + resources["vnc_display"]):
        fail(f"VNC port {5900 + resources['vnc_display']} is already in use", EXIT_BUSY)
    if endpoint["type"] == "tcp" and not port_available(endpoint["port"]):
        fail(f"QMP port {endpoint['port']} is already in use", EXIT_BUSY)


def _handle_list(ctx: types.SimpleNamespace) -> int:
    entries: List[Dict[str, Any]] = []
    if ctx.instance_root.is_dir():
        for path in sorted(ctx.instance_root.iterdir()):
            if not (path.is_dir() and re.fullmatch(r"[0-9]{2}", path.name)):
                continue
            state, runtime = instance_state(path, ctx.run_root / path.name)
            if state != "RUNNING" and lock_is_busy(ctx.instance_root / ".locks" / f"{path.name}.lock"):
                state = "BUSY_LEGACY"
            entries.append({
                "instance": path.name,
                "state": state,
                "pid": runtime.get("qemu_pid") if state == "RUNNING" else None,
            })
    if ctx.args.json:
        print(json.dumps(entries, indent=2))
    elif entries:
        for entry in entries:
            print(f"{entry['instance']}  {entry['state']:<8} pid={entry['pid'] or '-'}")
    else:
        print(f"No instances under {ctx.instance_root}")
    return 0


def _handle_status(ctx: types.SimpleNamespace) -> int:
    state, runtime = instance_state(ctx.instance_dir, ctx.run_dir)
    if state != "RUNNING" and lock_is_busy(ctx.lock_path):
        state = "BUSY_LEGACY"
    active_pid = runtime.get("qemu_pid") if state == "RUNNING" else None
    result = {
        "profile": ctx.profile["id"], "instance": ctx.args.instance, "state": state,
        "instance_dir": str(ctx.instance_dir), "runtime_dir": str(ctx.run_dir),
        "qemu_pid": active_pid, "hdc_port": ctx.resources["hdc_port"],
        "vnc_port": 5900 + ctx.resources["vnc_display"], "sn": ctx.resources["sn"], "mac": ctx.resources["mac"],
    }
    json_or_text(ctx.args, result, [
        f"Instance {ctx.args.instance}: {state}", f"  profile:   {ctx.profile['id']}",
        f"  directory: {ctx.instance_dir}", f"  runtime:   {ctx.run_dir}",
        f"  pid:       {active_pid or '-'}", f"  HDC:       127.0.0.1:{ctx.resources['hdc_port']}",
        f"  VNC:       127.0.0.1:{5900 + ctx.resources['vnc_display']}",
        f"  SN:        {ctx.resources['sn']}", f"  MAC:       {ctx.resources['mac']}",
    ])
    return 0


def _handle_stop(ctx: types.SimpleNamespace) -> int:
    state, runtime = instance_state(ctx.instance_dir, ctx.run_dir)
    if state != "RUNNING":
        fail(f"instance {ctx.args.instance} is not running (state: {state})", EXIT_BUSY)
    qmp_command(runtime["qmp"], "quit" if ctx.args.force else "system_powerdown")
    deadline = time.monotonic() + (5 if ctx.args.force else 30)
    while time.monotonic() < deadline and process_alive(runtime.get("qemu_pid")):
        time.sleep(0.2)
    if process_alive(runtime.get("qemu_pid")):
        fail("guest did not stop; retry with stop --force", EXIT_BUSY)
    print(f"Stopped instance {ctx.args.instance}")
    return 0


def _handle_delete(ctx: types.SimpleNamespace) -> int:
    with FileLock(ctx.lock_path):
        if ctx.instance_dir.exists():
            if canonical(ctx.instance_dir) != canonical(ctx.instance_root / ctx.args.instance):
                fail("refusing unsafe instance path", EXIT_INSTANCE)
            shutil.rmtree(ctx.instance_dir)
        if ctx.run_dir.exists():
            shutil.rmtree(ctx.run_dir)
    print(f"Deleted instance {ctx.args.instance}: {ctx.instance_dir}")
    return 0


def _handle_create(ctx: types.SimpleNamespace) -> int:
    with FileLock(ctx.lock_path):
        state, runtime = instance_state(ctx.instance_dir, ctx.run_dir)
        if state == "RUNNING":
            fail(f"instance {ctx.args.instance} is already running with PID {runtime.get('qemu_pid')}", EXIT_BUSY)
        ensure_instance(ctx.instance_root, ctx.profile, ctx.args.instance, ctx.image_dir, ctx.qemu_img, ctx.command == "reset")
    print(f"Instance {ctx.args.instance}: READY")
    return 0


def _handle_diagnose(ctx: types.SimpleNamespace) -> int:
    command_argv = build_command(
        ctx.qemu, ctx.profile, ctx.image_dir, ctx.instance_dir, ctx.run_dir,
        ctx.accelerator, ctx.display, ctx.network, ctx.resources, ctx.endpoint, ctx.args,
    )
    print_summary(
        ctx.profile, ctx.image_dir, ctx.instance_dir, ctx.run_dir, ctx.accelerator,
        ctx.display, ctx.network, ctx.resources, ctx.qemu, ctx.capabilities["version"],
    )
    if ctx.args.verbose:
        for reason in ctx.accel_reasons:
            print(f"Accel probe: {reason}")
    if ctx.command == "diagnose":
        result = {
            "profile": ctx.profile["id"], "host_os": host_os(),
            "host_arch": normalize_arch(platform.machine()), "qemu": ctx.qemu,
            "qemu_version": ctx.capabilities["version"], "accelerator": ctx.accelerator,
            "accelerator_probes": ctx.accel_reasons, "display": ctx.display, "network": ctx.network,
            "images": str(ctx.image_dir), "instance_root": str(ctx.instance_root),
            "runtime_root": str(ctx.run_root), "command": command_argv,
        }
        if ctx.args.json:
            print(json.dumps(result, indent=2, sort_keys=True))
    else:
        print(display_command(command_argv))
    return 0


def _handle_run(ctx: types.SimpleNamespace) -> int:
    with FileLock(ctx.lock_path):
        state, runtime = instance_state(ctx.instance_dir, ctx.run_dir)
        if state == "RUNNING":
            fail(f"instance {ctx.args.instance} is already running with PID {runtime.get('qemu_pid')}", EXIT_BUSY)
        reset = ctx.command == "reset" or ctx.args.reset_before_run
        instance_dir = ensure_instance(ctx.instance_root, ctx.profile, ctx.args.instance, ctx.image_dir, ctx.qemu_img, reset)
        command_argv = build_command(
            ctx.qemu, ctx.profile, ctx.image_dir, instance_dir, ctx.run_dir,
            ctx.accelerator, ctx.display, ctx.network, ctx.resources, ctx.endpoint, ctx.args,
        )
        print_summary(
            ctx.profile, ctx.image_dir, instance_dir, ctx.run_dir, ctx.accelerator,
            ctx.display, ctx.network, ctx.resources, ctx.qemu, ctx.capabilities["version"],
        )
        if ctx.args.verbose:
            for reason in ctx.accel_reasons:
                print(f"Accel probe: {reason}")
        _assert_ports_available(ctx.network, ctx.display, ctx.resources, ctx.endpoint)
        metadata = {"profile": ctx.profile["id"], "instance": ctx.args.instance, "instance_dir": str(instance_dir)}
        if ctx.args.background and not ctx.args.supervise:
            # Release the current lock before the detached supervisor acquires it.
            pass
        else:
            return_code = spawn_qemu(command_argv, ctx.run_dir, ctx.endpoint, metadata, ctx.args.supervise)
            if return_code != 0:
                fail(f"QEMU exited with code {return_code}", EXIT_START)
            return 0
    launch_background(ctx.original_argv, ctx.run_dir)
    return 0


# --- Argument parser ---------------------------------------------------------


_USAGE_EPILOG = """Commands:
  run            Create or reuse an instance and start QEMU (default command).
  create         Create and validate the instance qcow2 overlays, then exit.
  list           List all instances belonging to this profile and image set.
  status         Show instance state, PID, identity, ports, and storage paths.
  stop           Request guest shutdown through QMP; add --force to quit QEMU.
  reset          Discard instance writes and recreate all qcow2 overlays.
  delete         Delete a stopped instance and its runtime files.
  diagnose       Probe host/QEMU capabilities and print selected defaults.
  print-command  Print the generated QEMU command without creating an instance.

Resources derived from --instance ID for x86_64:
  SN          ID23456789
  MAC         52:54:00:58:00:<ID as hexadecimal>
  HDC port    5555 + decimal ID
  VNC port    5921 + decimal ID
  GDB port    1234 + decimal ID

Examples:
  %(prog)s
  %(prog)s run --instance 03 --display vnc --background
  %(prog)s status --instance 03
  %(prog)s stop --instance 03 --force
  %(prog)s diagnose --verbose

Environment overrides:
  OHOS_IMG, QEMU_DISPLAY, QEMU_INSTANCE_ROOT, QEMU_RUNTIME_ROOT,
  QEMU_BRIDGE_NAME, QEMU_DISK_CACHE
"""


def _build_main_parser() -> argparse.ArgumentParser:
    entry_name = "qemu_run.cmd" if os.name == "nt" else "qemu_run.sh"
    return argparse.ArgumentParser(
        prog=entry_name,
        usage="%(prog)s [OPTIONS] [COMMAND]",
        description=(
            "Run and manage OpenHarmony QEMU instances. Each instance uses "
            "private qcow2 overlays while sharing the read-only base images."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=_USAGE_EPILOG,
    )


def _add_path_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--profile", required=True, help=argparse.SUPPRESS)
    parser.add_argument(
        "command", nargs="?", choices=sorted(COMMANDS), metavar="COMMAND",
        help="lifecycle command to execute; omit it to run the instance",
    )
    parser.add_argument(
        "-e", "--images", "--exec", metavar="PATH",
        help=(
            "image directory, package root, or zip/tar archive; defaults to "
            "OHOS_IMG, the profile build output, or a complete current directory"
        ),
    )
    parser.add_argument(
        "-i", "--instance", metavar="ID", default="00",
        help=(
            "two-digit instance ID from 00 to 99 (default: 00); automatically "
            "derives SN, MAC, and HDC/VNC/GDB ports"
        ),
    )
    parser.add_argument(
        "--instance-root", metavar="PATH", default=os.environ.get("QEMU_INSTANCE_ROOT"),
        help=(
            "persistent directory for manifests and qcow2 overlays; defaults to "
            "QEMU_INSTANCE_ROOT, the product output, or the host user-state directory"
        ),
    )
    parser.add_argument(
        "--runtime-root", metavar="PATH",
        help=(
            "directory for QMP, PID, and log files; defaults to QEMU_RUNTIME_ROOT "
            "or a short per-user temporary path"
        ),
    )
    parser.add_argument(
        "--qemu-dir", metavar="PATH",
        help="directory containing qemu-system-* and qemu-img; PATH is used by default",
    )
    parser.add_argument(
        "--qemu-binary", metavar="PATH",
        help="exact qemu-system executable to use instead of profile/PATH discovery",
    )
    parser.add_argument(
        "--qemu-img", metavar="PATH",
        help="exact qemu-img executable used to create and validate qcow2 overlays",
    )


def _add_resource_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--accel", choices=["auto", "kvm", "hvf", "whpx", "tcg"], default="auto",
        help=(
            "QEMU accelerator: auto probes KVM on Linux, HVF on macOS, or WHPX "
            "on Windows, then falls back to TCG (default: auto)"
        ),
    )
    parser.add_argument(
        "--display", choices=["auto", "gtk", "sdl", "cocoa", "vnc", "none"],
        help=(
            "display backend; auto selects a native desktop backend or localhost "
            "VNC when headless (default: QEMU_DISPLAY or auto)"
        ),
    )
    parser.add_argument(
        "--network", choices=["auto", "user", "bridge", "none"], default="auto",
        help=(
            "guest networking: auto/user uses unprivileged NAT with HDC forwarding; "
            "bridge is Linux-only; none disables the NIC (default: auto)"
        ),
    )
    parser.add_argument(
        "--bridge", metavar="NAME", default=os.environ.get("QEMU_BRIDGE_NAME", "virbr0"),
        help=(
            "Linux host bridge name used only with --network bridge "
            "(default: QEMU_BRIDGE_NAME or virbr0)"
        ),
    )
    parser.add_argument(
        "--disk-cache", choices=["none", "writeback", "writethrough", "directsync", "unsafe"],
        default=os.environ.get("QEMU_DISK_CACHE", "none"),
        help=(
            "QEMU cache mode applied to every qcow2 drive; unsafe risks data loss "
            "(default: QEMU_DISK_CACHE or none)"
        ),
    )


def _add_behavior_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--background", action="store_true",
        help="run QEMU under a detached supervisor and write serial/QEMU logs to the runtime directory",
    )
    parser.add_argument(
        "--gdb-wait", "-g", action="store_true",
        help="start QEMU paused with a GDB server on the port derived from --instance",
    )
    parser.add_argument(
        "--reset-before-run", "-f", action="store_true",
        help="recreate the selected instance overlays before starting; all guest writes are discarded",
    )
    parser.add_argument(
        "--force", action="store_true",
        help="with stop, send QMP quit instead of requesting an orderly guest powerdown",
    )
    parser.add_argument(
        "--json", action="store_true",
        help="emit machine-readable JSON for list, status, diagnose, and errors",
    )
    parser.add_argument(
        "--verbose", action="store_true",
        help="print accelerator probe details and additional diagnostic decisions",
    )
    parser.add_argument(
        "--qemu-arg", metavar="ARG", action="append", default=[],
        help="append one raw argument to QEMU; repeat for multiple arguments (advanced)",
    )


def _add_compat_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--create-only", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--reset", dest="reset_before_run", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--delete", dest="delete_compat", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--status", dest="status_compat", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--list", dest="list_compat", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("-n", dest="network", action="store_const", const="user", help=argparse.SUPPRESS)
    parser.add_argument("--supervise", action="store_true", help=argparse.SUPPRESS)


def build_parser() -> argparse.ArgumentParser:
    parser = _build_main_parser()
    _add_path_arguments(parser)
    _add_resource_arguments(parser)
    _add_behavior_arguments(parser)
    _add_compat_arguments(parser)
    return parser


def strip_legacy_parameter_block(argv: List[str]) -> List[str]:
    # virt/qemu_run/qemu-run historically passes 9+ positional values. The full-product
    # script ignored them, and the old min scripts only consumed their own flags.
    profile_end = 0
    for index, value in enumerate(argv):
        if value == "--profile" and index + 1 < len(argv):
            profile_end = index + 2
            break
    tail = argv[profile_end:]
    if len(tail) >= 9 and len(tail) >= 3 and tail[1] in {"yes", "no"} and tail[2] in {"yes", "no"}:
        print("Warning: legacy qemu-run positional parameter block is deprecated and ignored.", file=sys.stderr)
        return argv[:profile_end]
    return argv


def execute(args: argparse.Namespace, original_argv: List[str]) -> int:
    ctx = _build_context(args, original_argv)
    command = ctx.command
    if command == "list":
        return _handle_list(ctx)
    if command == "status":
        return _handle_status(ctx)
    if command == "stop":
        return _handle_stop(ctx)
    if command == "delete":
        return _handle_delete(ctx)

    ctx.qemu_img = _discover_qemu_img(ctx.args)
    validate_base_images(ctx.profile, ctx.image_dir, ctx.qemu_img)
    if command in {"create", "reset"}:
        return _handle_create(ctx)

    ctx.qemu = find_executable(ctx.profile["qemu_binaries"], ctx.args.qemu_binary, ctx.args.qemu_dir)
    ctx.capabilities = qemu_capabilities(ctx.qemu, ctx.profile)
    ctx.accelerator, ctx.accel_reasons = select_accelerator(ctx.args.accel, ctx.qemu, ctx.profile, ctx.capabilities)
    ctx.display = select_display(ctx.display_request, ctx.profile, ctx.capabilities)
    ctx.network = "user" if ctx.args.network == "auto" else ctx.args.network
    ctx.endpoint = qmp_endpoint(ctx.run_dir, ctx.profile, ctx.resources)
    if command in {"diagnose", "print-command"}:
        return _handle_diagnose(ctx)
    return _handle_run(ctx)


def main(argv: Optional[Sequence[str]] = None) -> None:
    original = strip_legacy_parameter_block(list(argv if argv is not None else sys.argv[1:]))
    try:
        parser = build_parser()
        args = parser.parse_args(original)
        code = execute(args, original)
    except LauncherError as error:
        if "--json" in original:
            print(json.dumps({"error": str(error), "exit_code": error.code}), file=sys.stderr)
        else:
            print(f"Error: {error}", file=sys.stderr)
        raise SystemExit(error.code)
    raise SystemExit(code)
