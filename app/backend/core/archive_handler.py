#!/usr/bin/env python3
# [Flow: Step 1 (확장자 감지) -> Step 2 (안전한 경로에 압축 해제) -> Step 3 (재귀 해제) -> Step 4 (파일 목록 반환)]
import os
import shutil
import tarfile
import tempfile
import zipfile
from pathlib import Path
from typing import BinaryIO


ARCHIVE_EXTENSIONS = {".zip", ".rar", ".7z", ".tar", ".gz", ".tgz", ".bz2"}


def _is_archive(filename: str) -> bool:
    return any(filename.lower().endswith(ext) for ext in ARCHIVE_EXTENSIONS)


def _safe_extract_path(base: Path, member_name: str) -> Path:
    # Path traversal 방지: base 외부로 나가지 않도록 절대/상대 경로 정규화
    target = (base / member_name).resolve()
    base_resolved = base.resolve()
    if not str(target).startswith(str(base_resolved) + os.sep) and target != base_resolved:
        raise ValueError(f"Unsafe archive path: {member_name}")
    return target


def extract_zip(file_bytes: bytes, dest: Path) -> list[Path]:
    files: list[Path] = []
    with tempfile.NamedTemporaryFile(suffix=".zip", delete=False) as tmp:
        tmp.write(file_bytes)
        tmp_path = tmp.name
    try:
        with zipfile.ZipFile(tmp_path, "r") as zf:
            for member in zf.namelist():
                target = _safe_extract_path(dest, member)
                target.parent.mkdir(parents=True, exist_ok=True)
                if member.endswith("/"):
                    continue
                with zf.open(member) as src, open(target, "wb") as dst:
                    shutil.copyfileobj(src, dst)
                files.append(target)
    finally:
        Path(tmp_path).unlink(missing_ok=True)
    return files


def extract_rar(file_bytes: bytes, dest: Path) -> list[Path]:
    import rarfile

    files: list[Path] = []
    with tempfile.NamedTemporaryFile(suffix=".rar", delete=False) as tmp:
        tmp.write(file_bytes)
        tmp_path = tmp.name
    try:
        with rarfile.RarFile(tmp_path) as rf:
            for member in rf.infolist():
                if member.is_file():
                    target = _safe_extract_path(dest, member.filename)
                    target.parent.mkdir(parents=True, exist_ok=True)
                    rf.extract(member, dest)
                    files.append(target)
    finally:
        Path(tmp_path).unlink(missing_ok=True)
    return files


def extract_7z(file_bytes: bytes, dest: Path) -> list[Path]:
    import py7zr

    files: list[Path] = []
    with tempfile.NamedTemporaryFile(suffix=".7z", delete=False) as tmp:
        tmp.write(file_bytes)
        tmp_path = tmp.name
    try:
        with py7zr.SevenZipFile(tmp_path, mode="r") as zf:
            zf.extractall(dest)
            for root, _, filenames in os.walk(dest):
                for name in filenames:
                    files.append(Path(root) / name)
    finally:
        Path(tmp_path).unlink(missing_ok=True)
    return files


def extract_tar(file_bytes: bytes, dest: Path) -> list[Path]:
    files: list[Path] = []
    with tempfile.NamedTemporaryFile(suffix=".tar.gz", delete=False) as tmp:
        tmp.write(file_bytes)
        tmp_path = tmp.name
    try:
        with tarfile.open(tmp_path, "r:*") as tf:
            for member in tf.getmembers():
                if member.isfile():
                    target = _safe_extract_path(dest, member.name)
                    target.parent.mkdir(parents=True, exist_ok=True)
                    src = tf.extractfile(member)
                    if src:
                        with src, open(target, "wb") as dst:
                            shutil.copyfileobj(src, dst)
                    files.append(target)
    finally:
        Path(tmp_path).unlink(missing_ok=True)
    return files


EXTRACTORS = {
    ".zip": extract_zip,
    ".rar": extract_rar,
    ".7z": extract_7z,
    ".tar": extract_tar,
    ".gz": extract_tar,
    ".tgz": extract_tar,
    ".bz2": extract_tar,
}


def extract_archive(filename: str, file_bytes: bytes, dest: Path) -> list[Path]:
    ext = Path(filename).suffix.lower()
    if ext == ".gz" and filename.lower().endswith(".tar.gz"):
        ext = ".tar"
    if ext not in EXTRACTORS:
        raise ValueError(f"지원하지 않는 압축 형식입니다: {ext}")
    return EXTRACTORS[ext](file_bytes, dest)


def extract_all_recursive(filename: str, file_bytes: bytes, dest: Path) -> list[Path]:
    """압축 파일을 재귀적으로 풀어 모든 일반 파일의 경로를 반환한다."""
    files = extract_archive(filename, file_bytes, dest)
    result: list[Path] = []
    for path in files:
        if _is_archive(path.name):
            sub_dest = path.parent / f"__extracted_{path.name}"
            sub_dest.mkdir(parents=True, exist_ok=True)
            try:
                sub_files = extract_all_recursive(path.name, path.read_bytes(), sub_dest)
                result.extend(sub_files)
            except Exception as e:
                # 재귀 해제 실패한 파일은 그대로 포함
                result.append(path)
        else:
            result.append(path)
    return result


def is_archive(filename: str) -> bool:
    return _is_archive(filename)
