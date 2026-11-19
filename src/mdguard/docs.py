"""文書の索引、相対リンク、増加上限を調べる。"""

import os
from pathlib import Path
import re

from .repository import git, git_root


EXTERNAL_ALLOW = Path("tests/doc_external_allow.txt")
# Match the UTF-8 POSIX space class used by the checks, including ideographic space.
SPACE = r" \t\r\n\v\f\u1680\u2000-\u2006\u2008-\u200a\u2028\u2029\u205f\u3000"
LINK = re.compile(rf"\]\(([^){SPACE}]+)\)")
TABLE_COMMENT = re.compile(rf"^[{SPACE}]*(?:#|$)")
ALLOW_SEPARATOR = re.compile(rf"[{SPACE}]*###[{SPACE}]*")
BLANK = re.compile(rf"[{SPACE}]*")
DATE_HEADING = re.compile(r"^#+ .*20[0-9]{2}-[0-9]{2}-[0-9]{2}")
LINE_REF = re.compile(r"[A-Za-z0-9_]\.(hpp|cpp|h|cu|py|sh|mk|c):[0-9]+")


def read_lines(path):
    # Like the command-line tools, split only on LF and keep any preceding CR.
    with path.open(encoding="utf-8", errors="surrogateescape", newline="\n") as stream:
        return [line.removesuffix("\n") for line in stream]


def entries(root, directory):
    """列挙には隠し項目も含め、ディレクトリの symlink の中はたどらない。"""
    start = root / directory
    if start.is_symlink():
        yield start
        return
    for parent, dirs, names in os.walk(start):
        yield from (Path(parent) / name for name in (*dirs, *names))


def doc_entries(root):
    paths = (path for path in entries(root, "doc")
             if path.name.endswith(".md") and path.name != "README.md")
    return sorted(paths, key=Path.as_posix)


def log_entries(root):
    directory = root / "log"
    if directory.is_dir():
        return sorted(path for path in directory.iterdir()
                      if not path.name.startswith(".") and path.name != "README.md")
    return []


def table_rows(path):
    for line in read_lines(path):
        if not TABLE_COMMENT.match(line):
            yield line


def index(root, exempt=None):
    if exempt is not None and not (exempt.is_file() or exempt == Path("/dev/null")):
        raise ValueError(f"除外リスト '{exempt}' が無い")
    exclusions = [re.split(r"[ \t]+", line.lstrip(" \t"), maxsplit=1)[0]
                  for line in table_rows(exempt)] if exempt is not None else []
    excluded = set(exclusions)
    findings = []
    for path in doc_entries(root):
        rel = path.relative_to(root).as_posix()
        if rel in excluded:
            continue
        parent = path.parent
        while parent != root / "doc" and not (parent / "README.md").is_file():
            parent = parent.parent
        readme = parent / "README.md"
        index_name = readme.relative_to(root).as_posix()
        if not readme.is_file():
            findings.append(f"{rel}: 索引 {index_name} が無い")
        elif not any(path.name in line for line in read_lines(readme)):
            findings.append(f"{rel}: {index_name} に載っていない")

    readme = root / "log/README.md"
    log_index = read_lines(readme) if readme.is_file() else []
    for path in log_entries(root):
        rel = path.relative_to(root).as_posix()
        if path.exists() and rel not in excluded and not any(path.name in line for line in log_index):
            findings.append(f"{rel}: log/README.md に載っていない")
    for name in exclusions:
        if not (root / name).exists():
            findings.append(f"{name}: 除外リストにあるのに無い（腐った行）")
    return findings


def link_sources(root):
    paths = {p for directory in ("doc", "tests") for p in entries(root, directory) if p.name.endswith(".md")}
    # Active documentation only. Closed records and archived log entries are never rescanned.
    for pattern in ("note/*.md", "note/history/*.md", "note/issues/*.md", "note/jobs/*.md",
                    "*.md", "*/README.md", "log/README.md"):
        paths.update(p for p in root.glob(pattern)
                     if not any(part.startswith(".") for part in p.relative_to(root).parts))
    return sorted((path for path in paths if path.is_file()), key=Path.as_posix)


def external_allowances(root):
    findings = []
    allowances = []
    path = root / EXTERNAL_ALLOW
    if not path.is_file():
        return allowances, findings
    for line in table_rows(path):
        fields = ALLOW_SEPARATOR.split(line)
        if (len(fields) != 3 or not re.fullmatch(r"/.+/", fields[0])
                or re.search(r"/\.?\.?/|//$", fields[0])
                or not re.fullmatch(r"[0-9]+", fields[1])
                or BLANK.fullmatch(fields[2])):
            findings.append(f"{EXTERNAL_ALLOW}: 許可表の書式（<絶対パスの頭（末尾 /）> ### <上限の数> ### <理由>）: {line}")
            continue
        prefix, cap, _ = fields
        findings.extend(f"{EXTERNAL_ALLOW}: 許可表のパスの頭が重複: {prefix}"
                        for previous, _ in allowances if previous == prefix)
        allowances.append((prefix, cap))
    return allowances, findings


def links(root):
    top = root if git_root(root) == root else root.parent
    use_ignore = git_root(top) == top
    allowances, findings = external_allowances(root)
    used = dict.fromkeys((prefix for prefix, _ in allowances), 0)
    for path in link_sources(root):
        rel = path.relative_to(root).as_posix()
        for line in read_lines(path):
            for match in LINK.finditer(line):
                target = match[1].split("#", 1)[0]
                if not target or target.startswith(("http:", "https:", "mailto:", "/")):
                    continue
                resolved = Path(os.path.realpath(path.parent / target))
                if not resolved.is_relative_to(top):
                    for prefix, cap in allowances:
                        if str(resolved).startswith(prefix):
                            used[prefix] += 1
                            if used[prefix] > int(cap):
                                findings.append(f"{rel}: {target}: リポジトリ外への相対リンク（{prefix} の上限 {cap} を越えた）")
                            break
                    else:
                        findings.append(f"{rel}: {target}: リポジトリ外への相対リンク（未許可: {resolved}）")
                elif not resolved.exists():
                    # A missing ignored directory needs a second lookup with a trailing slash.
                    if use_ignore and any(
                        git(top, "check-ignore", "-q", "--", name).returncode == 0
                        for name in (str(resolved), f"{resolved}/")
                    ):
                        continue
                    findings.append(f"{rel}: {target}")
    return findings


def counts(root):
    dates = refs = 0
    for path in entries(root, "doc"):
        if not path.name.endswith(".md") or path.is_symlink() or not path.is_file():
            continue
        for line in read_lines(path):
            dates += bool(DATE_HEADING.search(line))
            refs += len(LINE_REF.findall(line))
    spec = root / "note/spec.md"
    long_lines = sum(len(line) >= 401 for line in read_lines(spec)) if spec.is_file() else 0
    return {"date_headings": dates, "spec_long_lines": long_lines, "line_refs": refs}


def ratchet(root, limits, measured=None):
    if not limits.is_file():
        raise ValueError(f"上限ファイル '{limits}' が無い")
    rows = {}
    for line in table_rows(limits):
        key, *fields = re.split(r"[ \t]+", line.strip(" \t"))
        rows.setdefault(key, []).append(fields[0] if fields else "")
    findings = []
    for key, count in (counts(root) if measured is None else measured).items():
        caps = rows.get(key, [])
        if not caps or caps == [""]:
            findings.append(f"{key}: 上限ファイルに行が無い（いま {count}）")
        elif len(caps) != 1 or not re.fullmatch(r"[+-]?[0-9]+", caps[0]):
            raise ValueError(f"{limits}: {key} の上限は整数を 1 つ指定する")
        elif count > int(caps[0]):
            findings.append(f"{key}: {count} が上限 {caps[0]} を越えた")
    return findings
