#!/bin/bash

#Copyright (c) 2020-2021 Huawei Device Co., Ltd.
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

set -e
elf_file=$1
rebuild_image=$2
vnc_enable=$3
add_boot_args=$4
boot_args=$5
net_enable=$6
gdb_enable=$7
qemu_test=$8
test_file=$9
qemu_help=${10}

vnc="-vnc :20  -serial mon:stdio"
qemu_option=""

if [ "$elf_file" = "" ]; then
    elf_file=out/qemu-arm-linux/packages/phone/images
fi

help_info=$(cat <<-END
Usage: qemu-run [OPTION]...
Run a OHOS image in qemu according to the options.

    Options:

    -e,  --exec image_path    build images path, including: zImage-dtb, ramdisk.img, system.img, vendor.img, userdata.img
    -g,  --gdb                enable gdb for kernel
    -h,  --help               print help info

    By default, the kernel exec file is: ${elf_file}.
END
)

if [ "$qemu_help" = "yes" ]; then
    echo "${help_info}"
    exit 0
fi

if [ "$gdb_enable" = "yes" ]; then
    qemu_option+="-s -S"
fi

function start_qemu(){
    qemu-system-arm -M virt -cpu cortex-a7 -smp 4 -m 1024 -nographic \
    $qemu_option \
    -drive if=none,file=$elf_file/userdata.img,format=raw,id=userdata,index=3 -device virtio-blk-device,drive=userdata \
    -drive if=none,file=$elf_file/vendor.img,format=raw,id=vendor,index=2 -device virtio-blk-device,drive=vendor \
    -drive if=none,file=$elf_file/system.img,format=raw,id=system,index=1 -device virtio-blk-device,drive=system \
    -drive if=none,file=$elf_file/updater.img,format=raw,id=updater,index=0 -device virtio-blk-device,drive=updater \
    -kernel $elf_file/zImage-dtb -initrd $elf_file/ramdisk.img \
    -append "console=ttyAMA0,115200 init=/bin/init hardware=qemu.arm.linux default_boot_device=a003e00.virtio_mmio root=/dev/ram0 rw"
}

start_qemu
