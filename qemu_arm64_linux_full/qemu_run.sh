#!/usr/bin/env bash

# Copyright 2026 Institute of Software, Chinese Academy of Sciences.
# Licensed under the Apache License, Version 2.0 (the "License");

set -e

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
exec "${SCRIPT_DIR}/../virt/qemu_run/arm64/qemu_run.sh" "$@"
