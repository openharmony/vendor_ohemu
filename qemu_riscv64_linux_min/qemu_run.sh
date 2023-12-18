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

OHOS_IMG="out/qemu-riscv64-linux/packages/phone/images"

qemu-system-riscv64 \
	-machine virt -m 2028 \
	-smp 2 \
	-nographic \
	--no-reboot \
	-kernel ${OHOS_IMG}/Image \
	-initrd ${OHOS_IMG}/ramdisk.img \
	-drive if=none,file=${OHOS_IMG}/updater.img,format=raw,id=updater,index=3 -device virtio-blk-device,drive=updater \
	-drive if=none,file=${OHOS_IMG}/system.img,format=raw,id=system,index=2 -device virtio-blk-device,drive=system \
	-drive if=none,file=${OHOS_IMG}/vendor.img,format=raw,id=vendor,index=1 -device virtio-blk-device,drive=vendor \
	-drive if=none,file=${OHOS_IMG}/userdata.img,format=raw,id=userdata,index=0 -device virtio-blk-device,drive=userdata \
	-append "loglevel=4 console=ttyS0,115200 init=init root=/dev/ram0 rw  ohos.boot.hardware=qemu.riscv64.linux default_boot_device=10007000.virtio_mmio sn=8823456789 ohos.required_mount.system=/dev/block/vdb@/usr@ext4@ro,barrier=1@wait,required ohos.required_mount.vendor=/dev/block/vdc@/vendor@ext4@ro,barrier=1@wait,required ohos.required_mount.data=/dev/block/vdd@/data@ext4@nosuid,nodev,noatime,barrier=1,data=ordered,noauto_da_alloc@wait,reservedsize=104857600"

