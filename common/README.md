# OpenHarmony QEMU Emulator Launcher

本文档说明 OpenHarmony QEMU 模拟器镜像包的启动、qcow2 多实例和生命周期管理方法。启动器由产品 profile 驱动，同一套 Python 核心可用于 x86_64、AArch64 和 ARM32 产品；当前 `x86_64_virt` 完整编译会将本文档和便携启动器一起安装到镜像目录。

## 1. 镜像包内容

可直接运行的镜像目录至少包含：

```text
bzImage
ramdisk.img
updater.img
system.img
vendor.img
sys_prod.img
chip_prod.img
userdata.img
README.md
qemu_run.sh
qemu_run.cmd
qemu_profile.json
qemu_launcher.py
qemu_launcher_lib/
├── __init__.py
└── launcher.py
```

发布或移动镜像包时，必须保留 `qemu_launcher_lib` 的目录结构。基础 `.img` 文件由所有实例只读共享；客户机写入保存在独立的 qcow2 overlay 中。

## 2. 宿主机要求

| 宿主机 | 必需软件 | 推荐硬件加速 | 自动图形选择 |
| --- | --- | --- | --- |
| Linux | Python 3.8+、`qemu-system-x86_64`、`qemu-img` | KVM | GTK/SDL；无桌面时 VNC |
| macOS | Python 3.8+、对应架构 QEMU、`qemu-img` | HVF | Cocoa/SDL；远程会话时 VNC |
| Windows | Python 3.8+、对应架构 QEMU、`qemu-img` | WHPX | SDL/GTK；服务会话时 VNC |

启动器会实际探测加速器能否初始化。`auto` 模式下，硬件加速不可用时自动回退到 TCG。QEMU 不在 `PATH` 时使用 `--qemu-dir`，或分别使用 `--qemu-binary` 和 `--qemu-img`。

## 3. 编译与自动安装

完整编译命令：

```bash
./build.sh --product-name x86_64_virt --ccache --jobs 16 \
  --build-target make_all
```

构建依赖链为：

```text
make_all
  └── virt 产品配置
       └── //vendor/ohemu/virt:virtconfig_group
            └── //vendor/ohemu/virt/qemu_run:qemu_run_package
                 ├── //vendor/ohemu/common:qemu_launcher_common
                 └── qemu_run_product_entries
```

公共安装 target 定义在 `vendor/ohemu/common/BUILD.gn`，产品选择 target 定义在 `vendor/ohemu/virt/qemu_run/BUILD.gn`。后者根据 `target_cpu` 自动选择 x86_64、ARM64 或 ARM32 profile，并通过 GN `copy` target 将 README、包装脚本、profile 和 Python 核心复制到：

```text
out/x86_64_virt/packages/phone/images
```

只更新启动器或文档时，可以执行窄范围构建：

```bash
./build.sh --product-name x86_64_virt --ccache \
  --deps-guard=false --build-target qemu_run_package
```

## 4. 快速开始

Linux 或 macOS：

```bash
cd out/x86_64_virt/packages/phone/images

# 默认实例 00；自动选择加速器、显示和网络
./qemu_run.sh

# 后台启动实例 03，使用本机 VNC
./qemu_run.sh run --instance 03 --display vnc --background

# 查看实例状态
./qemu_run.sh status --instance 03

# 强制停止并删除测试实例
./qemu_run.sh stop --instance 03 --force
./qemu_run.sh delete --instance 03
```

Windows 命令提示符：

```bat
cd out\x86_64_virt\packages\phone\images
qemu_run.cmd run --instance 03 --display vnc --background
qemu_run.cmd status --instance 03
qemu_run.cmd stop --instance 03 --force
```

便携入口自动将脚本所在目录作为镜像目录，因此不依赖 OpenHarmony 源码树，也不依赖启动命令的当前工作目录。

## 5. 生命周期命令

| 命令 | 作用 | 是否修改实例数据 |
| --- | --- | --- |
| `run` | 创建或复用实例并启动 QEMU；省略命令时的默认操作 | 必要时创建 |
| `create` | 创建并校验 qcow2 overlay，不启动 QEMU | 是 |
| `list` | 列出当前 profile 和镜像集合的实例 | 否 |
| `status` | 显示状态、PID、端口、身份和路径 | 否 |
| `stop` | 通过 QMP 请求客户机关机 | 否 |
| `reset` | 丢弃实例全部写入并重建 overlay | 是，破坏性操作 |
| `delete` | 删除已停止实例及运行时文件 | 是，破坏性操作 |
| `diagnose` | 探测宿主机、QEMU、加速器和显示后端 | 否 |
| `print-command` | 打印最终 QEMU argv，不创建实例 | 否 |

完整、与当前版本一致的参数说明：

```bash
./qemu_run.sh --help
```

## 6. 常用选项

| 选项 | 说明 |
| --- | --- |
| `-i ID, --instance ID` | 两位实例号 `00..99`；默认 `00` |
| `-e PATH, --images PATH` | 指定镜像目录、包根目录或 zip/tar 包 |
| `--instance-root PATH` | 指定 manifest 和 qcow2 overlay 的持久化目录 |
| `--runtime-root PATH` | 指定 QMP、PID 和日志目录 |
| `--qemu-dir PATH` | 指定 QEMU 与 `qemu-img` 所在目录 |
| `--accel auto\|kvm\|hvf\|whpx\|tcg` | 加速器选择，默认 `auto` |
| `--display auto\|gtk\|sdl\|cocoa\|vnc\|none` | 图形后端选择 |
| `--network auto\|user\|bridge\|none` | 网络模式；bridge 仅支持 Linux |
| `--background` | 后台运行并将串口/QEMU 输出写入日志 |
| `-g, --gdb-wait` | 开启 GDB server，并在客户机启动前暂停 |
| `-f, --reset-before-run` | 启动前重建 overlay，丢弃该实例原有写入 |
| `--force` | 与 `stop` 配合，直接发送 QMP quit |
| `--json` | 为 list/status/diagnose 和错误输出 JSON |
| `--verbose` | 输出加速器探测等诊断细节 |

SN、MAC、HDC/VNC/GDB 端口不提供独立覆盖参数，全部由 profile 与 `--instance` 稳定生成，避免资源和实例身份不一致。

## 7. x86_64 实例资源映射

实例 `ID` 为两位十进制数：

```text
SN          = ID + "23456789"
MAC         = 52:54:00:58:00:<ID 的十六进制值>
HDC 端口    = 5555 + ID
VNC display = 21 + ID
VNC TCP端口 = 5921 + ID
GDB 端口    = 1234 + ID
```

示例：

| 实例 | SN | MAC | HDC | VNC TCP | GDB |
| --- | --- | --- | ---: | ---: | ---: |
| `00` | `0023456789` | `52:54:00:58:00:00` | 5555 | 5921 | 1234 |
| `01` | `0123456789` | `52:54:00:58:00:01` | 5556 | 5922 | 1235 |
| `03` | `0323456789` | `52:54:00:58:00:03` | 5558 | 5924 | 1237 |

其他 profile 使用不同 `port_slot`，可以避免不同 CPU 架构的同号实例发生端口或 MAC 冲突。

## 8. qcow2 实例数据

每个可写 raw 分区对应一个 qcow2 overlay：

```text
<instance-root>/<ID>/
├── manifest.json
├── updater.qcow2
├── system.qcow2
├── vendor.qcow2
├── sys_prod.qcow2
├── chip_prod.qcow2
└── userdata.qcow2
```

manifest 记录 profile、实例号、镜像根目录和基础盘签名。重新编译或替换基础 raw 后，旧 overlay 会被拒绝启动；确认不再需要客户机数据后执行：

```bash
./qemu_run.sh reset --instance ID
```

不要对正在运行的 overlay 执行 `qemu-img rebase`、`commit`、`resize` 或修复操作。

启动器创建 overlay 时使用 64 KiB cluster 并关闭 lazy refcounts。这样即使通过 QEMU 控制台 `Ctrl-A X` 立即退出，已分配数据簇的 refcount 也会同步写入，下一次启动的严格 `qemu-img check` 不会因延迟 refcount 元数据而失败。

升级前创建且仍然一致的 lazy-refcount overlay 会在实例停止状态下自动迁移为关闭；迁移前后都会执行完整一致性检查。已经损坏的 overlay 不会被静默修复，需先备份，再选择人工修复或 `reset` 重建。

## 9. 默认数据目录

便携镜像包默认不会写入自身目录：

| 宿主机 | 默认实例目录 |
| --- | --- |
| Linux | `${XDG_STATE_HOME:-~/.local/state}/openharmony-qemu` |
| macOS | `~/Library/Application Support/OpenHarmony/QEMU` |
| Windows | `%LOCALAPPDATA%\OpenHarmony\QEMU\State` |

QMP、PID 和日志使用短临时路径，以避免 Unix socket 路径长度限制。需要固定位置时设置：

```bash
export QEMU_INSTANCE_ROOT=/path/to/qemu-instances
export QEMU_RUNTIME_ROOT=/short/path/qemu-runtime
```

## 10. 指定外部镜像包

```bash
# 完整镜像目录
./qemu_run.sh run --images /path/to/images --instance 02

# 包含唯一完整 images 子目录的包根目录
./qemu_run.sh run --images /path/to/package --instance 02

# zip 或 tar 归档
./qemu_run.sh run --images /path/to/images.zip --instance 02
```

归档文件按照内容 SHA-256 缓存解压，并拒绝绝对路径、目录穿越和符号链接。外部镜像使用独立状态空间，不会与产品默认镜像实例混用。

## 11. 常见问题

### 没有可用的硬件加速

执行：

```bash
./qemu_run.sh diagnose --verbose
```

Linux 检查 `/dev/kvm` 是否存在且当前用户可读写；BIOS/UEFI 中需启用虚拟化。无法使用硬件加速时可显式测试 `--accel tcg`。

### 没有桌面或图形窗口无法打开

使用 VNC 或无图形后台模式：

```bash
./qemu_run.sh run --instance 01 --display vnc --background
./qemu_run.sh run --instance 01 --display none --background
```

VNC 默认仅监听 `127.0.0.1`。

### 端口已被占用

每个实例号具有固定端口。先使用 `status/list` 检查是否已有同号实例；选择其他实例号，不要手工修改端口与身份映射。

### 报告基础镜像已变化

编译覆盖了 raw 基础盘。确认实例数据可以丢弃后执行 `reset`；需要保留旧客户机数据时，应先保留整套旧基础镜像和 overlay。

### 后台日志位置

`run --background` 的摘要会打印日志路径。运行时目录通常包含：

```text
runtime.json
qemu.pid
qmp.sock
qemu.log
serial.log
supervisor.log
```
