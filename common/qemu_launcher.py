#!/usr/bin/env python3

# Copyright 2026 Institute of Software, Chinese Academy of Sciences.
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0

import sys


# The launcher lives in the source tree; do not leave generated __pycache__
# files behind after ordinary simulator runs.
sys.dont_write_bytecode = True

from qemu_launcher_lib import main  # noqa: E402


if __name__ == "__main__":
    main()
