# vendor_ohos

## Introduction

The repository is mainly developed by OpenHarmony community, rather than the
typical certain manufacturer, mainly including the development of QEMU products
with characteristics such as graphics, soft bus, etc.

## Software Architecture

Graphic display product samples of virt platform supporting QEMU's ARMv7-a
architecture, samples of virt platform supporting RISC-V architecture, and
samples of Cortex-M4 architecture.

code path:

```
device/qemu/                          --- device_qemu repository path
├── arm_mps2_an386                    --- Cortex-M4 architecture MPS2-AN386 platform
├── arm_virt                          --- ARMv7-a architecture virt platform
├── drivers                           --- virt drivers
└── riscv32_virt                      --- RISC-V architecture virt platform
vendor/ohos/                          --- vendor_ohos repository path
├── qemu_small_system_demo            --- small system default demo
├── qemu_mini_system_demo             --- mini system default demo
└── qemu_riscv_mini_system_demo       --- mini system demo with riscv architecture
```

## Installation

[QEMU Install Guide](https://gitee.com/openharmony/device_qemu/blob/HEAD/README.md)

## Usage

1. run command `hb set` to select the product target
```
ohos
 > qemu_small_system_demo
   qemu_mini_system_demo
```

`qemu_small_system_demo` indicates small system product demo, it contains
system components, such as graphic, foundation, etc.

`qemu_mini_system_demo` indicates mini system product demo, it contains
system components, such as samgr, hilog, etc.

2. run command `hb build` to start building。

3. To run the image with qemu. In details,

3.1 `qemu_small_system_demo` target,

```
./qemu-init
./qemu-run
```

use `vnc-client` to connect the host's 5920 port.

3.2 `qemu_mini_system_demo` target,

```
cd device/qemu/arm_mps2_an386
./qemu_run.sh ../../../out/arm_mps2_an386/bin/liteos
```
## Contribution

[How to involve](https://gitee.com/openharmony/docs/blob/HEAD/en/contribute/contribution.md)

[Commit message spec](https://gitee.com/openharmony/device_qemu/wikis/Commit%20message%E8%A7%84%E8%8C%83?sort_id=4042860)

## Repositories Involved

[device\_qemu](https://gitee.com/openharmony/device_qemu/blob/HEAD/README.md)

