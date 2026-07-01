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

# Append a PATH export to shell config files (.bashrc, .zshrc, .profile)
# if the install dir is not already in PATH, so it persists across sessions.
# If a previous block was commented out, PATH simply won't contain the dir in
# a fresh shell, so we just append a new block — no need to detect that case.
ensure_path() {
    # Already in PATH — nothing to persist
    case ":$PATH:" in
        *:"$INSTALL_DIR":*) return ;;
    esac

    marker="# === wuji-cli === "
    line='export PATH="$HOME/.local/bin:$PATH"'
    for rc in ".bashrc" ".zshrc" ".profile"; do
        rcfile="$HOME/$rc"
        [ -f "$rcfile" ] || continue
        echo "$marker" >> "$rcfile"
        echo "$line" >> "$rcfile"
        echo "$marker" >> "$rcfile"
    done
    info "added $INSTALL_DIR to PATH (~/.bashrc, ~/.zshrc, etc.)"
    info "run 'source ~/.bashrc' or restart your shell to apply"
}

# Detect system architecture
detect_arch() {
    arch=$(uname -m)
    case "$arch" in
        x86_64|amd64)  echo "amd64" ;;
        aarch64|arm64) echo "arm64" ;;
        *) error "unsupported arch: $arch" ;;
    esac
}

# Download file
download() {
    if command -v curl >/dev/null 2>&1; then
        curl -fL "$1" -o "$2"
    else
        wget -O "$2" "$1"
    fi
}

main() {

    # Check prerequisites
    need_cmd uname
    need_cmd mktemp
    if ! command -v curl >/dev/null 2>&1 && ! command -v wget >/dev/null 2>&1; then
        error "need curl or wget"
    fi

    # Detect architecture
    ARCH=$(detect_arch)
    URL="${BASE_URL}/${BINARY_NAME}_${VERSION}_${ARCH}"

    TMPDIR=$(mktemp -d)
    TMPFILE="$TMPDIR/$BINARY_NAME"

    info "downloading $URL to $TMPFILE"

    download "$URL" "$TMPFILE" || error "download failed, please try again later"

    # Install binary
    DEST="${INSTALL_DIR}/${BINARY_NAME}"
    mkdir -p "$INSTALL_DIR" || error "cannot create $INSTALL_DIR"
    chmod +x "$TMPFILE"

    info "installing $TMPFILE to $DEST"
    
    mv "$TMPFILE" "$DEST"
    rm -rf "$TMPDIR"

    success "wuji-cli installed to $DEST"
    success "run 'wuji --help' to get started"

    # Ensure install dir is in PATH (check before we mutate PATH below)
    ensure_path
    export PATH="$INSTALL_DIR:$PATH"
}

main