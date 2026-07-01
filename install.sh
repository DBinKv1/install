#!/bin/sh
set -u

VERSION="0.1.0-rc.6"
GITHUB_REPO="DBinKv1/install"

# BASE_URL="https://github.com/${GITHUB_REPO}/releases/download/v${VERSION}"
BASE_URL="https://s3.click.diy/wuji-cli/v${VERSION}"

BINARY_NAME="wuji"
INSTALL_DIR="$HOME/.local/bin"

info()  { printf "\033[36m[INFO]\033[0m %s\n" "$*"; }
warn()  { printf "\033[33m[WARN]\033[0m %s\n" "$*"; }
error() { printf "\033[31m[ERROR]\033[0m %s\n" "$*" >&2; exit 1; }
success() { printf "\033[32m[SUCCESS]\033[0m %s\n" "$*"; }

need_cmd() { command -v "$1" >/dev/null 2>&1 || error "need '$1'"; }

# Check if install dir is in PATH, warn if not
check_path() {
    case ":$PATH:" in
        *:"$1":*) ;;
        *)
            warn "$1 is not in PATH, add 'export PATH=\"$1:\$PATH\"' to your shell config (~/.bashrc, ~/.zshrc, etc.)"
            ;;
    esac
}

# 检测架构
detect_arch() {
    arch=$(uname -m)
    case "$arch" in
        x86_64|amd64)  echo "amd64" ;;
        aarch64|arm64) echo "arm64" ;;
        *) error "unsupported arch: $arch" ;;
    esac
}

# 下载文件
download() {
    if command -v curl >/dev/null 2>&1; then
        # curl -sSfL "$1" -o "$2"  # 无进度条
        curl -fL "$1" -o "$2"
    else
        # wget -qO "$2" "$1"  # 无进度条
        wget -O "$2" "$1"
    fi
}

main() {

    # 检查环境
    need_cmd uname
    need_cmd mktemp
    if ! command -v curl >/dev/null 2>&1 && ! command -v wget >/dev/null 2>&1; then
        error "need curl or wget"
    fi

    # 检测架构
    ARCH=$(detect_arch)
    URL="${BASE_URL}/${BINARY_NAME}_${VERSION}_${ARCH}"

    TMPDIR=$(mktemp -d)
    TMPFILE="$TMPDIR/$BINARY_NAME"

    info "downloading $URL to $TMPFILE"

    download "$URL" "$TMPFILE" || error "download failed"

    # 安装
    DEST="${INSTALL_DIR}/${BINARY_NAME}"
    mkdir -p "$INSTALL_DIR" || error "cannot create $INSTALL_DIR"
    chmod +x "$TMPFILE"

    info "installing $TMPFILE to $DEST"
    
    mv "$TMPFILE" "$DEST"
    rm -rf "$TMPDIR"

    success "wuji-cli installed to $DEST"
    success "run 'wuji --help' to get started"

    # 检查 PATH 是否包含安装目录
    check_path "$INSTALL_DIR"
}

main