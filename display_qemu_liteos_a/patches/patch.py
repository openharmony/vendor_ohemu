import shutil
import sys
import os

if __name__ == '__main__':
    if len(sys.argv) > 1:
        root_dir = sys.argv[1]
        root_dir = os.path.join(os.getcwd(), root_dir)
        shutil.copy(os.path.join(root_dir, "device/hisilicon/drivers/libs/ohos/llvm/hi3518ev300/libspinor_flash.a"),
                    os.path.join(root_dir, "device/qemu/drivers/libs/virt/libspinor_flash.a"))
        shutil.copy(os.path.join(root_dir, "vendor/ohemu/display_qemu_liteos_a/patches/qemu-init"), root_dir)
        shutil.copy(os.path.join(root_dir, "vendor/ohemu/display_qemu_liteos_a/patches/qemu-run"), root_dir)

