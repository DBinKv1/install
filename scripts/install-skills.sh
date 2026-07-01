#!/bin/sh
set -u

GITHUB_REPO="DBinKv1/install"

BASE_URL="https://github.com/${GITHUB_REPO}"

INSTALL_DIR="$HOME/.agents/skills"


info()  { printf "\033[36m[INFO]\033[0m %s\n" "$*"; }
warn()  { printf "\033[33m[WARN]\033[0m %s\n" "$*"; }
error() { printf "\033[31m[ERROR]\033[0m %s\n" "$*" >&2; exit 1; }
success() { printf "\033[32m[SUCCESS]\033[0m %s\n" "$*"; }

need_cmd() { command -v "$1" >/dev/null 2>&1 || error "need '$1'"; }

need_cmd git

info "downloading skills from $BASE_URL"

TMP_DIR=$(mktemp -d)
git clone "$BASE_URL" "$TMP_DIR"  || error "failed to download $BASE_URL"

mv "$TMP_DIR/install/skills/*" "$INSTALL_DIR/"  || error "failed to move skills to $INSTALL_DIR"
rm -rf "$TMP_DIR"

success "installed skills to $INSTALL_DIR"
