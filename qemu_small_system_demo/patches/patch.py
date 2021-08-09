# Copyright (c) 2020-2021 Huawei Device Co., Ltd. All rights reserved.
#
# Redistribution and use in source and binary forms, with or without modification,
# are permitted provided that the following conditions are met:
#
# 1. Redistributions of source code must retain the above copyright notice, this list of
#    conditions and the following disclaimer.
#
# 2. Redistributions in binary form must reproduce the above copyright notice, this list
#    of conditions and the following disclaimer in the documentation and/or other materials
#    provided with the distribution.
#
# 3. Neither the name of the copyright holder nor the names of its contributors may be used
#    to endorse or promote products derived from this software without specific prior written
#    permission.
#
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS
# "AS IS" AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO,
# THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR
# PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR
# CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL,
# EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO,
# PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR PROFITS;
# OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY,
# WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR
# OTHERWISE) ARISING IN ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF
# ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.

import shutil
import sys
import os

graphic_config_path = 'foundation/graphic/utils/interfaces/innerkits/graphic_config.h'

if __name__ == '__main__':
    if len(sys.argv) > 1:
        root_dir = sys.argv[1]
        root_dir = os.path.join(os.getcwd(), root_dir)
        shutil.copy(os.path.join(root_dir, "vendor/ohemu/qemu_small_system_demo/patches/qemu-run"), root_dir)

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

