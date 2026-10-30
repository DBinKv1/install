"""命令行入口与编排：预检、取上游、下载、镜像、提交、发布、清理。"""

import asyncio
import datetime
import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import httpx
import typer
from loguru import logger
from rich.console import Console
from rich.progress import BarColumn, DownloadColumn, Progress, TaskID, TextColumn, TransferSpeedColumn

from wuji_gray import __version__
from wuji_gray.assets import (
    GrayError,
    archive_member,
    derive_target,
    die,
    is_macho,
    patch_bytes,
    repack,
    run_cmd,
    sha256_file,
    sign_and_verify,
    unpack,
)

# logger.remove()
# logger.add(sys.stderr, level="INFO", format="<level>{level: <7}</level> {message}")

console = Console()
VERSION_LINE = re.compile(r'^(\s*version:\s*")[^"]*(")$', re.MULTILINE)
DOWNLOAD_CONCURRENCY = 4
DOWNLOAD_CHUNK = 1 << 20


class GrayRelease:
    def __init__(self, *, upstream: str, fixture: str, explicit_version: str | None, dry_run: bool) -> None:
        self.upstream = upstream
        self.fixture = fixture
        self.explicit_version = explicit_version
        self.dry_run = dry_run
        self.repo_root = self._detect_repo_root()
        self.work_dir = self.repo_root / "tmp" / "work"
        self.real = ""
        self.target = ""
        self.assets: list[dict] = []
        self.manifest: list[dict] = []

    def _detect_repo_root(self) -> Path:
        result = run_cmd(["git", "rev-parse", "--show-toplevel"], check=False)
        if result.returncode != 0:
            die("当前目录不在 git 仓库内")
        return Path(result.stdout.strip())

    def precheck(self) -> None:
        for tool in ("gh", "git", "rcodesign"):
            if not shutil.which(tool):
                hint = "，安装: cargo binstall apple-codesign" if tool == "rcodesign" else ""
                die(f"系统缺少必要工具: {tool}{hint}")
        dirty = run_cmd(["git", "status", "--porcelain", "--untracked-files=no"], cwd=self.repo_root).stdout.strip()
        if dirty:
            if not self.dry_run:
                die("git 工作区有未提交的改动，请先清理或提交")
            logger.warning("工作区有未提交改动，演练预览基于 HEAD，不含这些改动")
        visibility = run_cmd(["gh", "repo", "view", self.fixture, "--json", "visibility", "--jq", ".visibility"]).stdout
        if visibility.strip() != "PUBLIC":
            if not self.dry_run:
                die(f"仓库 {self.fixture} 当前为 {visibility.strip()}，发版前需先手动转为 public")
            logger.warning("仓库 {} 非 public，正式客户端下载会 404（演练放行）", self.fixture)

    def resolve_versions(self) -> None:
        meta = json.loads(run_cmd(["gh", "api", f"repos/{self.upstream}/releases/latest"]).stdout)
        if meta.get("draft") or meta.get("prerelease"):
            die("上游 latest release 处于 draft 或 prerelease 状态")
        self.real = meta["tag_name"].removeprefix("v")
        self.target = derive_target(self.real, self.explicit_version)
        self.assets = meta.get("assets") or []
        logger.info("上游版本 {} -> 目标版本 {}", self.real, self.target)

    @property
    def cache_dir(self) -> Path:
        return self.repo_root / "tmp" / "cache" / f"v{self.real}"

    def fetch_assets(self) -> Path:
        """资产落到仓库内 tmp/ 缓存。命中缓存则跳过下载。"""
        if not self.assets:
            die("上游 release 中未找到任何资产文件")
        cache_dir = self.cache_dir
        cache_dir.mkdir(parents=True, exist_ok=True)
        pending = []
        for asset in self.assets:
            if self._cached(cache_dir, asset):
                continue
            # 残缺或摘要不符的旧文件必须先清掉，否则续传会把新旧字节拼在一起。
            (cache_dir / asset["name"]).unlink(missing_ok=True)
            pending.append(asset)
        if not pending:
            logger.info("{} 个资产命中本地缓存 {}", len(self.assets), cache_dir)
            return cache_dir

        headers = {"Accept": "application/octet-stream"}
        token = run_cmd(["gh", "auth", "token"], check=False).stdout.strip()
        if token:
            headers["Authorization"] = f"Bearer {token}"
        columns = (
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            DownloadColumn(),
            TransferSpeedColumn(),
            TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
        )
        with Progress(*columns, console=console) as progress:
            asyncio.run(self._download_all(pending, cache_dir, headers, progress))
        for asset in self.assets:
            if not self._cached(cache_dir, asset):
                die(f"{asset['name']} 下载后校验失败（大小或 sha256 不符）")
        logger.info("已下载 {} 个资产到 {}", len(pending), cache_dir)
        return cache_dir

    @staticmethod
    def _cached(cache_dir: Path, asset: dict) -> bool:
        path = cache_dir / asset["name"]
        if not path.exists() or path.stat().st_size != asset["size"]:
            return False
        declared = (asset.get("digest") or "").removeprefix("sha256:")
        return not declared or sha256_file(path) == declared

    async def _download_all(
        self, pending: list[dict], cache_dir: Path, headers: dict[str, str], progress: Progress
    ) -> None:
        semaphore = asyncio.Semaphore(DOWNLOAD_CONCURRENCY)
        timeout = httpx.Timeout(60.0, connect=15.0)
        async with httpx.AsyncClient(follow_redirects=True, timeout=timeout) as client:
            jobs = []
            for asset in pending:
                path = cache_dir / asset["name"]
                have = path.stat().st_size if path.exists() else 0
                task = progress.add_task(asset["name"], total=asset["size"], completed=have)
                jobs.append(self._download_one(client, semaphore, headers, asset, path, task, progress))
            await asyncio.gather(*jobs)

    async def _download_one(
        self,
        client: httpx.AsyncClient,
        semaphore: asyncio.Semaphore,
        headers: dict[str, str],
        asset: dict,
        dest: Path,
        task: TaskID,
        progress: Progress,
    ) -> None:
        """断点续传加三次重试。链路中断时会从已落盘的字节继续。"""
        total = asset["size"]
        last_error = ""
        async with semaphore:
            for _ in range(3):
                have = dest.stat().st_size if dest.exists() else 0
                if have >= total:
                    return
                request_headers = dict(headers)
                if have:
                    request_headers["Range"] = f"bytes={have}-"
                try:
                    async with client.stream("GET", asset["url"], headers=request_headers) as response:
                        if have and response.status_code == 200:
                            have = 0
                            progress.update(task, completed=0)
                        else:
                            response.raise_for_status()
                        with dest.open("ab" if have else "wb") as handle:
                            async for chunk in response.aiter_bytes(DOWNLOAD_CHUNK):
                                handle.write(chunk)
                                progress.update(task, advance=len(chunk))
                except httpx.HTTPError as error:
                    last_error = str(error)
                if dest.exists() and dest.stat().st_size >= total:
                    return
        die(f"下载失败 {asset['name']}: {last_error}")

    def patch_all_assets(self, src_dir: Path) -> None:
        dst_dir = self.work_dir / "dist"
        dst_dir.mkdir(parents=True, exist_ok=True)
        for archive in sorted(path for path in src_dir.iterdir() if path.is_file()):
            self._patch_one(archive, dst_dir)
        logger.info("资产解包、补丁、重签与重新打包完成")

    def _patch_one(self, archive: Path, dst_dir: Path) -> None:
        member = archive_member(archive)
        if self.real not in archive.name:
            die(f"资产名未包含上游版本号 {self.real}: {archive.name}")
        out_path = dst_dir / archive.name.replace(self.real, self.target)

        with tempfile.TemporaryDirectory() as tmp:
            binary = Path(tmp) / member
            unpack(archive, member, binary)
            data, _ = patch_bytes(binary.read_bytes(), self.real, self.target)
            binary.write_bytes(data)
            if is_macho(binary):
                binary.chmod(0o755)
                sign_and_verify(binary)
            if sys.platform == "darwin" and "aarch64-apple-darwin" in archive.name:
                probe = run_cmd([str(binary), "--version"], check=False)
                if probe.returncode != 0 or self.target not in probe.stdout:
                    die(f"补丁后的二进制无法自报目标版本: {probe.stderr.strip()}")
            repack(out_path, member, binary)

        self.manifest.append(
            {
                "source": archive.name,
                "name": out_path.name,
                "sha256": sha256_file(out_path),
                "size": out_path.stat().st_size,
            }
        )

    def mirror_upstream(self, root: Path) -> None:
        upstream_dir = self.work_dir / "upstream"
        tag = f"v{self.real}"
        ready = False
        if (upstream_dir / ".git").exists():
            fetch = run_cmd(
                [
                    "git",
                    "-C",
                    str(upstream_dir),
                    "fetch",
                    "--quiet",
                    "--depth",
                    "1",
                    "origin",
                    f"+refs/tags/{tag}:refs/tags/{tag}",
                ],
                check=False,
            )
            if fetch.returncode == 0:
                run_cmd(["git", "-C", str(upstream_dir), "checkout", "--quiet", "--force", tag])
                logger.info("上游克隆已更新到 {}", tag)
                ready = True
            else:
                shutil.rmtree(upstream_dir, ignore_errors=True)
        if not ready:
            run_cmd(
                [
                    "git",
                    "-c",
                    "advice.detachedHead=false",
                    "clone",
                    "--quiet",
                    "--depth",
                    "1",
                    "--branch",
                    tag,
                    f"https://github.com/{self.upstream}.git",
                    str(upstream_dir),
                ]
            )
        for name in ("skills", "scripts"):
            self._mirror_dir(upstream_dir / name, root / name, name)
        self._bump_skills(root)
        logger.info("已镜像上游 skills 与 scripts 并改写 metadata.version")

    def _mirror_dir(self, src: Path, dst: Path, name: str) -> None:
        dst.mkdir(parents=True, exist_ok=True)
        if shutil.which("rsync"):
            run_cmd(["rsync", "-a", "--delete", f"{src}/", f"{dst}/"])
        else:
            shutil.rmtree(dst, ignore_errors=True)
            shutil.copytree(src, dst)
        src_count = len([path for path in src.rglob("*") if path.is_file()])
        dst_count = len([path for path in dst.rglob("*") if path.is_file()])
        if src_count != dst_count:
            die(f"镜像文件数不一致: {name} 上游 {src_count}，本地 {dst_count}")

    def _bump_skills(self, root: Path) -> None:
        skills = sorted(root.glob("skills/*/SKILL.md"))
        if not skills:
            die(f"{root}/skills 下没有找到 SKILL.md")
        for skill in skills:
            head, sep, tail = skill.read_text(encoding="utf-8").partition("\n---")
            if not sep:
                die(f"{skill} 缺少 frontmatter 结束标记")
            new_head, count = VERSION_LINE.subn(rf"\g<1>{self.target}\g<2>", head, count=1)
            if count != 1:
                die(f"{skill} 中的 metadata.version 无法定位")
            skill.write_text(new_head + sep + tail, encoding="utf-8")

    def write_gray_json(self, root: Path) -> None:
        payload = {
            "source_repo": self.upstream,
            "source_version": self.real,
            "version": self.target,
            "generated_at": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "assets": [
                {"name": item["name"], "size": item["size"], "sha256": item["sha256"]} for item in self.manifest
            ],
        }
        (root / "gray.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        logger.info("已生成 gray.json 资产清单")

    def commit_and_push(self) -> None:
        run_cmd(["git", "add", "skills", "scripts", "gray.json"], cwd=self.repo_root)
        if run_cmd(["git", "diff", "--cached", "--quiet"], cwd=self.repo_root, check=False).returncode == 0:
            logger.info("没有内容变更，跳过提交")
            return
        run_cmd(
            ["git", "commit", "-q", "-m", f"chore: sync fixture from v{self.real} as {self.target}"], cwd=self.repo_root
        )
        run_cmd(["git", "push", "-q", "origin", "HEAD"], cwd=self.repo_root)
        logger.info("已提交并推送到远程 main")

    def publish_release(self) -> None:
        tag = f"v{self.target}"
        if run_cmd(["gh", "release", "view", tag, "-R", self.fixture], check=False).returncode == 0:
            run_cmd(["gh", "release", "delete", tag, "-R", self.fixture, "--yes", "--cleanup-tag"])

        notes = self.work_dir / "notes.md"
        notes.write_text(
            f"Test fixture for `wuji update` end-to-end testing.\n\n"
            f"- Source: `{self.upstream}` release `v{self.real}`.\n"
            f"- Assets: upstream binaries with the embedded version string rewritten to `{self.target}`.\n"
            f"- macOS binaries are re-signed ad-hoc after patching.\n"
            f"- The skills content used by `wuji update --skills` lives at tag `v{self.target}`.\n",
            encoding="utf-8",
        )
        dist = self.work_dir / "dist"
        assets = [str(dist / item["name"]) for item in self.manifest]
        run_cmd(
            [
                "gh",
                "release",
                "create",
                tag,
                "-R",
                self.fixture,
                "--latest",
                "--title",
                tag,
                "--notes-file",
                str(notes),
                *assets,
            ]
        )
        logger.info("已创建 Release {}", tag)

    def prune_old_releases(self) -> None:
        keep = f"v{self.target}"
        listing = run_cmd(
            ["gh", "release", "list", "-R", self.fixture, "--limit", "100", "--json", "tagName", "--jq", ".[].tagName"]
        )
        for tag in (line.strip() for line in listing.stdout.splitlines()):
            if tag and tag != keep:
                run_cmd(["gh", "release", "delete", tag, "-R", self.fixture, "--yes", "--cleanup-tag"])
                logger.info("已删除旧 Release 与 Tag: {}", tag)

    def verify_release(self) -> None:
        expected = f"v{self.target}"
        latest = run_cmd(["gh", "api", f"repos/{self.fixture}/releases/latest", "--jq", ".tag_name"]).stdout.strip()
        if latest != expected:
            die(f"latest 校验失败: 期望 {expected}，实际 {latest}")
        remote = run_cmd(
            ["gh", "release", "view", expected, "-R", self.fixture, "--json", "assets", "--jq", ".assets | length"]
        ).stdout.strip()
        if int(remote) != len(self.manifest):
            die(f"资产数量不一致: 远程 {remote} 个，本地 {len(self.manifest)} 个")
        logger.info("校验通过：latest={}，远端 {} 个资产", expected, remote)

    def preview(self) -> None:
        preview_dir = self.work_dir / "repo-preview"
        preview_dir.mkdir(parents=True, exist_ok=True)
        archive_proc = subprocess.Popen(["git", "archive", "HEAD"], cwd=str(self.repo_root), stdout=subprocess.PIPE)
        untar_proc = subprocess.Popen(["tar", "-x", "-C", str(preview_dir)], stdin=archive_proc.stdout)
        assert archive_proc.stdout is not None
        archive_proc.stdout.close()
        untar_proc.communicate()
        if untar_proc.returncode != 0:
            die("解压 git archive 预览失败")

        self.mirror_upstream(preview_dir)
        self.write_gray_json(preview_dir)
        logger.info("[dry-run] 演练完成，预览目录 {}", preview_dir)
        logger.info("[dry-run] 将创建 Release v{}，并删除其余全部历史版本", self.target)
        for item in self.manifest:
            logger.info("[dry-run] 产物 {} ({} 字节)", item["name"], item["size"])

    def report_next_steps(self) -> None:
        """打印客户端侧的通道检查命令，隔离 HOME 避免污染。"""
        logger.info('快速检查：HOME=$(mktemp -d) WUJI_UPDATE_REPO={} ./target/debug/wuji update --check', self.fixture)

    def report_visibility(self) -> None:
        """收尾提醒仓库可见性：公开后要记得关回私有。"""
        visibility = run_cmd(
            ["gh", "repo", "view", self.fixture, "--json", "visibility", "--jq", ".visibility"]
        ).stdout.strip()
        if visibility == "PUBLIC":
            logger.warning("仓库 {} 当前 public，灰测结束后记得改回 private", self.fixture)
        else:
            logger.warning("仓库 {} 当前 {}，wuji update 下载会 404，需先转为 public", self.fixture, visibility)

    def run(self) -> int:
        self.precheck()
        self.resolve_versions()
        self.patch_all_assets(self.fetch_assets())
        logger.info("补丁产物 {}", self.work_dir / "dist")
        if self.dry_run:
            self.preview()
            self.report_visibility()
            self.report_next_steps()
            return 0
        self.mirror_upstream(self.repo_root)
        self.write_gray_json(self.repo_root)
        self.commit_and_push()
        self.publish_release()
        self.prune_old_releases()
        self.verify_release()
        self.report_visibility()
        self.report_next_steps()
        return 0


def main(
    dry_run: bool = typer.Option(False, "--dry-run", help="演练模式：下载、补丁、签名与预览，不修改仓库与远程"),
    target_version: str | None = typer.Option(None, "--to", help="显式指定目标版本号，长度必须等于上游真实版本"),
    upstream: str = typer.Option("wuji-technology/wuji-cli", envvar="GRAY_UPSTREAM_REPO", help="上游公开仓库"),
    fixture: str = typer.Option("DBinKv1/install", envvar="GRAY_FIXTURE_REPO", help="目标灰测仓库"),
    show_version: bool = typer.Option(False, "--version", is_eager=True, help="显示工具版本并退出"),
) -> None:
    """Wuji CLI 灰测仓库发版工具。"""
    if show_version:
        typer.echo(f"gray {__version__}")
        raise typer.Exit()
    runner = GrayRelease(upstream=upstream, fixture=fixture, explicit_version=target_version, dry_run=dry_run)
    try:
        code = runner.run()
    except GrayError as error:
        logger.error("{}", error)
        raise typer.Exit(code=1) from error
    if code:
        raise typer.Exit(code=code)


def run() -> None:
    typer.run(main)


if __name__ == "__main__":
    run()
