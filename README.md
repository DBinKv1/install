# Wuji CLI 灰测安装与更新仓库

本仓库（`DBinKv1/install`）作为 `wuji update` 的灰测源，提供高版本号（如 `2077.x.x`）的 Release 资产与配套 Skills。

---

## 阶段一：灰测仓库发版（生成灰测版本）

在对 CLI 进行升级测试之前，本仓库必须先有对应的灰测 Release 资产。

### 1. 前置条件

1. **仓库公开状态**：发版前仓库必须为 Public，否则客户端下载会返回 404（演练模式不受此限）：
   ```bash
   gh repo edit DBinKv1/install --visibility public --accept-visibility-change-consequences
   ```
2. **依赖工具**：已安装 `uv`、`gh`、`git` 以及 `rcodesign`。签名工具安装：
   ```bash
   cargo binstall -y apple-codesign
   ```
3. **工作区状态**：必须在本仓库根目录下执行，且本地 git 工作区无未提交改动。

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

> 上游资产缓存在仓库内 `tmp/cache/`，已忽略跟踪。重复发版命中缓存，不再下载。

> **注意（破坏性清理）**：脚本正式运行会**永久删除历史所有旧 Release 与旧 Tag**，并用上游最新内容完全覆盖本地 `skills/` 与 `scripts/`。

---

## 阶段二：使用灰测源验证客户端升级

灰测 Release 发布成功后，切换到 **`wuji-cli-dev` 代码仓库**进行客户端升级验证。

> **说明**：以下验证命令均在 `wuji-cli-dev` 仓库根目录下执行。若尚未构建，先执行 `cargo build` 生成 `./target/debug/wuji`。其版本号为 `2026.10.26`，低于灰测仓库的 `2077` 版本，正好用于触发升级。

### 1. 检查更新（建议隔离主目录）

`wuji update --check` 会将检查结果写入主目录下的 `~/.wuji/cli/state.json`。为避免把灰测版本写入本机真实状态文件，建议在临时主目录下检查：

```bash
HOME=$(mktemp -d) WUJI_UPDATE_REPO=DBinKv1/install ./target/debug/wuji update --check
```

输出若显示发现新版本（如 `2077.10.26`），且 Release URL 指向 `DBinKv1/install`，说明灰测通道连通正常。

---

### 2. 执行端到端升级灰测

> **警告**：
> 1. `wuji update` 执行的是**原地二进制替换**（Self-Replace）。务必将二进制拷贝到临时目录测试，切勿直接对开发目录的 `./target/debug/wuji` 执行更新。
> 2. 二进制升级成功后，`wuji` 会自动同步配套 Skills 并可能覆盖全局目录。务必严格隔离主目录。

#### macOS / Linux

```bash
# 1. 准备隔离主目录与副本二进制
TEST_DIR=$(mktemp -d)
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

#### Windows (PowerShell)

在独立的作用域中执行，避免污染当前 PowerShell 会话的环境变量：

```powershell
& {
    $TestDir = Join-Path $env:TEMP "wuji-gray-test"
    New-Item -ItemType Directory -Force -Path $TestDir | Out-Null
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

---

### 3. 关于 Skills 同步的特别说明

`wuji update --skills` 的拉取目标是由**当前运行二进制自身的版本号**决定的：
- 如果当前二进制已经是升级后的灰测版本（如 `2077.10.26`），执行 `--skills` 会匹配灰测仓库的 `v2077.10.26` 标签并成功拉取。
- 如果对未经升级的正式版 CLI（如 `2026.10.26`）执行 `WUJI_UPDATE_REPO=DBinKv1/install wuji update --skills`，因本仓库没有 `v2026.10.26` 标签，会报 404 错误。

---

## 阶段三：测试完成清理

灰测完成后，如果需要恢复仓库为私有状态：

```bash
gh repo edit DBinKv1/install --visibility private --accept-visibility-change-consequences
```

---

## 深入文档与设计细节

详细技术设计、约束条件、签名验证与自测步骤见文档：[docs/gray-release.md](docs/gray-release.md)。
