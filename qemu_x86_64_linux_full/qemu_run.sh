#!/bin/bash

set -euo pipefail

OHOS_IMG="${OHOS_IMG:-out/x86_64_virt/packages/phone/images}"
DISPLAY_TYPE="${QEMU_DISPLAY:-gtk}"
ACCEL="tcg"

if [ -e /dev/kvm ] && [ -r /dev/kvm ]; then
    ACCEL="kvm"
fi

case "${DISPLAY_TYPE}" in
    none)
        DISPLAY_ARGS=(
            -display none
            -serial mon:stdio
        )
        ;;
    vnc)
        DISPLAY_ARGS=(
            -device virtio-gpu-pci
            -vnc :21
            -serial stdio
        )
        ;;
    sdl)
        DISPLAY_ARGS=(
            -device virtio-gpu-pci
            -display sdl,gl=off
            -serial stdio
        )
        ;;
    gtk|*)
        DISPLAY_ARGS=(
            -device virtio-gpu-pci
            -display gtk,gl=off
            -serial stdio
        )
        ;;
esac

KERNEL_BOOTARGS="console=ttyS0,115200 init=/bin/init hardware=qemu.x86_64.linux root=/dev/ram0 rw ohos.boot.hardware=virt ohos.required_mount.system=/dev/block/vdc@/usr@ext4@ro,barrier=1@wait,required ohos.required_mount.vendor=/dev/block/vdd@/vendor@ext4@ro,barrier=1@wait,required ohos.required_mount.sys_prod=/dev/block/vde@/sys_prod@ext4@rw,barrier=1@wait,required ohos.required_mount.chip_prod=/dev/block/vdf@/chip_prod@ext4@rw,barrier=1@wait,required ohos.required_mount.data=/dev/block/vdb@/data@ext4@nosuid,nodev,noatime,barrier=1,data=ordered,noauto_da_alloc@wait,reservedsize=104857600"

exec qemu-system-x86_64 \
    -machine q35,accel="${ACCEL}" \
    -cpu max \
    -smp 4 \
    -m 4096 \
    -kernel "${OHOS_IMG}/bzImage" \
    -initrd "${OHOS_IMG}/ramdisk.img" \
    "${DISPLAY_ARGS[@]}" \
    -device virtio-mouse-pci \
    -device virtio-keyboard-pci \
    -netdev user,id=net0,hostfwd=tcp::5555-:5555 \
    -device virtio-net-pci,netdev=net0 \
    -drive if=none,file="${OHOS_IMG}/updater.img",format=raw,id=updater \
    -device virtio-blk-pci,drive=updater,serial=updater \
    -drive if=none,file="${OHOS_IMG}/system.img",format=raw,id=system \
    -device virtio-blk-pci,drive=system,serial=system \
    -drive if=none,file="${OHOS_IMG}/vendor.img",format=raw,id=vendor \
    -device virtio-blk-pci,drive=vendor,serial=vendor \
    -drive if=none,file="${OHOS_IMG}/sys_prod.img",format=raw,id=sys_prod \
    -device virtio-blk-pci,drive=sys_prod,serial=sys_prod \
    -drive if=none,file="${OHOS_IMG}/chip_prod.img",format=raw,id=chip_prod \
    -device virtio-blk-pci,drive=chip_prod,serial=chip_prod \
    -drive if=none,file="${OHOS_IMG}/userdata.img",format=raw,id=userdata \
    -device virtio-blk-pci,drive=userdata,serial=userdata \
    -append "${KERNEL_BOOTARGS}"
