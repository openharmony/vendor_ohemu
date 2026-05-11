#!/bin/bash

#Copyright 2024 Institute of Software, Chinese Academy of Sciences.
#Licensed under the Apache License, Version 2.0 (the "License");
#you may not use this file except in compliance with the License.
#You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
#Unless required by applicable law or agreed to in writing, software
#distributed under the License is distributed on an "AS IS" BASIS,
#WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#See the License for the specific language governing permissions and
#limitations under the License.

OHOS_IMG="out/arm64_virt/packages/phone/images"
BRIDGE_NAME="${QEMU_BRIDGE_NAME:-virbr0}"
BRIDGE_CONF="${QEMU_BRIDGE_CONF:-/etc/qemu/bridge.conf}"

NET_ARGS=(
    -netdev user,id=net0
    -device virtio-net-device,netdev=net0,mac=12:22:33:44:55:66
)

if ip link show "${BRIDGE_NAME}" >/dev/null 2>&1 && \
   [ -r "${BRIDGE_CONF}" ] && \
   grep -Eq "^[[:space:]]*allow[[:space:]]+${BRIDGE_NAME}([[:space:]]*$|[[:space:]]+#)" "${BRIDGE_CONF}"; then
    NET_ARGS=(
        -netdev bridge,id=net0,br="${BRIDGE_NAME}"
        -device virtio-net-device,netdev=net0,mac=12:22:33:44:55:66
    )
else
    echo "Bridge network is unavailable, fallback to user-mode NAT." >&2
    echo "Expected bridge: ${BRIDGE_NAME}, ACL file: ${BRIDGE_CONF}" >&2
fi

sudo qemu-system-aarch64 \
-M virt \
-cpu cortex-a57 \
-smp 4 \
-m 4096 \
-kernel ${OHOS_IMG}/Image \
-initrd ${OHOS_IMG}/ramdisk.img \
-nographic \
-vga none \
-device virtio-gpu-pci,xres=800,yres=500 \
-vnc :21 \
-display sdl,gl=off \
-device virtio-mouse-pci \
-device virtio-keyboard-pci \
-k en-us \
-rtc base=localtime,clock=host \
-device es1370 \
"${NET_ARGS[@]}" \
-drive if=none,file=${OHOS_IMG}/userdata.img,format=raw,id=userdata,index=5 -device virtio-blk-device,drive=userdata \
-drive if=none,file=${OHOS_IMG}/chip_prod.img,format=raw,id=chip_prod,index=4 -device virtio-blk-device,drive=chip_prod \
-drive if=none,file=${OHOS_IMG}/sys_prod.img,format=raw,id=sys_prod,index=3 -device virtio-blk-device,drive=sys_prod \
-drive if=none,file=${OHOS_IMG}/vendor.img,format=raw,id=vendor,index=2 -device virtio-blk-device,drive=vendor \
-drive if=none,file=${OHOS_IMG}/system.img,format=raw,id=system,index=1 -device virtio-blk-device,drive=system \
-drive if=none,file=${OHOS_IMG}/updater.img,format=raw,id=updater,index=0 -device virtio-blk-device,drive=updater \
-append " \
ip=dhcp \
loglevel=7 \
console=tty0,115200 console=ttyAMA0,115200 \
init=/bin/init ohos.boot.hardware=virt \
root=/dev/ram0 rw \
ohos.required_mount.system=/dev/block/vdb@/usr@ext4@ro,barrier=1@wait,required \
ohos.required_mount.vendor=/dev/block/vdc@/vendor@ext4@ro,barrier=1@wait,required \
ohos.required_mount.sys_prod=/dev/block/vdd@/sys_prod@ext4@rw,barrier=1@wait,required \
ohos.required_mount.chip_prod=/dev/block/vde@/chip_prod@ext4@rw,barrier=1@wait,required \
ohos.required_mount.data=/dev/block/vdf@/data@ext4@nosuid,nodev,noatime,barrier=1,data=ordered,noauto_da_alloc@wait,reservedsize=104857600"
