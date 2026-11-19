"""索引・相対リンク・ラチェットの種の木を使った動作確認。"""

from pathlib import Path
from tempfile import TemporaryDirectory

from . import docs, math


def seed_checks(base):
    """不合格と修正後の両方を調べ、期待と違った結果を返す。"""
    root = base / "tree/project"
    extern = base / "external"
    extern.mkdir()
    (extern / "exists.md").touch()
    exempt, limits = base / "exempt.txt", base / "limits.txt"
    allow = root / docs.EXTERNAL_ALLOW
    index_errors, ratchet_errors = [], []

    def write(name, content=""):
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    def expect(errors, label, got, expected):
        if got != expected:
            errors.append(f"{label}: {got!r} / 期待値 {expected!r}")

    write("sub/README.md", "# 1 段下\n[無い](gone.md)\n")
    write("doc/README.md", "# 索引\n[a](design/a.md) [無い](design/nothere.md)\n")
    write("doc/design/a.md", "# a\n## 1. 中身\n")
    write("doc/design/b.md", "# b\n## 2020-01-01 の実測\n### 2020-01-02 の続き\n`x.hpp:12` の `f`\n")
    write("log/README.md", "[記録](2020-01-01_entry.md)\n")
    write("log/2020-01-01_entry.md")
    write("log/2020-01-02_entry.md")
    write("note/spec.md", "決" * 401 + "\n" + "決" * 400 + "\n")
    exempt.write_text("# 除外\nlog/2020-01-03_gone.md 腐った行\n", encoding="utf-8")
    limits.write_text("date_headings 1\nspec_long_lines 0\nline_refs 0\n", encoding="utf-8")

    expect(index_errors, "索引", docs.index(root, exempt), [
        "doc/design/b.md: doc/README.md に載っていない",
        "log/2020-01-02_entry.md: log/README.md に載っていない",
        "log/2020-01-03_gone.md: 除外リストにあるのに無い（腐った行）",
    ])
    expect(index_errors, "相対リンク", docs.links(root), [
        "doc/README.md: design/nothere.md", "sub/README.md: gone.md",
    ])
    expect(ratchet_errors, "ラチェット", docs.ratchet(root, limits), [
        "date_headings: 2 が上限 1 を越えた",
        "spec_long_lines: 1 が上限 0 を越えた",
        "line_refs: 1 が上限 0 を越えた",
    ])

    write("doc/README.md", "# 索引\n[a](design/a.md) [b](design/b.md)\n")
    write("sub/README.md", "# 1 段下\n")
    write("log/README.md", "[記録](2020-01-01_entry.md) [記録](2020-01-02_entry.md)\n")
    exempt.write_text("# 除外\n", encoding="utf-8")
    limits.write_text("date_headings 2\nspec_long_lines 1\nline_refs 1\n", encoding="utf-8")
    expect(index_errors, "修正後の索引", docs.index(root, exempt), [])
    expect(index_errors, "修正後の相対リンク", docs.links(root), [])
    expect(ratchet_errors, "上限ちょうど", docs.ratchet(root, limits), [])

    missing = "[外](../../../external/gone.md)\n"
    existing = "[外](../../../external/exists.md)\n"
    write("sub/README.md", missing)
    expect(index_errors, "未許可", docs.links(root), [
        f"sub/README.md: ../../../external/gone.md: リポジトリ外への相対リンク（未許可: {extern}/gone.md）",
    ])
    write(allow, f"{extern}/ ### 1 ### 試験材料\n")
    expect(index_errors, "許可内の欠損", docs.links(root), [])
    write("sub/README.md", missing + existing)
    expect(index_errors, "上限超過", docs.links(root), [
        f"sub/README.md: ../../../external/exists.md: リポジトリ外への相対リンク（{extern}/ の上限 1 を越えた）",
    ])
    write(allow, f"{extern}/ ### 2 ### 試験材料\n")
    expect(index_errors, "許可内の 2 件", docs.links(root), [])
    write("sub/README.md", missing + existing + "[兄弟](../../../external_other/gone.md)\n"
          "[逸脱](../../../external/../gone.md)\n")
    expect(index_errors, "許可範囲外", docs.links(root), [
        f"sub/README.md: ../../../external_other/gone.md: リポジトリ外への相対リンク（未許可: {base}/external_other/gone.md）",
        f"sub/README.md: ../../../external/../gone.md: リポジトリ外への相対リンク（未許可: {base}/gone.md）",
    ])
    malformed = f"{extern}/ ### 2 ### "
    write(allow, malformed + "\n")
    expect(index_errors, "理由なし", docs.links(root)[:1], [
        f"{docs.EXTERNAL_ALLOW}: 許可表の書式（<絶対パスの頭（末尾 /）> ### <上限の数> ### <理由>）: {malformed}",
    ])
    return index_errors, ratchet_errors


def run_selftest():
    with TemporaryDirectory() as temp:
        index_errors, ratchet_errors = seed_checks(Path(temp).resolve())
    if index_errors:
        print("NG  番人 (44): 文書の索引・リンクの番人が種を拾い違えた")
        for line in index_errors:
            print(f"    {line}")
    else:
        print("OK  番人 (44): 索引の点呼とリンクの番人が種の抜け 3 件・壊れたリンク 2 件（doc と 1 段下の README）を拾い、直した木では黙る。外向きは未許可・上限超過・許可範囲の逸脱・理由なしで NG、許可内で OK")
    if ratchet_errors:
        print("NG  番人 (45): 文書のラチェットが種を数え違えた")
        for line in ratchet_errors:
            print(f"    {line}")
    else:
        print("OK  番人 (45): 文書のラチェットが日付見出し 2 > 1・401 字の行 1 > 0・行番号の参照 1 > 0 で落ち（400 字の行は数えない = 字で数える）、上限ちょうどは通す")
    math_status = math.run_cases(live=False)
    return int(bool(index_errors or ratchet_errors or math_status))
