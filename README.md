# Wuji CLI 灰测安装与更新仓库

本仓库（`DBinKv1/install`）作为 `wuji update` 的灰测源，提供高版本号（如 `2077.x.x`）的 Release 资产与配套 Skills。

---

## 快速指引：如何指向本仓库进行灰测

> **说明**：以下第 2、3 节的验证命令需在 **`wuji-cli-dev` 代码仓库根目录**下执行。若尚未构建，请先执行 `cargo build` 生成 `./target/debug/wuji`。该 debug 二进制内置的当前版本号为 `2026.10.26`，低于灰测仓库的 `2077` 版本，正好用于触发升级。

### 1. 前置条件：切换为公开状态

灰测期间仓库必须处于公开状态。私有仓库会导致资产下载返回 404：

```bash
gh repo edit DBinKv1/install --visibility public --accept-visibility-change-consequences
```

测试完成后若需恢复私有：

```bash
gh repo edit DBinKv1/install --visibility private --accept-visibility-change-consequences
```

---

### 2. 检查更新（建议隔离主目录）

`wuji update --check` 会将检查结果写入主目录下的 `~/.wuji/cli/state.json`。为避免把灰测版本写入本机真实状态文件，建议在临时主目录下检查：

```bash
HOME=$(mktemp -d) WUJI_UPDATE_REPO=DBinKv1/install ./target/debug/wuji update --check
```

输出若显示发现新版本（如 `2077.10.26`），且 Release URL 指向 `DBinKv1/install`，说明灰测通道连通正常。

---

### 3. 执行端到端升级灰测

> **警告**：
> 1. `wuji update` 执行的是**原地二进制替换**（Self-Replace）。务必将二进制拷贝到临时目录测试，切勿直接对 `~/.local/bin/wuji` 执行更新。
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

### 4. 关于 Skills 同步的特别说明

`wuji update --skills` 的拉取目标是由**当前运行二进制自身的版本号**决定的：
- 如果当前二进制已经是升级后的灰测版本（如 `2077.10.26`），执行 `--skills` 会匹配灰测仓库的 `v2077.10.26` 标签并成功拉取。
- 如果对未经升级的正式版 CLI（如 `2026.10.26`）执行 `WUJI_UPDATE_REPO=DBinKv1/install wuji update --skills`，因本仓库没有 `v2026.10.26` 标签，会报 404 错误。

---

## 快速跟进上游新版本 Release

当 `wuji-technology/wuji-cli` 发布了新的正式版时，只需一条命令即可将本灰测仓库一键对齐跟进。

### 执行前置要求

1. **仓库公开状态**：正式发版前仓库必须为 Public，否则脚本预检会被拒绝。演练模式（`--dry-run`）不受此限。
2. **依赖工具**：需要已安装 `gh`、`git`、`python3` 以及 `rcodesign`。签名工具安装：
   ```bash
   cargo binstall -y apple-codesign
   ```
3. **工作区状态**：必须在仓库根目录执行，且本地 git 工作区无未提交改动。

### 执行发版

```bash
# 进入本仓库根目录直接执行
tools/gray_release.py
```

> **注意（破坏性清理）**：脚本正式运行会**永久删除历史所有旧 Release 与旧 Tag**，并用上游最新内容完全覆盖本地 `skills/` 与 `scripts/`。
脚本会自动执行全套流水线：
1. **自动取源**：拉取公开仓最新的正式 Release 及其全平台资产。
2. **自动升级为 2077 年超大版本**：保持月份和日期不变（如 `2026.11.10` 自动转化为 `2077.11.10`）。
3. **二进制自动打补丁与签名**：对全平台二进制完成内部版本串等长替换，并使用 `rcodesign` 为 macOS arm64 重新做 Ad-hoc 签名与校验。
4. **Skills 与脚本无缝镜像**：精确同步最新 Skills 与安装脚本，并自动改写 `metadata.version`。
5. **自动发布与旧版本清理**：在 GitHub 上打标并发布最新 Release，并彻底清理历史旧 Release 和 Tag。

如果需要自定义指定灰测版本号，支持通过 `--version` 参数显式传入（必须与上游版本等长）：

```bash
tools/gray_release.py --version 2077.11.10
```

执行前可随时通过 `--dry-run` 进行全流程无害演练：

```bash
tools/gray_release.py --dry-run
```

### 发版后自测

脚本仅自动校验 Release 标签与资产文件数量。发版完成后，建议按第 3 节在临时隔离目录下执行一次实际的端到端 `update` 升级自测。

---

## 深入文档与设计细节

详细技术设计、约束条件、签名验证与自测步骤见文档：[docs/gray-release.md](docs/gray-release.md)。

