# Wuji CLI 灰测安装与更新仓库

本仓库（`DBinKv1/install`）作为 `wuji update` 的灰测源，提供高版本号（如 `2077.x.x`）的 Release 资产与配套 Skills。

---

## 阶段一：灰测仓库发版（生成灰测版本）

升级测试前，本仓库必须有对应的灰测 Release 资产。

### 1. 前置条件

1. **仓库公开状态**：发版前仓库必须为 Public。仓库为私有状态时，客户端下载返回 404。演练模式不受此限。改为 Public：
   ```bash
   gh repo edit DBinKv1/install --visibility public --accept-visibility-change-consequences
   ```
2. **依赖工具**：安装 `uv`、`gh`、`git`、`rcodesign`。安装签名工具：
   ```bash
   cargo binstall -y apple-codesign
   ```
3. **工作区状态**：必须在本仓库根目录执行。本地 git 工作区必须没有未提交改动。

### 2. 触发自动发版

```bash
# 首次准备依赖环境
uv sync

# 默认自动拉取上游最新正式版，并升级为 2077 超大版本
uv run gray

# 也可自定义指定等长版本号
uv run gray --to 2077.11.10

# 正式发版前，可随时进行无害演练
uv run gray --dry-run
```

生成过程使用的路径：

- `tmp/cache/v<上游版本>/`：下载得到的原始资产，已被 `.gitignore` 忽略。命中缓存则跳过下载，并按 API 声明的 sha256 校验。
- `tmp/work/upstream/`：上游仓库浅克隆，后续运行只做 `git fetch` 到目标 tag。
- `tmp/work/dist/`：补丁后的产物，同名文件直接覆盖。
- `tmp/work/repo-preview/`：演练时由 `git archive` 展开的仓库预览。
- 系统临时目录（`tempfile.TemporaryDirectory`，前缀 `wuji-gray-`）：单个资产解包、打补丁、重签使用。打包完成后自动删除。日志会打印实际路径，例如 `/var/folders/.../wuji-gray-tf_7ura8`。

**警告**：正式发版会**永久删除全部旧 Release 与旧 Tag**。上游内容会完全覆盖本地 `skills/` 与 `scripts/`。

---

## 阶段二：使用灰测源验证客户端升级

灰测 Release 发布后，在 **`wuji-cli-dev` 代码仓库**验证客户端升级。

> **说明**：以下命令在 `wuji-cli-dev` 仓库根目录执行。如果尚未构建，先执行 `cargo build`。生成的文件为 `./target/debug/wuji`，版本 `2026.10.26`，低于灰测仓库的 `2077` 版本，可以触发升级。

### 1. 检查更新（建议隔离主目录）

`wuji update --check` 会写入 `~/.wuji/cli/state.json`。如果不想改动本机状态文件，在临时主目录运行：

```bash
HOME=$(mktemp -d) WUJI_UPDATE_REPO=DBinKv1/install ./target/debug/wuji update --check
```

```pwsh
pwsh -NoProfile -Command '$env:USERPROFILE=$env:TEMP; $env:WUJI_UPDATE_REPO="DBinKv1/install";
.\target\debug\wuji.exe update --check'
```

如果输出显示新版本（如 `2077.10.26`），且 Release URL 指向 `DBinKv1/install`，灰测通道已连通。

---

### 2. 执行端到端升级灰测

> **警告**：
> 1. `wuji update` 执行**原地二进制替换**（Self-Replace）。必须先把二进制拷贝到临时目录。禁止对开发目录的 `./target/debug/wuji` 执行更新。
> 2. 升级成功后，`wuji` 会同步配套 Skills，可能覆盖全局目录。必须隔离主目录。

#### 方式一：一键测试

一次执行完，结束后自动清理临时目录，适合单次验证。

**macOS / Linux**

```bash
# 1. 准备隔离主目录与副本二进制
TEST_DIR=$(mktemp -d)
echo $TEST_DIR
cp ./target/debug/wuji "$TEST_DIR/wuji"

# 2. 在完全隔离的环境下执行升级
HOME="$TEST_DIR" \
USERPROFILE="$TEST_DIR" \
WUJI_TELEMETRY_DISABLE=1 \
WUJI_UPDATE_REPO=DBinKv1/install \
  "$TEST_DIR/wuji" update

# 3. 验证升级后的自报版本
"$TEST_DIR/wuji" --version

# 4. （可选）验证 Skills 单独同步
HOME="$TEST_DIR" \
USERPROFILE="$TEST_DIR" \
WUJI_UPDATE_REPO=DBinKv1/install \
  "$TEST_DIR/wuji" update --skills

# 5. 清理测试目录
rm -rf "$TEST_DIR"
```

**Windows (PowerShell)**

在独立的作用域中执行，避免污染当前 PowerShell 会话的环境变量：

```powershell
& {
    $TestDir = Join-Path $env:TEMP "wuji-gray-test"
    New-Item -ItemType Directory -Force -Path (Join-Path $TestDir "AppData\Local") | Out-Null
    Write-Output "TestDir=$TestDir"
    Copy-Item .\target\debug\wuji.exe (Join-Path $TestDir "wuji.exe")

    try {
        $prevUser = $env:USERPROFILE
        $prevHome = $env:HOME
        $prevRepo = $env:WUJI_UPDATE_REPO
        $prevTelem = $env:WUJI_TELEMETRY_DISABLE

        $env:USERPROFILE = $TestDir
        $env:HOME = $TestDir
        $env:WUJI_TELEMETRY_DISABLE = "1"
        $env:WUJI_UPDATE_REPO = "DBinKv1/install"

        # 执行升级并验证
        & "$TestDir\wuji.exe" update
        & "$TestDir\wuji.exe" --version

        # （可选）测试 Skills 单独同步
        & "$TestDir\wuji.exe" update --skills
    }
    finally {
        $env:USERPROFILE = $prevUser
        $env:HOME = $prevHome
        $env:WUJI_UPDATE_REPO = $prevRepo
        $env:WUJI_TELEMETRY_DISABLE = $prevTelem
        Remove-Item -Recurse -Force $TestDir
    }
}
```

> **SSH 连 Windows 时注意**：ConPTY 把粘贴内容里的换行转成 `Ctrl+Enter`。pwsh 默认把该组合键绑为 `InsertLineAbove`，所以多行粘贴会倒序，并停在续行状态。另外，PowerShell 不把 `Ctrl+D`（0x04）当作 EOF，也没有绑定该键，所以它不能退出会话。在远端 `$PROFILE` 加两行：第一行修正粘贴倒序，第二行让 `Ctrl+D` 在空行时退出。
>
> ```powershell
> if ($env:SSH_CONNECTION) { Set-PSReadLineKeyHandler -Chord Ctrl+Enter -Function AddLine }
> if ($env:SSH_CONNECTION) { Set-PSReadLineKeyHandler -Chord Ctrl+d -Function DeleteCharOrExit }
> ```

#### 方式二：装一个指向测试环境的 `wuji`

以下函数只在调用期间设置隔离主目录与灰测源，返回后自动还原。同一会话里的 `git`、`gh`、`ssh` 不受影响。适合反复执行 `wuji update`、`wuji update --skills`、`wuji --version`。

**macOS / Linux**

```bash
export WUJI_TEST_DIR=$(mktemp -d)
cp ./target/debug/wuji "$WUJI_TEST_DIR/wuji"
wuji() {
    printf '\n\033[31m[灰测] %s\033[0m\n\n' "$WUJI_TEST_DIR/wuji" >&2
    HOME="$WUJI_TEST_DIR" USERPROFILE="$WUJI_TEST_DIR" \
    WUJI_UPDATE_REPO=DBinKv1/install WUJI_TELEMETRY_DISABLE=1 \
    "$WUJI_TEST_DIR/wuji" "$@"
}
```

**Windows (PowerShell)**

```powershell
$env:WUJI_TEST_DIR = Join-Path $env:TEMP "wuji-gray-test"
New-Item -ItemType Directory -Force (Join-Path $env:WUJI_TEST_DIR "AppData\Local") | Out-Null
Copy-Item .\target\debug\wuji.exe "$env:WUJI_TEST_DIR\wuji.exe" -Force

function wuji {
    $o = @{ U = $env:USERPROFILE; H = $env:HOME }
    $env:USERPROFILE = $env:WUJI_TEST_DIR
    $env:HOME = $env:WUJI_TEST_DIR
    $env:WUJI_UPDATE_REPO = "DBinKv1/install"
    $env:WUJI_TELEMETRY_DISABLE = "1"
    Write-Host "`n[灰测] $env:WUJI_TEST_DIR\wuji.exe`n" -ForegroundColor Red
    try { & "$env:WUJI_TEST_DIR\wuji.exe" @args }
    finally {
        $env:USERPROFILE = $o.U
        $env:HOME = $o.H
        Remove-Item Env:WUJI_UPDATE_REPO, Env:WUJI_TELEMETRY_DISABLE -ErrorAction SilentlyContinue
    }
}
```

之后直接运行 `wuji update`、`wuji update --skills`、`wuji update --check`、`wuji --version`。

恢复环境：

```bash
# macOS / Linux
unset -f wuji
rm -rf "$WUJI_TEST_DIR"
unset WUJI_TEST_DIR
```

```powershell
# PowerShell
Remove-Item Function:wuji
Remove-Item Env:WUJI_TEST_DIR
Remove-Item -Recurse -Force "$env:TEMP\wuji-gray-test" -ErrorAction SilentlyContinue
```

移除函数后，`wuji` 会回到本机已安装的正式版（例如 `~/.local/bin/wuji`）。

如果用了全局 `export`，且没有保存原值，就无法回退。关闭当前终端窗口，再新开一个。在 bash 或 zsh 中执行 `exec zsh` 无效，因为新 shell 会继承已导出的 `HOME`。

---

### 3. Skills 同步说明

`wuji update --skills` 按**当前二进制自身的版本号**选择拉取目标。
- 二进制是升级后的灰测版本（如 `2077.10.26`）时，`--skills` 匹配灰测仓库的 `v2077.10.26` 标签，拉取成功。
- 用未升级的正式版（如 `2026.10.26`）执行 `WUJI_UPDATE_REPO=DBinKv1/install wuji update --skills` 时，本仓库没有 `v2026.10.26` 标签，返回 404。

---

### 4. 用仓库自带的安装脚本安装灰测版

`scripts/install-cli.sh` 与 `scripts/install-cli.ps1` 是上游原版，通过 `GITHUB_REPO` 指向灰测仓库。

**警告**：默认安装目录会覆盖已安装的正式版 `wuji`。只做验证时，用 `INSTALL_DIR` 或 `-InstallDir` 指定临时目录。

macOS / Linux：

```bash
GITHUB_REPO=DBinKv1/install sh scripts/install-cli.sh

# 指定版本与安装目录
GITHUB_REPO=DBinKv1/install VERSION=2077.10.26 INSTALL_DIR=$(mktemp -d) \
  sh scripts/install-cli.sh
```

Windows (PowerShell)：

```powershell
$env:GITHUB_REPO = "DBinKv1/install"
.\scripts\install-cli.ps1

# 指定版本与安装目录
$env:GITHUB_REPO = "DBinKv1/install"
.\scripts\install-cli.ps1 -Version 2077.10.26 -InstallDir "$env:TEMP\wuji-gray"
```

同步 Skills：

```bash
GITHUB_REPO=DBinKv1/install sh scripts/install-skills.sh
```

设置令牌：

- 用途：GitHub API 匿名配额为每小时 60 次。共享出口或 NAT 下容易耗尽。设置后为每小时 5000 次。
- 资产下载不带令牌，所以私有仓库无法用这两个脚本安装。

macOS / Linux：

```bash
export GH_TOKEN=$(gh auth token)
GITHUB_REPO=DBinKv1/install sh scripts/install-cli.sh
```

Windows (PowerShell)：

```powershell
$env:GH_TOKEN = gh auth token
.\scripts\install-cli.ps1
```

脚本按顺序读取 `GH_TOKEN`，再读 `GITHUB_TOKEN`。两个都未设置时，GitHub API 按匿名请求处理。

安装到不在 `PATH` 的目录时，`install-cli.sh` 会向 `~/.bashrc`、`~/.zshrc`、`~/.profile` 追加 PATH 行。

---

## 阶段三：测试完成清理

灰测完成后，如果需要把仓库改回私有状态：

```bash
gh repo edit DBinKv1/install --visibility private --accept-visibility-change-consequences
```

---

## 深入文档与设计细节

详细技术设计、约束条件、签名验证与自测步骤见文档：[docs/gray-release.md](docs/gray-release.md)。
