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

qemu_test=""
gdb_option=""
out_file=""
out_option=""
elf_file=out/arm_mps2_an386/qemu_mini_system_demo/bin/liteos

help_info=$(cat <<-END
Usage: qemu-run [OPTION]...
Run a OHOS image in qemu according to the options.

    Options:

    -f, --file file_name     kernel exec file name
    -g, --gdb                enable gdb for kernel
    -t, --test log.txt       test mode, exclusive with -g
    -h, --help               print help info

    By default, the kernel exec file is: ${elf_file}.
END
)

function start_qemu(){
    set +e
    read -t 5 -p "Enter to start qemu[y/n]:" flag
    set -e
    start=${flag:-y}
    if [ ${start} = y ]; then
      if [ "${qemu_test}" == "test" ]; then
        vendor/ohemu/qemu_mini_system_demo/qemu_test_monitor.sh $out_file &
      fi
      `which qemu-system-arm` -M mps2-an386 -m 16M -kernel $elf_file $gdb_option \
          -append "root=dev/vda or console=ttyS0" $out_option -nographic
    else
        echo "Exit qemu-run"
    fi
}

############################## main ##############################
ARGS=`getopt -o f:gt:h --l file:,gdb,test:,help -n "$0" -- "$@"`
if [ $? != 0 ]; then
    echo "Try '$0 --help' for more information."
    exit 1
fi
eval set --"${ARGS}"

while true;do
    case "${1}" in
        -f|--file)
        elf_file="${2}"
        shift;
        shift;
        ;;
        -t|--test)
        qemu_test="test"
        out_file="${2}"
        out_option="-serial file:$out_file"
        shift;
        shift;
        ;;
        -g|--gdb)
        shift;
        gdb_option="-s -S"
        echo -e "Qemu kernel gdb enable..."
        ;;
        -h|--help)
        shift;
        echo -e "${help_info}"
        exit
        ;;
        --)
        shift;
        break;
        ;;
    esac
done

if [ "$elf_file" == "" ] || [ ! -f "${elf_file}" ]; then
  echo "Specify the path to the executable file"
  echo -e "${help_info}"
  exit 1
fi
if [ "${gdb_option}" != "" ] && [ "${qemu_test}" != "" ]; then
  echo "Error: '-g' '-t' options cannot be used together"
  exit 2
fi
echo -e "elf_file = ${elf_file}"
start_qemu

function test_success() {
  echo "Test success!!!"
  exit 0
}

function test_failed() {
  cat $out_file
  echo "Test failed!!!"
  exit 1
}

if [ "$qemu_test" = "test" ]; then
  if [ ! -f "$out_file" ]; then
    test_failed
  else
    result=`tail -1 $out_file`
    if [ "$result" != "--- Test End ---" ]; then
      test_failed
    fi

    result=`tail -2 $out_file`
    failedresult=${result%,*}
    failed=${failedresult%:*}
    if [ "$failed" != "failed count" ]; then
      test_failed
    fi

    failedcount=${failedresult#*:}
    if [ "$failedcount" = "0" ]; then
      test_success
    else
      test_failed
    fi
  fi
fi
