# OpenHarmony QEMU Emulator Launcher

本文档说明 OpenHarmony QEMU 模拟器镜像包的启动、qcow2 多实例和生命周期管理方法。启动器由产品 profile 驱动，同一套 Python 核心可用于 x86_64、AArch64 和 ARM32 产品；镜像包中附带启动器，解压后即可直接运行，无需额外安装。

## 1. 宿主机要求

| 宿主机 | 必需软件 | 推荐硬件加速 | 自动图形选择 |
| --- | --- | --- | --- |
| Linux | Python 3.8+、对应客户机架构的 `qemu-system-*`、`qemu-img` | KVM | GTK/SDL；无桌面时 VNC |
| macOS | Python 3.8+、对应客户机架构的 QEMU、`qemu-img` | HVF | Cocoa/SDL；远程会话时 VNC |
| Windows | Python 3.8+、对应客户机架构的 QEMU、`qemu-img` | WHPX | SDL/GTK；服务会话时 VNC |

客户机架构决定所需的 QEMU 二进制：x86_64 客户机用 `qemu-system-x86_64`，AArch64 用 `qemu-system-aarch64`，ARM32 用 `qemu-system-arm`。

启动器会实际探测加速器能否初始化。`auto` 模式下，硬件加速不可用时自动回退到 TCG。QEMU 不在 `PATH` 时使用 `--qemu-dir`，或分别使用 `--qemu-binary` 和 `--qemu-img`。

## 2. 快速开始

进入镜像目录（包含 `qemu_run.sh` 与各 `.img` 文件的目录）。

Linux 或 macOS：

```bash
cd <镜像目录>

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
cd <镜像目录>
qemu_run.cmd run --instance 03 --display vnc --background
qemu_run.cmd status --instance 03
qemu_run.cmd stop --instance 03 --force
```

便携入口自动将脚本所在目录作为镜像目录，因此不依赖 OpenHarmony 源码树，也不依赖启动命令的当前工作目录。

## 3. 启动后模拟器的使用方法

模拟器启动后，通过 hdc 命令行或 VNC 图形界面与客户机交互。连接端口由实例号与客户机架构决定（见「实例资源映射」），以下以默认实例 `00`、x86_64 客户机为例；其他实例号或架构的端口在实例资源映射表对应基址上偏移。

### hdc 连接与命令行

`run`/`create` 启动时，启动器默认以 user 网络模式将客户机 5555 端口转发到宿主机 `127.0.0.1:<HDC 端口>`（默认实例 `00` 为 `5555`）。先用 `hdc tconn` 连接，再用 `hdc -t` 指定目标执行命令：

```bash
# 连接模拟器（默认实例 00 的 HDC 端口为 5555）
hdc tconn 127.0.0.1:5555

# 进入交互式 shell
hdc -t 127.0.0.1:5555 shell

# 单次执行命令示例
hdc -t 127.0.0.1:5555 shell hilog | head
hdc -t 127.0.0.1:5555 install /path/to/entry-default-signed.hap
hdc -t 127.0.0.1:5555 file send /local/path /data/local/tmp/
```

其他实例号或架构的 HDC 端口见「实例资源映射」，例如实例 `03` 的 HDC 端口为 `5558`。

### VNC 图形界面

使用 `--display vnc`（或无桌面场景自动选择 VNC）启动时，QEMU 在 `127.0.0.1:<VNC TCP 端口>` 提供 VNC 服务（默认实例 `00` 为 `5921`，对应 display `:21`）。用任意 VNC 客户端连接：

```bash
# 显式端口形式
vncviewer 127.0.0.1::5921

# 或 display 形式（display 21 即端口 5921）
vncviewer 127.0.0.1:21
```

VNC 默认仅监听 `127.0.0.1`，仅本机可达；在远程开发环境（VS Code / code-server 类 CodeSpace）中的远程访问方式见下节。其他实例号或架构的 VNC 端口见「实例资源映射」。

### 通过 VS Code 端口代理远程访问 VNC

在基于 VS Code（code-server）的远程开发环境（CodeSpace）中，远程网关只代理 HTTP/WebSocket，无法转发 VNC 的裸 TCP。借助 VS Code「端口（Ports）」面板 + noVNC 网页客户端即可在本地浏览器访问模拟器画面。

前置准备（每个工作区执行一次）：

```bash
pip3 install --user websockify
git clone --depth 1 https://github.com/novnc/noVNC ~/noVNC
```

以实例 `00`、x86_64（VNC TCP 端口 `5921`）为例，操作流程：

1. 启动模拟器，VNC 监听本机 5921：

   ```bash
   ./qemu_run.sh run --instance 00 --display vnc --background
   ```

2. 另开终端，启动 websockify 桥接 + noVNC 网页（监听 6080，桥接到本机 VNC 5921）：

   ```bash
   ~/.local/bin/websockify --web ~/noVNC 6080 127.0.0.1:5921
   ```

3. 打开「端口」面板：菜单 **View → Open View… → Ports**（或点击底部面板的 **Ports** 标签）。列表会自动发现 `6080`；若未出现，点面板右上 **Forward a Port**（`+`）并输入 `6080`。

4. 在 `6080` 一行右键 → **Open in Browser**（地球图标），或点 **Forwarded Address** 列复制 forwarded URL（形如 `http://<网关>/proxy/6080/`）。

5. 浏览器打开 noVNC 页面（URL 格式与参数见下文）。noVNC 经代理的 WebSocket 回连到 websockify，再桥接到 QEMU VNC，显示模拟器画面。

**访问 URL 格式**（`<网关>` 取 Ports 面板里 `6080` 的 Forwarded Address 的 `host:port` 部分，`<端口>` 取 websockify 监听端口）：

```
http://<网关>/proxy/<端口>/vnc.html?host=&path=websockify&autoconnect=true&resize=scale
```

示例（网关 `123.249.34.178:40097`、端口 `6080`）：

```
http://123.249.34.178:40097/proxy/6080/vnc.html?host=&path=websockify&autoconnect=true&resize=scale
```

noVNC 会把 WebSocket 连到 `ws://<网关>/proxy/<端口>/websockify`，经代理转发到 websockify，再桥接到 QEMU VNC（`127.0.0.1:<VNC 端口>`）。

**查询参数说明**：

| 参数 | 必填 | 含义与作用 |
| --- | --- | --- |
| `host` | 是 | noVNC 连接的 WebSocket 主机。**留空**（`host=`）让 noVNC 沿用页面 URL 的 host（即 CodeSpace 网关）。不能省略：省略后 noVNC 可能读取浏览器 localStorage 里残留的旧 host，导致 WebSocket 连到错误地址而报"无法连接到服务器"。 |
| `path` | 是 | noVNC 连接的 WebSocket 路径，设为 `websockify`（websockify 的 WS 端点）。noVNC 以页面 URL 为基准将其解析为 `/proxy/<端口>/websockify`。不能省略。 |
| `autoconnect` | 否 | `true`：页面加载后自动发起连接，无需手动点击连接按钮。 |
| `resize` | 否 | `scale`：将远端画面缩放适配浏览器视口；不传则按原始分辨率显示。 |
| `reconnect` | 否 | `true`：连接断开后自动重连。 |

说明：

- forwarded URL 沿用 WebIDE 登录会话，用登录着 WebIDE 的浏览器打开即可，无需额外鉴权。
- 其他实例号或架构的 VNC 端口见「实例资源映射」，改 websockify 的目标端口即可（实例 `03`→`5924`，AArch64→`6021`，ARM32→`6121`）。
- 端口可见性默认 **Private**，仅自己可访问；需他人访问可在端口行右键将 **Port Visibility** 改为 **Public**。

## 4. 生命周期命令

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

### 前台运行与退出（Ctrl-A 转义）

不带 `--background` 的前台运行会把终端接到 QEMU 串口（`-serial mon:stdio`，monitor 与串口复用，终端为 raw 模式）。此时 `Ctrl-C` **不会**退出模拟器（被透传给客户机串口），改用 QEMU 的 `Ctrl-A` 转义序列：

| 按键 | 作用 |
| --- | --- |
| `Ctrl-A X` | 退出 QEMU（前台最常用） |
| `Ctrl-A C` | 在串口与 QEMU monitor 之间切换 |
| `Ctrl-A H` | 打印全部 `Ctrl-A` 转义帮助 |
| `Ctrl-A Ctrl-A` | 把 `Ctrl-A` 作为普通字节送给客户机 |

后台运行（`--background`）时串口重定向到文件、QEMU 脱离终端，没有 `Ctrl-A`；改用 `stop` 命令经 QMP 关机即可。

## 5. 常用选项

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

## 6. 实例资源映射

每个实例的身份与端口由两位十进制实例号 `ID` 与 profile 的 `port_slot` 共同决定。`port_slot` 按客户机架构区分，避免不同架构的同号实例发生端口或 MAC 冲突：

```text
SN          = ID + "23456789"
MAC         = 52:54:<port_slot>:58:00:<ID 的十六进制值>
HDC 端口    = 5555 + port_slot×100 + ID
VNC display = 21 + port_slot×100 + ID
VNC TCP 端口 = 5921 + port_slot×100 + ID
GDB 端口    = 1234 + port_slot×100 + ID
```

各架构的 `port_slot` 取值：

| 客户机架构 | port_slot | HDC 基址 | VNC TCP 基址 | GDB 基址 | MAC 前缀 |
| --- | --- | ---: | ---: | ---: | --- |
| x86_64 | 0 | 5555 | 5921 | 1234 | 52:54:00:58:00 |
| AArch64 | 1 | 5655 | 6021 | 1334 | 52:54:01:58:00 |
| ARM32 | 2 | 5755 | 6121 | 1434 | 52:54:02:58:00 |

以 x86_64（`port_slot=0`）为例：

| 实例 | SN | MAC | HDC | VNC TCP | GDB |
| --- | --- | --- | ---: | ---: | ---: |
| `00` | `0023456789` | `52:54:00:58:00:00` | 5555 | 5921 | 1234 |
| `01` | `0123456789` | `52:54:00:58:00:01` | 5556 | 5922 | 1235 |
| `03` | `0323456789` | `52:54:00:58:00:03` | 5558 | 5924 | 1237 |

AArch64 与 ARM32 的同号实例端口在 x86_64 基础上分别再偏移 100 和 200。

## 7. qcow2 实例数据

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

manifest 记录 profile、实例号、镜像根目录和基础盘签名。基础 raw 镜像被替换或更新后，旧 overlay 会被拒绝启动；确认不再需要客户机数据后执行：

```bash
./qemu_run.sh reset --instance ID
```

不要对正在运行的 overlay 执行 `qemu-img rebase`、`commit`、`resize` 或修复操作。

启动器创建 overlay 时使用 64 KiB cluster 并关闭 lazy refcounts。这样即使通过 QEMU 控制台 `Ctrl-A X` 立即退出，已分配数据簇的 refcount 也会同步写入，下一次启动的严格 `qemu-img check` 不会因延迟 refcount 元数据而失败。

升级前创建且仍然一致的 lazy-refcount overlay 会在实例停止状态下自动迁移为关闭；迁移前后都会执行完整一致性检查。已经损坏的 overlay 不会被静默修复，需先备份，再选择人工修复或 `reset` 重建。

## 8. 默认数据目录

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

## 9. 指定外部镜像包

```bash
# 完整镜像目录
./qemu_run.sh run --images /path/to/images --instance 02

# 包含唯一完整 images 子目录的包根目录
./qemu_run.sh run --images /path/to/package --instance 02

# zip 或 tar 归档
./qemu_run.sh run --images /path/to/images.zip --instance 02
```

归档文件按照内容 SHA-256 缓存解压，并拒绝绝对路径、目录穿越和符号链接。外部镜像使用独立状态空间，不会与产品默认镜像实例混用。

## 10. 常见问题

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

基础 raw 镜像被替换或更新后，旧 overlay 会被拒绝启动。确认实例数据可以丢弃后执行 `reset`；需要保留旧客户机数据时，应先保留整套旧基础镜像和 overlay。

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
