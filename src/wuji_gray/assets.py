"""文件与二进制处理：版本推导、版本串补丁、归档解包重打包、签名校验、哈希。

不依赖 gh 与 git。签名部分会起子进程调用 rcodesign 与 codesign。
"""

import hashlib
import re
import subprocess
import sys
import tarfile
import zipfile
from pathlib import Path
from typing import NoReturn

SEMVER = re.compile(r"^\d+\.\d+\.\d+$")
SIGN_FLAGS = re.compile(r"flags:\s*CodeSignatureFlags\(([^)]*)\)")
BINARY_NAMES = {".tar.gz": "wuji", ".zip": "wuji.exe"}
MAX_BINARY_SIZE = 256 * 1024 * 1024


class GrayError(Exception):
    """可预期的执行失败，由命令入口打印并返回退出码 1。"""


def die(message: str) -> NoReturn:
    raise GrayError(message)


def run_cmd(cmd: list[str], *, cwd: str | Path | None = None, check: bool = True) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(cmd, cwd=str(cwd) if cwd else None, capture_output=True, text=True, check=False)
    if check and result.returncode != 0:
        die(f"命令失败 {' '.join(cmd)}: {result.stderr.strip()}")
    return result


def version_key(version: str) -> tuple[int, int, int]:
    major, minor, patch = (int(part) for part in version.split("."))
    return major, minor, patch


def derive_target(real: str, explicit: str | None = None) -> str:
    """默认把年份换成 2077，月日不动。显式版本必须等长且合法。"""
    if not SEMVER.match(real):
        die(f"上游版本不是合法 semver: {real}")
    if explicit:
        if not SEMVER.match(explicit):
            die(f"--version 不是合法 semver: {explicit}")
        if len(explicit) != len(real):
            die(f"--version 与上游版本长度不同: {explicit}({len(explicit)}) vs {real}({len(real)})")
        target = explicit
    else:
        target = re.sub(r"^\d{4}", "2077", real)
    if len(target) != len(real):
        die(f"目标版本与上游版本长度不同: {target}({len(target)}) vs {real}({len(real)})")
    if version_key(target) <= version_key(real):
        die(f"目标版本必须大于上游版本: {target} <= {real}")
    return target


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def is_macho(path: Path) -> bool:
    return path.read_bytes()[:4] in {b"\xcf\xfa\xed\xfe", b"\xce\xfa\xed\xfe", b"\xca\xfe\xba\xbe"}


def archive_member(archive: Path) -> str:
    for suffix, member in BINARY_NAMES.items():
        if archive.name.endswith(suffix):
            return member
    die(f"不支持的归档类型: {archive.name}")


def patch_bytes(data: bytes, old: str, new: str) -> tuple[bytes, int]:
    """按边界替换版本串，返回 (新内容, 命中数)。"""
    old_b, new_b = old.encode(), new.encode()
    if len(old_b) != len(new_b):
        die(f"版本串长度不同，无法原地替换: {old} -> {new}")
    pattern = re.compile(rb"(?<![0-9.])" + re.escape(old_b) + rb"(?![0-9.])")
    hits = len(pattern.findall(data))
    if hits == 0:
        die(f"二进制内没有命中的版本串: {old}")
    patched = pattern.sub(new_b, data)
    if pattern.findall(patched):
        die(f"补丁后仍有旧版本串残留: {old}")
    if len(patched) != len(data):
        die("补丁改变了二进制长度")
    return patched, hits


def unpack(archive: Path, member: str, destination: Path) -> None:
    """解出归档内唯一的根级可执行文件。"""
    if archive.name.endswith(".tar.gz"):
        with tarfile.open(archive, "r:gz") as tar:
            members = tar.getmembers()
            if len(members) != 1:
                die(f"{archive.name} 含 {len(members)} 个成员，要求必须只有 1 个")
            entry = members[0]
            if entry.name != member or not entry.isfile():
                die(f"{archive.name} 的成员不是根级常规文件 {member}: {entry.name}")
            source = tar.extractfile(entry)
            if source is None:
                die(f"{archive.name} 无法读取成员")
            destination.write_bytes(source.read())
    else:
        with zipfile.ZipFile(archive) as bundle:
            infos = bundle.infolist()
            if len(infos) != 1:
                die(f"{archive.name} 含 {len(infos)} 个条目，要求必须只有 1 个")
            info = infos[0]
            if info.filename != member or info.is_dir():
                die(f"{archive.name} 的条目不是根级文件 {member}: {info.filename}")
            destination.write_bytes(bundle.read(info))
    if destination.stat().st_size > MAX_BINARY_SIZE:
        die(f"{member} 超过 256 MiB 限制")


def repack(archive: Path, member: str, binary: Path) -> None:
    if archive.name.endswith(".tar.gz"):
        with tarfile.open(archive, "w:gz") as tar:
            info = tarfile.TarInfo(member)
            info.size = binary.stat().st_size
            info.mode = 0o755
            with binary.open("rb") as handle:
                tar.addfile(info, handle)
    else:
        with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as bundle:
            info = zipfile.ZipInfo(member)
            info.external_attr = 0o100755 << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            bundle.writestr(info, binary.read_bytes())


def signature_flags(path: Path) -> str:
    matched = SIGN_FLAGS.search(run_cmd(["rcodesign", "print-signature-info", str(path)]).stdout)
    if not matched:
        die(f"无法解析签名 flags: {path}")
    return matched.group(1)


def sign_and_verify(path: Path) -> None:
    """ad-hoc 重签并校验，失败重试一次。"""
    before = path.stat().st_size
    last_error = ""
    for attempt in range(2):
        result = run_cmd(["rcodesign", "sign", str(path)], check=False)
        if result.returncode != 0:
            last_error = result.stderr.strip()
            continue
        flags = signature_flags(path)
        if "ADHOC" not in flags:
            last_error = f"签名缺少 ADHOC 标志: {flags}"
            continue
        # 上游二进制自带 linker-signed 签名，未重签的文件同样带 ADHOC，必须排除该标志。
        if "LINKER_SIGNED" in flags:
            last_error = f"签名仍为 linker-signed，未生效: {flags}"
            continue
        if path.stat().st_size <= before and attempt == 0:
            last_error = "重签后文件未变大"
            continue
        if sys.platform == "darwin":
            verify = run_cmd(["codesign", "--verify", "--strict", str(path)], check=False)
            if verify.returncode != 0:
                last_error = f"codesign 校验失败: {verify.stderr.strip()}"
                continue
        return
    die(f"签名失败（已重试）: {last_error}")
