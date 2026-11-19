"""Git の作業ツリーにある Markdown を列挙する。"""

import os
from pathlib import Path
import subprocess


def git(root, *args):
    command = ["git", "-C", root, *args]
    try:
        return subprocess.run(command, capture_output=True, check=False)
    except FileNotFoundError as exc:
        return subprocess.CompletedProcess(command, 127, b"", os.fsencode(str(exc)))


def git_root(start):
    result = git(start, "rev-parse", "--show-toplevel")
    if result.returncode == 0:
        return Path(os.fsdecode(result.stdout.rstrip(b"\n"))).resolve()
    return None


def git_names(result):
    return [os.fsdecode(name) for name in result.stdout.split(b"\0") if name]


def repo_files(root, patterns, under=None):
    """設定の Git pathspec に一致するファイルをリポジトリルート相対で返す。"""
    if root is None:
        raise ValueError("--repo: git の木の中で呼ぶ")
    if not patterns:
        raise ValueError("--repo: 設定に math.paths が必要")
    directory = Path(under or ".")
    if directory.is_absolute() or ".." in directory.parts:
        raise ValueError("--under: Git の根からの相対ディレクトリを指定する")

    result = git(root, "ls-files", "-z", "--cached", "--others", "--exclude-standard", "--", *patterns)
    if result.returncode:
        raise ValueError(f"--repo: git ls-files が落ちた（{os.fsdecode(result.stderr).strip()}）")
    names = sorted({
        name for name in git_names(result)
        if name.endswith(".md") and directory in Path(name).parents
        # Index entries for removed files survive until the deletion is staged.
        and os.path.lexists(root / name)
    })
    if not names:
        suffix = f"（--under {under}）" if under else ""
        raise ValueError(f"--repo: 対象の md が 0 本{suffix}")
    return names


def named_files(paths, cwd):
    for arg in paths:
        if arg == "-":
            yield "-", None
            continue
        path = cwd / arg
        if path.is_dir():
            result = git(cwd, "ls-files", "-z", "--cached", "--others", "--exclude-standard", "--", arg)
            if result.returncode == 0:
                names = {cwd / name for name in git_names(result)}
            else:
                names = {Path(directory) / name for directory, _, files in os.walk(path) for name in files}
            for name in sorted(names, key=Path.as_posix):
                if name.name.endswith(".md"):
                    yield os.path.relpath(name, cwd), name
        else:
            yield os.path.relpath(path, cwd), path
