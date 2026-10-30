#!/usr/bin/env python3
"""灰测仓库全流程自动化脚本。

取代原 bash + python 双层架构，单文件完成：
1. 预检（环境依赖、git 状态、仓库可见性）
2. 查上游 latest release，自动推导 2077 年超大版本（月日保留）
3. 下载全平台资产
4. 解包、正则边界原地补丁、rcodesign 重签、合法性校验、重打包
5. 镜像上游 tag 的 skills/ 与 scripts/，批量改写 metadata.version
6. 写入 gray.json
7. 提交、推送、创建 GitHub Release、全量删除旧 release 与 tag
8. 校验最新发布状态与资产数量
"""

from __future__ import annotations

import argparse
import datetime
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path

SEMVER = re.compile(r"^\d+\.\d+\.\d+$")
MAX_BINARY_SIZE = 256 * 1024 * 1024
SIGN_FLAGS = re.compile(r"flags:\s*CodeSignatureFlags\(([^)]*)\)")
BINARY_NAMES = {".tar.gz": "wuji", ".zip": "wuji.exe"}


class Fail(Exception):
    """可预期的执行失败，直接打印并以退出码 1 退出。"""


def die(message: str) -> None:
    raise Fail(message)


def run_cmd(
    cmd: list[str],
    *,
    cwd: Path | None = None,
    check: bool = True,
    capture: bool = True,
) -> subprocess.CompletedProcess[str]:
    """统一命令行调用封装。"""
    res = subprocess.run(
        cmd,
        cwd=str(cwd) if cwd else None,
        capture_output=capture,
        text=True,
    )
    if check and res.returncode != 0:
        err = res.stderr.strip() if capture else f"exit {res.returncode}"
        die(f"命令失败 {' '.join(cmd)}: {err}")
    return res


# ---------------------------------------------------------------- 版本推导


def derive_target(real: str, explicit: str | None) -> str:
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


def version_key(version: str) -> tuple[int, int, int]:
    major, minor, patch = (int(part) for part in version.split("."))
    return major, minor, patch


# ---------------------------------------------------------------- 二进制补丁与签名


def patch_bytes(data: bytes, old: str, new: str) -> tuple[bytes, int]:
    """按边界替换版本串。返回 (新内容, 命中数)。"""
    old_b, new_b = old.encode(), new.encode()
    if len(old_b) != len(new_b):
        die(f"版本串长度不同，无法原地替换: {old} -> {new}")
    pattern = re.compile(rb"(?<![0-9.])" + re.escape(old_b) + rb"(?![0-9.])")
    hits = len(pattern.findall(data))
    if hits == 0:
        die(f"二进制内没有命中的版本串: {old}")
    patched = pattern.sub(new_b, data)
    if len(pattern.findall(patched)) != 0:
        die(f"补丁后仍有旧版本串残留: {old}")
    if len(patched) != len(data):
        die("补丁改变了二进制长度")
    return patched, hits


def is_macho(path: Path) -> bool:
    magic = path.read_bytes()[:4]
    return magic in {b"\xcf\xfa\xed\xfe", b"\xce\xfa\xed\xfe", b"\xca\xfe\xba\xbe"}


def signature_flags(path: Path) -> str:
    res = run_cmd(["rcodesign", "print-signature-info", str(path)])
    matched = SIGN_FLAGS.search(res.stdout)
    if not matched:
        die(f"无法解析签名 flags: {path}")
    return matched.group(1)


def sign_and_verify(path: Path) -> None:
    """ad-hoc 重签并校验。失败自动重试一次。"""
    before = path.stat().st_size
    last_error = ""
    for attempt in range(2):
        res = run_cmd(["rcodesign", "sign", str(path)], check=False)
        if res.returncode != 0:
            last_error = res.stderr.strip()
            continue
        flags = signature_flags(path)
        if "ADHOC" not in flags:
            last_error = f"签名缺少 ADHOC 标志: {flags}"
            continue
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


def unpack(archive: Path, member: str, destination: Path) -> None:
    if archive.name.endswith(".tar.gz"):
        with tarfile.open(archive, "r:gz") as tar:
            members = [m for m in tar.getmembers()]
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
            if len(bundle.infolist()) != 1:
                die(f"{archive.name} 含 {len(bundle.infolist())} 个条目，要求必须只有 1 个")
            info = bundle.infolist()[0]
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


def archive_member(archive: Path) -> str:
    for suffix, member in BINARY_NAMES.items():
        if archive.name.endswith(suffix):
            return member
    die(f"不支持的归档类型: {archive.name}")


def sha256_file(path: Path) -> str:
    import hashlib

    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


# ---------------------------------------------------------------- 编排工作流


class GrayRelease:
    def __init__(
        self,
        repo_root: Path,
        upstream: str,
        fixture: str,
        explicit_version: str | None,
        dry_run: bool,
    ) -> None:
        self.repo_root = repo_root
        self.upstream = upstream
        self.fixture = fixture
        self.explicit_version = explicit_version
        self.dry_run = dry_run
        self.work_dir = Path(tempfile.mkdtemp(prefix="wuji-gray-"))

    def cleanup(self) -> None:
        if self.work_dir.exists():
            shutil.rmtree(self.work_dir, ignore_errors=True)

    def log(self, msg: str) -> None:
        print(f"\033[36m[INFO]\033[0m {msg}")

    def warn(self, msg: str) -> None:
        print(f"\033[33m[WARN]\033[0m {msg}")

    def precheck(self) -> None:
        if Path.cwd().resolve() != self.repo_root.resolve():
            die("必须在仓库根目录执行")
        status = run_cmd(["git", "status", "--porcelain", "--untracked-files=no"], cwd=self.repo_root).stdout
        if status.strip():
            die("git 工作区有未提交的改动，请先清理或提交")
        for tool in ("gh", "git", "python3", "rcodesign"):
            if not shutil.which(tool):
                die(f"系统缺少必要工具: {tool}")

        vis_res = run_cmd(["gh", "repo", "view", self.fixture, "--json", "visibility", "--jq", ".visibility"])
        vis = vis_res.stdout.strip()
        if vis != "PUBLIC":
            if self.dry_run:
                self.warn(f"仓库 {self.fixture} 当前为 {vis}，正式客户端下载资产会报 404（演练模式放行）")
            else:
                die(f"仓库 {self.fixture} 当前为 {vis}，发版前需先手动转为 public")

    def resolve_versions(self) -> tuple[str, str]:
        meta_res = run_cmd(["gh", "api", f"repos/{self.upstream}/releases/latest"])
        meta = json.loads(meta_res.stdout)
        if meta.get("draft"):
            die("上游 latest release 处于 draft 状态")
        if meta.get("prerelease"):
            die("上游 latest release 处于 prerelease 状态")
        real = meta["tag_name"].removeprefix("v")
        target = derive_target(real, self.explicit_version)
        self.log(f"上游版本 {real} -> 目标版本 {target}")
        return real, target

    def fetch_assets(self, real: str) -> Path:
        src_dir = self.work_dir / "src"
        src_dir.mkdir(parents=True, exist_ok=True)
        self.log("下载上游资产中...")
        run_cmd(["gh", "release", "download", f"v{real}", "-R", self.upstream, "-D", str(src_dir), "--clobber"])
        assets = [f for f in src_dir.iterdir() if f.is_file()]
        if not assets:
            die("上游 release 中未找到任何资产文件")
        self.log(f"已下载 {len(assets)} 个上游资产")
        return src_dir

    def patch_all_assets(self, src_dir: Path, real: str, target: str) -> list[dict]:
        dst_dir = self.work_dir / "dist"
        dst_dir.mkdir(parents=True, exist_ok=True)
        manifest = []
        for archive in sorted(src_dir.iterdir()):
            if not archive.is_file():
                continue
            member = archive_member(archive)
            if real not in archive.name:
                die(f"资产名未包含上游版本号 {real}: {archive.name}")
            out_name = archive.name.replace(real, target)
            out_path = dst_dir / out_name

            with tempfile.TemporaryDirectory() as tmp:
                binary = Path(tmp) / member
                unpack(archive, member, binary)
                data, hits = patch_bytes(binary.read_bytes(), real, target)
                binary.write_bytes(data)

                if is_macho(binary):
                    binary.chmod(0o755)
                    sign_and_verify(binary)

                if sys.platform == "darwin" and "aarch64-apple-darwin" in archive.name:
                    probe = run_cmd([str(binary), "--version"], check=False)
                    if probe.returncode != 0 or target not in probe.stdout:
                        die(f"补丁后的二进制无法自报目标版本: {probe.stderr.strip()}")

                repack(out_path, member, binary)

            manifest.append({
                "source": archive.name,
                "name": out_name,
                "sha256": sha256_file(out_path),
                "size": out_path.stat().st_size,
            })

        self.log("资产解包、补丁、重签与重新打包已全部完成")
        return manifest

    def mirror_upstream(self, root: Path, real: str, target: str) -> None:
        upstream_dir = self.work_dir / "upstream"
        run_cmd([
            "git", "-c", "advice.detachedHead=false", "clone", "--quiet",
            "--depth", "1", "--branch", f"v{real}",
            f"https://github.com/{self.upstream}.git", str(upstream_dir)
        ])

        for d in ("skills", "scripts"):
            src_sub = upstream_dir / d
            dst_sub = root / d
            dst_sub.mkdir(parents=True, exist_ok=True)
            if shutil.which("rsync"):
                run_cmd(["rsync", "-a", "--delete", f"{src_sub}/", f"{dst_sub}/"])
            else:
                shutil.rmtree(dst_sub, ignore_errors=True)
                shutil.copytree(src_sub, dst_sub)

            src_count = len([f for f in src_sub.rglob("*") if f.is_file()])
            dst_count = len([f for f in dst_sub.rglob("*") if f.is_file()])
            if src_count != dst_count:
                die(f"镜像文件数不一致: {d} 上游 {src_count}，本地 {dst_count}")

        # 批量改写 skills/*/SKILL.md 内的 metadata.version
        skills = sorted(root.glob("skills/*/SKILL.md"))
        if not skills:
            die(f"{root}/skills 下没有找到 SKILL.md")
        pattern = re.compile(r'^(\s*version:\s*")[^"]*(")$', re.M)
        for skill in skills:
            text = skill.read_text(encoding="utf-8")
            head, sep, tail = text.partition("\n---")
            if not sep:
                die(f"{skill} 缺少 frontmatter 结束标记")
            new_head, count = pattern.subn(rf"\g<1>{target}\g<2>", head, count=1)
            if count != 1:
                die(f"{skill} 中的 metadata.version 无法定位")
            skill.write_text(new_head + sep + tail, encoding="utf-8")

        self.log("已镜像上游 skills 与 scripts 并批量改写 metadata.version")

    def write_gray_json(self, root: Path, real: str, target: str, manifest: list[dict]) -> None:
        payload = {
            "source_repo": self.upstream,
            "source_version": real,
            "version": target,
            "generated_at": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "assets": [
                {"name": m["name"], "size": m["size"], "sha256": m["sha256"]}
                for m in manifest
            ],
        }
        (root / "gray.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        self.log("已生成 gray.json 资产清单")

    def commit_and_push(self, real: str, target: str) -> None:
        run_cmd(["git", "add", "skills", "scripts", "gray.json"], cwd=self.repo_root)
        diff = run_cmd(["git", "diff", "--cached", "--quiet"], cwd=self.repo_root, check=False)
        if diff.returncode == 0:
            self.log("没有内容变更，跳过提交")
            return
        run_cmd(["git", "commit", "-q", "-m", f"chore: sync fixture from v{real} as {target}"], cwd=self.repo_root)
        run_cmd(["git", "push", "-q", "origin", "HEAD"], cwd=self.repo_root)
        self.log("已提交本地改动并推送到远程 main")

    def publish_release(self, real: str, target: str) -> None:
        tag = f"v{target}"
        chk = run_cmd(["gh", "release", "view", tag, "-R", self.fixture], check=False)
        if chk.returncode == 0:
            run_cmd(["gh", "release", "delete", tag, "-R", self.fixture, "--yes", "--cleanup-tag"])

        notes_path = self.work_dir / "notes.md"
        notes_content = (
            f"Test fixture for `wuji update` end-to-end testing.\n\n"
            f"- Source: `{self.upstream}` release `v{real}`.\n"
            f"- Assets: upstream binaries with the embedded version string rewritten to `{target}`.\n"
            f"- macOS binaries are re-signed ad-hoc after patching.\n"
            f"- The skills content used by `wuji update --skills` lives at tag `v{target}`.\n"
        )
        notes_path.write_text(notes_content, encoding="utf-8")

        dist_files = [str(f) for f in (self.work_dir / "dist").iterdir() if f.is_file()]
        run_cmd([
            "gh", "release", "create", tag, "-R", self.fixture,
            "--latest", "--title", tag, "--notes-file", str(notes_path),
            *dist_files
        ])
        self.log(f"已创建新 Release {tag}")

    def prune_old_releases(self, target: str) -> None:
        keep = f"v{target}"
        res = run_cmd(["gh", "release", "list", "-R", self.fixture, "--limit", "100", "--json", "tagName", "--jq", ".[].tagName"])
        for tag in res.stdout.splitlines():
            tag = tag.strip()
            if not tag or tag == keep:
                continue
            run_cmd(["gh", "release", "delete", tag, "-R", self.fixture, "--yes", "--cleanup-tag"])
            self.log(f"已删除旧 Release 与 Tag: {tag}")

    def verify_release(self, target: str, manifest: list[dict]) -> None:
        expected = f"v{target}"
        latest = run_cmd(["gh", "api", f"repos/{self.fixture}/releases/latest", "--jq", ".tag_name"]).stdout.strip()
        if latest != expected:
            die(f"latest 校验失败: 期望 {expected}，实际 {latest}")
        remote_cnt = int(run_cmd(["gh", "release", "view", expected, "-R", self.fixture, "--json", "assets", "--jq", ".assets | length"]).stdout.strip())
        if remote_cnt != len(manifest):
            die(f"资产数量不一致: 远程 {remote_cnt} 个，本地 {len(manifest)} 个")
        self.log(f"发版校验通过：latest={expected}，远端包含 {remote_cnt} 个资产")

    def run_dry_run_preview(self, real: str, target: str, manifest: list[dict]) -> None:
        preview = self.work_dir / "repo-preview"
        preview.mkdir(parents=True, exist_ok=True)
        # 导出本地工作区副本进行镜像预览
        archive_proc = subprocess.Popen(["git", "archive", "HEAD"], cwd=str(self.repo_root), stdout=subprocess.PIPE)
        untar_proc = subprocess.Popen(["tar", "-x", "-C", str(preview)], stdin=archive_proc.stdout)
        archive_proc.stdout.close()
        untar_proc.communicate()
        if untar_proc.returncode != 0:
            die("解压 git archive 预览失败")

        self.mirror_upstream(preview, real, target)
        self.write_gray_json(preview, real, target, manifest)

        self.log(f"[dry-run] 演练完成！临时预览目录: {preview}")
        self.log(f"[dry-run] 将创建 Release v{target}，并删除其他全部历史版本")
        for m in manifest:
            self.log(f"[dry-run] 产物资产: {m['name']} ({m['size']} 字节, sha256: {m['sha256'][:12]}...)")


def main() -> int:
    parser = argparse.ArgumentParser(description="Wuji CLI 灰测发版自动化编排工具")
    parser.add_argument("--dry-run", action="store_true", help="演练模式：执行拉取、补丁、重签与预览，不修改远程与本地代码")
    parser.add_argument("--version", help="显式指定目标版本号（长度必须严格等于上游真实版本）")
    parser.add_argument("--upstream", default=os.getenv("GRAY_UPSTREAM_REPO", "wuji-technology/wuji-cli"), help="上游公开仓库")
    parser.add_argument("--fixture", default=os.getenv("GRAY_FIXTURE_REPO", "DBinKv1/install"), help="目标灰测仓库")

    args = parser.parse_args()
    repo_root = Path(__file__).resolve().parent.parent

    runner = GrayRelease(
        repo_root=repo_root,
        upstream=args.upstream,
        fixture=args.fixture,
        explicit_version=args.version,
        dry_run=args.dry_run,
    )

    try:
        runner.precheck()
        real, target = runner.resolve_versions()
        src_dir = runner.fetch_assets(real)
        manifest = runner.patch_all_assets(src_dir, real, target)

        if args.dry_run:
            runner.run_dry_run_preview(real, target, manifest)
            return 0

        runner.mirror_upstream(runner.repo_root, real, target)
        runner.write_gray_json(runner.repo_root, real, target, manifest)
        runner.commit_and_push(real, target)
        runner.publish_release(real, target)
        runner.prune_old_releases(target)
        runner.verify_release(target, manifest)

    except Fail as error:
        print(f"\033[31m[ERROR]\033[0m {error}", file=sys.stderr)
        return 1
    finally:
        runner.cleanup()

    return 0


if __name__ == "__main__":
    import io
    sys.exit(main())
