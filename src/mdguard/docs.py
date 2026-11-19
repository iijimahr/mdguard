"""文書の索引、相対リンク、増加上限を調べる。"""

import os
from pathlib import Path
import re

from .repository import git, git_names


# Match the UTF-8 POSIX space class used by the checks, including ideographic space.
SPACE = r" \t\r\n\v\f\u1680\u2000-\u2006\u2008-\u200a\u2028\u2029\u205f\u3000"
LINK = re.compile(rf"\]\(([^){SPACE}]+)\)")
TABLE_COMMENT = re.compile(rf"^[{SPACE}]*(?:#|$)")
ALLOW_SEPARATOR = re.compile(rf"[{SPACE}]*###[{SPACE}]*")
BLANK = re.compile(rf"[{SPACE}]*")


def read_lines(path):
    # Like the command-line tools, split only on LF and keep any preceding CR.
    with path.open(encoding="utf-8", errors="surrogateescape", newline="\n") as stream:
        return [line.removesuffix("\n") for line in stream]


def glob_paths(root, patterns):
    return {path for pattern in patterns for path in root.glob(pattern)}


def table_rows(path):
    for line in read_lines(path):
        if not TABLE_COMMENT.match(line):
            yield line


def index(root, rules, exempt=None):
    if exempt is not None and not (exempt.is_file() or exempt == Path("/dev/null")):
        raise ValueError(f"除外リスト '{exempt}' が無い")
    exclusions = [re.split(r"[ \t]+", line.lstrip(" \t"), maxsplit=1)[0]
                  for line in table_rows(exempt)] if exempt is not None else []
    excluded = set(exclusions)
    findings = []
    sizes = []
    indexes = {}
    for rule in rules:
        base = root / rule.base
        nearest = rule.index == "nearest-readme"
        fixed = None if nearest else root / rule.index
        paths = sorted(base.glob(rule.glob), key=Path.as_posix)
        paths = [path for path in paths if path != base and path != fixed
                 and not (nearest and path.name == "README.md")
                 and (rule.hidden or not any(part.startswith(".") for part in path.relative_to(base).parts))]
        sizes.append((rule.label, len(paths)))
        for path in paths:
            rel = path.relative_to(root).as_posix()
            if rel in excluded or (not nearest and not path.exists()):
                continue
            readme = fixed
            if nearest:
                parent = path.parent
                while parent != base and not (parent / "README.md").is_file():
                    parent = parent.parent
                readme = parent / "README.md"
            if readme not in indexes:
                indexes[readme] = read_lines(readme) if readme.is_file() else None
            lines = indexes[readme]
            index_name = readme.relative_to(root).as_posix()
            if nearest and lines is None:
                findings.append(f"{rel}: 索引 {index_name} が無い")
            elif not any(path.name in line for line in lines or ()):
                findings.append(f"{rel}: {index_name} に載っていない")
    for name in exclusions:
        if not (root / name).exists():
            findings.append(f"{name}: 除外リストにあるのに無い（腐った行）")
    return findings, sizes


def link_sources(root, top, include, exclude):
    if include is not None:
        paths = glob_paths(root, include)
    elif top is not None:
        result = git(root, "ls-files", "-z", "--cached")
        if result.returncode:
            raise ValueError(f"git ls-files: {os.fsdecode(result.stderr).strip()}")
        paths = {root / name for name in git_names(result) if name.endswith(".md")}
    else:
        paths = glob_paths(root, ["**/*.md"])
    paths -= glob_paths(root, exclude)
    return sorted((path for path in paths if path.is_file()), key=Path.as_posix)


def external_allowances(root, relative):
    findings = []
    allowances = []
    if relative is None or not (root / relative).is_file():
        return allowances, findings
    path = root / relative
    for line in table_rows(path):
        fields = ALLOW_SEPARATOR.split(line)
        if (len(fields) != 3 or not re.fullmatch(r"/.+/", fields[0])
                or re.search(r"/\.?\.?/|//$", fields[0])
                or not re.fullmatch(r"[0-9]+", fields[1])
                or BLANK.fullmatch(fields[2])):
            findings.append(f"{relative}: 許可表の書式（<絶対パスの頭（末尾 /）> ### <上限の数> ### <理由>）: {line}")
            continue
        prefix, cap, _ = fields
        findings.extend(f"{relative}: 許可表のパスの頭が重複: {prefix}"
                        for previous, _ in allowances if previous == prefix)
        allowances.append((prefix, cap))
    return allowances, findings


def links(root, config, top):
    boundary = top or root
    allowances, findings = external_allowances(root, config.external_allow())
    used = dict.fromkeys((prefix for prefix, _ in allowances), 0)
    for path in link_sources(root, top, *config.link_paths()):
        rel = path.relative_to(root).as_posix()
        for line in read_lines(path):
            for match in LINK.finditer(line):
                target = match[1].split("#", 1)[0]
                if not target or target.startswith(("http:", "https:", "mailto:", "/")):
                    continue
                resolved = Path(os.path.realpath(path.parent / target))
                if not resolved.is_relative_to(boundary):
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
                    if top is not None and any(
                        git(top, "check-ignore", "-q", "--", name).returncode == 0
                        for name in (str(resolved), f"{resolved}/")
                    ):
                        continue
                    findings.append(f"{rel}: {target}")
    return findings


def counts(root, metrics):
    if not metrics:
        raise ValueError("ratchet.metrics に指標を指定する")
    measured = {}
    for name, metric in metrics.items():
        count = 0
        for path in glob_paths(root, metric.paths):
            if not path.is_file() or (not metric.follow_symlinks and path.is_symlink()):
                continue
            for line in read_lines(path):
                if metric.count == "lines":
                    count += bool(metric.pattern.search(line))
                else:
                    count += sum(1 for _ in metric.pattern.finditer(line))
        measured[name] = count
    return measured


def ratchet(limits, measured):
    if not limits.is_file():
        raise ValueError(f"上限ファイル '{limits}' が無い")
    rows = {}
    for line in table_rows(limits):
        key, *fields = re.split(r"[ \t]+", line.strip(" \t"))
        rows.setdefault(key, []).append(fields[0] if fields else "")
    findings = []
    for key, count in measured.items():
        caps = rows.get(key, [])
        if not caps or caps == [""]:
            findings.append(f"{key}: 上限ファイルに行が無い（いま {count}）")
        elif len(caps) != 1 or not re.fullmatch(r"[+-]?[0-9]+", caps[0]):
            raise ValueError(f"{limits}: {key} の上限は整数を 1 つ指定する")
        elif count > int(caps[0]):
            findings.append(f"{key}: {count} が上限 {caps[0]} を越えた")
    return findings
