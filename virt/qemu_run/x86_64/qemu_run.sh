#!/usr/bin/env bash

# Copyright 2026 Institute of Software, Chinese Academy of Sciences.
# Licensed under the Apache License, Version 2.0 (the "License");

set -e
export PYTHONDONTWRITEBYTECODE=1

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
DEFAULT_ARGS=()
if [[ -f "${SCRIPT_DIR}/qemu_launcher.py" && -f "${SCRIPT_DIR}/qemu_launcher_lib/launcher.py" ]]; then
    LAUNCHER="${SCRIPT_DIR}/qemu_launcher.py"
    DEFAULT_ARGS=(--images "${SCRIPT_DIR}")
else
    LAUNCHER="${SCRIPT_DIR}/../qemu_launcher.py"
fi
PROFILE="${SCRIPT_DIR}/qemu_profile.json"

if command -v python3 >/dev/null 2>&1; then
    exec python3 "${LAUNCHER}" --profile "${PROFILE}" "${DEFAULT_ARGS[@]}" "$@"
elif command -v python >/dev/null 2>&1; then
    exec python "${LAUNCHER}" --profile "${PROFILE}" "${DEFAULT_ARGS[@]}" "$@"
else
    echo "Error: Python 3.8 or newer is required." >&2
    exit 127
fi
