import shutil
import sys
import os

graphic_config_path = 'foundation/graphic/utils/interfaces/innerkits/graphic_config.h'

if __name__ == '__main__':
    if len(sys.argv) > 1:
        root_dir = sys.argv[1]
        root_dir = os.path.join(os.getcwd(), root_dir)
        shutil.copy(os.path.join(root_dir, "device/hisilicon/drivers/libs/ohos/llvm/hi3518ev300/libspinor_flash.a"),
                    os.path.join(root_dir, "device/qemu/drivers/libs/virt/libspinor_flash.a"))
        shutil.copy(os.path.join(root_dir, "vendor/ohemu/display_qemu_liteos_a/patches/qemu-run"), root_dir)

        graphic_config_abs_path = os.path.join(root_dir, graphic_config_path)
        print(graphic_config_abs_path)
        if os.path.isfile(graphic_config_abs_path):
            with open(graphic_config_abs_path, 'r+') as f:
                flist = f.readlines()
                for i in range(len(flist)):
                    if 'static constexpr const char* VECTOR_FONT_DIR = "/user/data/"' in flist[i]:
                        print('='*40 + ' find it ' + '='*40)
                        flist[i] = 'static constexpr const char* VECTOR_FONT_DIR = "/storage/data/";\n'
                        break
                with open(graphic_config_abs_path, 'w+') as nf:
                    nf.writelines(flist)

