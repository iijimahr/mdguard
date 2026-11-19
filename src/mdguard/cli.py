"""mdguard のコマンドライン。"""

import argparse
from contextlib import redirect_stderr, redirect_stdout
import io
import os
from pathlib import Path
import sys
from urllib.error import URLError

from . import docs, math
from .config import load_config
from .repository import git_root, named_files, repo_files


def parser():
    cli = argparse.ArgumentParser(prog="mdguard", description="Markdown 文書を検査する")
    cli.add_argument("--config", metavar="FILE", help="設定ファイルを指定する")
    sub = cli.add_subparsers(dest="command", required=True)

    def command(name, help_text):
        ap = sub.add_parser(name, help=help_text)
        ap.add_argument("--config", metavar="FILE", default=argparse.SUPPRESS)
        return ap

    ap = command("math", "GitHub で壊れる数式を検査する")
    ap.add_argument("paths", nargs="*", metavar="FILES")
    ap.add_argument("--ignore", default="", help="外す規則（カンマ区切り、例: M13,M5）")
    ap.add_argument("--select", default="", help="この規則だけ見る")
    ap.add_argument("--selftest", action="store_true", help="記録した GitHub の結果と突き合わせる")
    ap.add_argument("--verify-github", action="store_true", help="GitHub の API に投げ直して突き合わせる")
    ap.add_argument("--summary", action="store_true", help="規則ごとの件数だけ出す")
    ap.add_argument("--repo", action="store_true", help="設定の math.paths を検査する")
    ap.add_argument("--under", metavar="DIR", help="--repo の対象をこのディレクトリの下に絞る")
    ap.add_argument("--list", action="store_true", help="検査対象のパスを出す")

    for name, help_text in [
        ("index", "索引の掲載漏れを調べる"),
        ("links", "相対リンクの行き先を調べる"),
        ("ratchet", "文書の数値が上限以内か調べる"),
        ("run", "文書検査をまとめて実行する"),
    ]:
        ap = command(name, help_text)
        ap.add_argument("root", metavar="ROOT")
        if name in ("index", "run"):
            ap.add_argument("--exempt", metavar="FILE")
        if name == "ratchet":
            ap.add_argument("limits", nargs="?", metavar="LIMITS")
        if name == "run":
            ap.add_argument("--name", metavar="NAME")
            ap.add_argument("--ratchet", metavar="FILE")
            ap.add_argument("--math-under", metavar="DIR")
    command("selftest", "種の木と数式の例で検査器を試す")
    return cli


def math_command(args, cwd):
    if args.selftest or args.verify_github:
        try:
            return math.run_cases(args.verify_github)
        except (URLError, TimeoutError) as exc:
            print(f"GitHub の Markdown API: {exc}", file=sys.stderr)
            return 1
    if args.under is not None and not args.repo:
        raise ValueError("--under は --repo と一緒に")
    if args.repo and args.paths:
        raise ValueError("--repo とファイルは一緒に渡さない")
    if not args.repo and not args.paths:
        raise ValueError("検査するファイルかディレクトリを渡す")
    if args.repo:
        top = git_root(cwd)
        config = load_config(cwd, top, args.config)
        try:
            patterns = config.get("math", "paths", list)
            if patterns is None and top is not None and args.config is None:
                patterns = load_config(top, top).get("math", "paths", list)
            names = repo_files(top, patterns, args.under)
        except ValueError as exc:
            print(exc, file=sys.stderr)
            return 1
        if args.list:
            print(*names, sep="\n")
            return 0
        inputs = ((os.path.relpath(top / name, cwd), top / name) for name in names)
    else:
        inputs = named_files(args.paths, cwd)
        if args.list:
            print_lines(name for name, _ in inputs)
            return 0
    return math.check(inputs, ignore=args.ignore, select=args.select, summary=args.summary)


def selected_path(arg, config, key):
    if arg == "-":
        return None
    return Path(arg) if arg is not None else config.run_path(key)


def print_lines(lines):
    for line in lines:
        print(line)


def run(root, name, exempt, limits, under, config, top, explicit_config):
    rc = 0

    def ng(message, details, hint):
        nonlocal rc
        print(f"NG  {message}")
        print_lines(f"    {line}" for line in details[:10])
        print(f"    {hint}")
        rc = 1

    def find(check, *args):
        try:
            return check(root, *args)
        except (OSError, ValueError) as exc:
            return [f"mdguard が落ちた: {exc}"]

    findings = find(docs.index, exempt)
    if findings:
        ng(f"文書の索引の点呼（{name}）が合わない（{len(findings)} 件）", findings,
           f"→ 新しい doc / log は README.md の表に 1 行足すこと（載せないなら除外リスト {exempt or '/dev/null'} に理由つきで 1 行）")
    else:
        nd, nl = len(docs.doc_entries(root)), len(docs.log_entries(root))
        print(f"OK  文書の索引の点呼（{name}: doc/ {nd}・log/ {nl} がどれも README.md に載っている）")

    findings = find(docs.links)
    if findings:
        ng(f"壊れた相対リンクがある（{name}: {len(findings)} 件）", findings,
           "→ issue を done/ へ移したら、それを指すリンクも直すこと（done/ の中から外へは ../ が 1 つ増える）")
    else:
        print(f"OK  動いている文書の相対リンクが全部実在する（{name} の doc / note / 開いている issue / tests / README / log/README.md）")

    if limits is not None:
        try:
            measured = docs.counts(root)
            findings = docs.ratchet(root, limits, measured)
        except (OSError, ValueError) as exc:
            findings = [f"mdguard が落ちた: {exc}"]
        if findings:
            ng(f"文書のラチェットを越えた（{name}）", findings,
               f"→ 経緯・日付つきの実測は log/ か issue へ、spec は決定 1 行 + リンクに。減らしたら上限 {limits} も下げる")
        else:
            values = " ".join(f"{key} {val}" for key, val in measured.items())
            print(f"OK  文書のラチェット（{name}: {values} が上限以内。上限は {limits}）")

    if under is not None and under != "-":
        stdout, stderr = io.StringIO(), io.StringIO()
        try:
            patterns = config.get("run", "math_paths", list) or config.get("math", "paths", list)
            if patterns is None and top is not None and explicit_config is None:
                patterns = load_config(top, top).get("math", "paths", list)
            names = repo_files(top, patterns, under)
            inputs = ((os.path.relpath(top / name, root), top / name) for name in names)
            with redirect_stdout(stdout), redirect_stderr(stderr):
                failed = math.check(inputs)
        except (OSError, ValueError) as exc:
            print(exc, file=stderr)
            failed = 1
        if failed:
            ng(f"文書の数式に GitHub で壊れる書き方がある（{name}: --under {under}）",
               (stderr.getvalue() + stdout.getvalue()).splitlines(),
               "→ 数式の直し方は mdguard の README を参照（M1 は空白、\\, は \\thinspace など）")
        else:
            print(f"OK  文書の数式が GitHub で壊れない（{name}: mdguard math --repo --under {under} で 0 件）")
    return rc


def main(argv=None):
    cli = parser()
    args = cli.parse_args(argv)
    cwd = Path.cwd()
    try:
        if args.command == "math":
            return math_command(args, cwd)
        if args.command == "selftest":
            from .selftest import run_selftest
            return run_selftest()

        root = Path(args.root).resolve()
        if not root.is_dir():
            raise ValueError(f"根 '{args.root}' が無い")
        if args.command == "links":
            print_lines(docs.links(root))
            return 0

        top = git_root(root)
        config = load_config(root, top, args.config)
        if args.command == "index":
            print_lines(docs.index(root, selected_path(args.exempt, config, "exempt")))
        elif args.command == "ratchet":
            limits = selected_path(args.limits, config, "ratchet")
            if limits is None:
                raise ValueError("上限ファイルを指定する")
            print_lines(docs.ratchet(root, limits))
        else:
            name = args.name or config.get("run", "name", str)
            if name is None:
                raise ValueError("--name または run.name を指定する")
            under = args.math_under or config.get("run", "math_under", str)
            return run(root, name, selected_path(args.exempt, config, "exempt"),
                       selected_path(args.ratchet, config, "ratchet"), under, config, top, args.config)
    except (OSError, ValueError) as exc:
        print(f"mdguard: {exc}", file=sys.stderr)
        return 2
    return 0
