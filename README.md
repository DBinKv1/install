# wuji CLI 安装

一键安装 [`wuji-cli`](../wuji-cli-dev) 到用户级目录（`~/.local/bin`），无需 `sudo`。

## 一键安装

```bash
curl -fsSL https://s3.click.diy/wuji-cli/install.sh | bash
```

脚本会自动：
1. 检测 CPU 架构（amd64 / arm64）
2. 从 S3 下载对应二进制文件
3. 安装到 `$HOME/.local/bin/wuji`

> 该目录也是 uv 的安装位置。如果 `$HOME/.local/bin` 不在 `PATH` 中，脚本会给出提示。

## 手动下载

| 架构 | 下载链接 |
|------|---------|
| amd64 | `https://s3.click.diy/wuji-cli/v0.1.0-rc.6/wuji_0.1.0-rc.6_amd64` |
| arm64 | `https://s3.click.diy/wuji-cli/v0.1.0-rc.6/wuji_0.1.0-rc.6_arm64` |

下载后赋权即可：

```bash
chmod +x wuji_0.1.0-rc.6_amd64
mv wuji_0.1.0-rc.6_amd64 ~/.local/bin/wuji
```

下载并安装 `wuji` 到 `$XDG_BIN_HOME`（未设置时为 `~/.local/bin`），自动检测平台架构。

## 支持平台

| 架构 | 下载文件 |
| --- | --- |
| x86_64 / amd64 | `wuji_0.1.0-rc.6_amd64` |
| aarch64 / arm64 | `wuji_0.1.0-rc.6_arm64` |

其他架构暂不支持预编译二进制。

## 本地安装

```sh
sh ./install.sh
```

## 安装后

若 `~/.local/bin` 不在 `PATH` 中，将其加入 shell 配置（`~/.bashrc` / `~/.zshrc`）：

```sh
export PATH="$HOME/.local/bin:$PATH"
```

然后验证：

```sh
wuji --version
```