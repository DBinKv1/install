"""版本推导、版本串补丁与归档结构的单元测试。"""

import io
import tarfile
import zipfile
from pathlib import Path

import pytest

from wuji_gray.assets import GrayError, archive_member, derive_target, patch_bytes, repack, unpack, version_key


def test_year_is_replaced_by_default() -> None:
    assert derive_target("2026.10.26") == "2077.10.26"
    assert derive_target("2026.9.22") == "2077.9.22"
    assert len(derive_target("2026.9.22")) == len("2026.9.22")


def test_explicit_version_rules() -> None:
    assert derive_target("2026.10.26", "2077.12.31") == "2077.12.31"
    with pytest.raises(GrayError, match="长度不同"):
        derive_target("2026.10.26", "2077.9.22")
    with pytest.raises(GrayError, match="必须大于上游版本"):
        derive_target("2026.10.26", "2026.10.26")
    with pytest.raises(GrayError, match="不是合法 semver"):
        derive_target("latest")


def test_version_key_orders_numerically() -> None:
    assert version_key("2077.9.22") > version_key("2026.10.26")
    assert version_key("2026.9.9") < version_key("2026.10.1")


def test_patch_replaces_all_occurrences() -> None:
    data = b"A2026.10.26B2026.10.26C"
    patched, hits = patch_bytes(data, "2026.10.26", "2077.10.26")
    assert hits == 2
    assert b"2026.10.26" not in patched and len(patched) == len(data)


def test_patch_respects_boundaries() -> None:
    patched, hits = patch_bytes(b"2026.9.71 2026.9.7 12026.9.7", "2026.9.7", "2077.9.7")
    assert hits == 1
    assert b"2026.9.71" in patched and b"12026.9.7" in patched


def test_patch_rejects_length_change_and_misses() -> None:
    with pytest.raises(GrayError, match="长度不同"):
        patch_bytes(b"2026.10.26", "2026.10.26", "2077.9.22")
    with pytest.raises(GrayError, match="没有命中的版本串"):
        patch_bytes(b"nothing", "2026.10.26", "2077.10.26")


def test_archive_member_by_suffix(tmp_path: Path) -> None:
    assert archive_member(tmp_path / "a_aarch64-apple-darwin.tar.gz") == "wuji"
    assert archive_member(tmp_path / "a_x86_64-pc-windows-msvc.zip") == "wuji.exe"
    with pytest.raises(GrayError, match="不支持的归档类型"):
        archive_member(tmp_path / "a.txt")


@pytest.mark.parametrize("suffix,member", [(".tar.gz", "wuji"), (".zip", "wuji.exe")])
def test_unpack_repack_round_trip(tmp_path: Path, suffix: str, member: str) -> None:
    archive = tmp_path / f"asset{suffix}"
    if suffix == ".tar.gz":
        with tarfile.open(archive, "w:gz") as tar:
            info = tarfile.TarInfo(member)
            info.size = 8
            tar.addfile(info, io.BytesIO(b"original"))
    else:
        with zipfile.ZipFile(archive, "w") as bundle:
            bundle.writestr(member, b"original")

    binary = tmp_path / "bin"
    unpack(archive, member, binary)
    assert binary.read_bytes() == b"original"

    binary.write_bytes(b"patched")
    repack(archive, member, binary)
    unpack(archive, member, tmp_path / "bin2")
    assert (tmp_path / "bin2").read_bytes() == b"patched"


def test_unpack_rejects_extra_members(tmp_path: Path) -> None:
    archive = tmp_path / "asset.tar.gz"
    with tarfile.open(archive, "w:gz") as tar:
        for name in ("wuji", "extra"):
            info = tarfile.TarInfo(name)
            info.size = 1
            tar.addfile(info, io.BytesIO(b"x"))
    with pytest.raises(GrayError, match="要求必须只有 1 个"):
        unpack(archive, "wuji", tmp_path / "bin")
