# 灰测仓库自动化方案

本仓库（`DBinKv1/install`）模拟 `wuji-technology/wuji-cli` 发版，用高版本号资产验证 `wuji update`。

> 实现：`uv run gray`，源码在 `src/wuji_gray/`。

---

## 一、核心机制

1. **版本自动升级为 2077**：默认仅将真实版本的年份替换为 `2077`，月份与日期原样保留（如 `2026.10.26` → `2077.10.26`，`2026.9.22` → `2077.9.22`）。长度天然等长，无需手动计算或传参。若显式传入 `--to`，长度必须与真实版本严格一致。
2. **Mach-O 必须重签**：macOS arm64 改动字节后内核拒绝执行（SIGKILL 137）。解包替换后必须执行 `rcodesign sign`，并校验 flags 去除了 `LINKER_SIGNED`。Linux 与 Windows 产物无需签名。
3. **隔离主目录**：`wuji update` 成功后会自动下载并同步 Skills。升级自测必须在临时 `HOME` 下执行，严禁污染本机 `~/.agents/skills`。
4. **仓库仅测试期公开**：客户端资产下载不带认证头，私有仓库返回 404。测试前由人工把仓库转为 public，脚本只检测，不自动改可见性。

---

## 二、文件布局

| 路径 | 职责 | 是否被镜像覆盖 |
|---|---|---|
| `src/wuji_gray/assets.py` | 纯文件与二进制处理：版本推导、版本串补丁、归档、签名校验、哈希 | 否 |
| `src/wuji_gray/cli.py` | 编排与入口：预检、取上游、下载、镜像、提交、发布、清理 | 否 |
| `pyproject.toml` | uv 项目定义与 `gray` 命令入口 | 否 |
| `tests/test_assets.py` | 版本推导、版本串补丁、归档结构的单元测试 | 否 |
| `tmp/cache/` | 上游资产缓存，已在 `.gitignore` 忽略 | 否 |
| `gray.json` | 记录来源 tag、目标版本、产物清单 | 否 |
| `skills/` | 上游 Skills 的副本，仅版本号不同 | 是，`--delete` 镜像 |
| `scripts/` | 上游安装脚本的副本 | 是，`--delete` 镜像 |

---

## 三、发版四阶段

入口（首次先 `uv sync`）：

```bash
uv run gray --dry-run      # 演练：下载、补丁、签名、镜像预览，不写仓库
uv run gray                # 正式发版
uv run gray --to 2077.9.22
```

### 1. 检查与取源
- 检查本地工作区干净且位于仓库根。
- 查上游 `releases/latest` 取真实 tag（必须非 draft/prerelease）。
- 目标版本默认由真实版本自动推导（年份改为 `2077`，月日不变）。若显式传入 `--to`，校验长度一致且 semver 更大。
- 下载该 release 的全部资产到临时目录。

### 2. 补丁与重签
- 逐个解包：`.tar.gz` 取 `wuji`，`.zip` 取 `wuji.exe`。
- 正则边界替换真实版本串，断言命中数 > 0 且旧串残留为 0。
- Mach-O 资产执行 `rcodesign sign`。断言 `print-signature-info` 含 `ADHOC`、不含 `LINKER_SIGNED` 且体积增大。macOS 额外执行 `codesign --verify --strict`。
- 签名校验若未通过，重签一次，仍失败则退出。
- 重新打包：保证每个归档仅含单个根级可执行文件，体积 < 256 MiB。

### 3. 镜像与提交
- `git clone` 上游 tag，用 `rsync -a --delete` 覆盖本仓 `skills/` 与 `scripts/`。
- 改写全部 `skills/*/SKILL.md` 的 `metadata.version` 为目标版本。
- 写入 `gray.json`，提交并推送到 `main`。若推送成功但后续创建 release 失败，旧 release 仍保留，可直接重跑。

### 4. 发布与验证
- 目标 tag 若已存在，先删除对应旧 release 与 tag。
- 创建 tag `v<目标版本>` 与 release（标记 latest），上传全部新资产。
- 删除历史旧 release 与旧 tag（默认全删）。
- 脚本自动校验 latest tag 与资产数量。
- 发版后人工运行升级自测（在 `wuji-cli-dev` 仓库根目录下，拷贝构建产物副本测试，避免覆盖开发构建）：

```bash
H=$(mktemp -d)
cp ./target/debug/wuji "$H/wuji"
HOME=$H USERPROFILE=$H WUJI_TELEMETRY_DISABLE=1 \
  WUJI_UPDATE_REPO=DBinKv1/install "$H/wuji" update
rm -rf "$H"
```

---

## 四、未验证项

- `rcodesign` 生成的签名在 macOS 11 至 13 上的兼容表现（本次仅在 macOS 15 / darwin 27 实测验证）。
- Linux 与 Windows 二进制补丁后的实际运行表现（当前开发机为 macOS，无法直接执行这两类产物）。

---

## 五、已定决策

| 项 | 决策 |
|---|---|
| 仓库可见性 | 仅测试期间由人工转为 public。脚本只检测，不改可见性。非 public 时正式发版拒绝执行。 |
| 旧 release 清理 | 每次发版删除其余全部 release 与 tag，只保留本次。 |
| 实现目录 | `src/wuji_gray/`，入口 `uv run gray`。 |
| 签名工具 | 全平台统一 `rcodesign`。macOS 上额外跑一次 `codesign --verify --strict` 作为断言。 |
| 依赖安装 | `cargo binstall apple-codesign`。 |
