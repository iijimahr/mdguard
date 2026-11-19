# mdguard

Check Markdown for GitHub math rendering problems, missing index entries,
broken relative links, and documentation metrics that exceed saved limits.

Python 3.11 以上。実行時に使う Python ライブラリは標準ライブラリのみです。`math --repo` は Git を使用します。

## インストールと使い方

```sh
python3 -m venv .venv
.venv/bin/pip install -e .
.venv/bin/mdguard --help
.venv/bin/python -m mdguard selftest
```

| コマンド | 検査 |
|---|---|
| `mdguard math FILES…` | ファイルやディレクトリを指定して数式を検査。標準入力は `-` |
| `mdguard math --repo [--under DIR] [--list]` | 設定した対象を検査。追跡済みと Git が無視していない未追跡の Markdown を列挙し、作業ツリーから削除済みの項目を外す |
| `mdguard index ROOT [--exempt FILE]` | `doc/` 配下の各 Markdown 名を最も近い上位 `README.md` で確認。`log/` 直下の項目名は `log/README.md` で確認。除外表には `パス 理由` を 1 項目ずつ書く |
| `mdguard links ROOT` | 現行文書の `](path)` や `](path#anchor)` の相対パスを確認。対象は `doc/`、`tests/`、`note/` 直下、`note/history/`・`note/issues/`・`note/jobs/` の直下、ルートの Markdown、1 段下の `README.md` と `log/README.md` |
| `mdguard ratchet ROOT LIMITS` | 文書の指標を上限と比較。設定に `run.ratchet` があれば `LIMITS` は省略可 |
| `mdguard run ROOT [--name NAME] [--exempt FILE] [--ratchet FILE] [--math-under DIR]` | 検査ごとに `OK  ` / `NG  ` を 1 行出し、NG の下に詳細を先頭 10 行まで表示。NG があれば終了コード 1 |
| `mdguard selftest` | 種の木と記録した数式例で検査器を確認 |

単独の `index`、`links`、`ratchet` は合格なら出力が空で、検出結果は 1 件ずつ出力します。検出結果があっても終了コードは 0 です。数式検査は検出やファイル読み取りの失敗があれば 1 を返し、`--summary` で規則ごとの件数を表示します。`--select M6` や `--ignore M13,M5` で規則を指定できます。

`math --selftest` は保存した例を使い、`math --verify-github` は GitHub の Markdown API に送信して結果を照合します。通信するのは `--verify-github` を指定した場合だけです。

相対リンクの境界は、検査する根が Git の根ならその根、それ以外なら検査する根の親です。境界の外を意図的に指す場合は、検査する根の `tests/doc_external_allow.txt` に `/absolute/path/ ### 2 ### 理由` の形式で、解決後の絶対パスの接頭辞と出現回数の上限を指定します。表の先頭から最初に一致する項目を適用し、リンク先の実在にかかわらず出現ごとに数えます。

ラチェットの上限ファイルは `date_headings 3` のように 1 行に名前と整数を書きます。名前は `date_headings`（`doc/` の日付付き見出し）、`spec_long_lines`（`note/spec.md` の 401 文字以上の行）、`line_refs`（`doc/` の `file.hpp:12` などの行番号参照）の 3 つです。日付付きの経緯は記録へ、仕様は短い決定と参照先へまとめ、コードの参照は位置がずれにくい関数名や変数名で示せます。

## 設定ファイル

```toml
# .mdguard.toml
[math]
paths = ["README.md", "doc/*.md", "packages/*.md", ":(exclude,glob)**/log/**"]

[run]
name = "文書"
exempt = "tests/doc_index_exempt.txt"
ratchet = "tests/doc_ratchet.txt"
math_under = "."
# math_paths = ["README.md", "doc/*.md"]  # run の数式対象だけ上書きする場合
```

- `math.paths` は Git ルート相対の Git pathspec の配列です。通常の `doc/*.md` は `doc/` の深い階層にも一致します。パスの除外にも Git pathspec を使えます。
- `--under DIR` と `run.math_under` は Git ルート相対のディレクトリを指定します。`.` は設定の対象全体です。`math --repo --list` は Git ルート相対のパスを 1 行ずつ表示し、対象が 0 本なら失敗します。
- `math --repo` は作業ディレクトリ、文書検査は `ROOT` から Git の根まで上がって最初の `.mdguard.toml` を読みます。Git の外では起点のみを見ます。子の設定に `math.paths` がなければ Git の根の設定を参照します。
- `--config FILE` はコマンドの前後どちらでも指定でき、そのファイルを使います。設定内の `exempt` と `ratchet` は設定ファイルのあるディレクトリ相対、CLI のファイル引数は呼び出し元のディレクトリ相対です。
- CLI の値が設定より優先されます。`run` は索引とリンクを常に検査し、上限ファイルと数式の対象ディレクトリがそれぞれ指定された場合に対応する検査も行います。`--exempt -`、`--ratchet -`、`--math-under -` で設定の指定を外せます。

## 数式の規則

| 規則 | GitHub で表示が崩れる書き方 |
|---|---|
| M1 | 開きの `$` が行頭・許容される空白・`(` などの直後にない。和文、全角空白、全角括弧の直後などでは生の `$` が残る |
| M2 | 開きの `$` の直後が空白 |
| M3 | 閉じの `$` の直前が空白 |
| M4 | 閉じの `$` の直後が ASCII 英数字または `_` |
| M5 | インライン数式が改行をまたぐ |
| M6 | `\\,`、`\\{` などのバックスラッシュが Markdown のエスケープとして消える。例えば `\\,` は `\\thinspace` で表せる |
| M7 | `*`・`_` が Markdown の強調になる、または斜体の内側に数式がある。太字の内側は可 |
| M8 | 数式中の `<…>` が HTML タグと解釈されて消える |
| M9 | 表の中の数式に縦棒（U+007C）があり、セルが割れる |
| M10 | `$$` だけの行で始まるブロックが段落全体を占めていない |
| M11 | 数式ブロックに Markdown の箇条書き・引用・見出し・区切りとして解釈される行や空行がある |
| M12 | 箇条書き内に複数行の `$$` がある。1 行の `$$…$$` や GitHub の `math` フェンスは可 |
| M13 | `$` の対応が取れない、または閉じの `$$` がない |
| M14 | 数式中にリンクやメンションがある |
| M15 | GitHub の MathJax が許可しないマクロがある。対象は `\\operatorname`、`\\thickspace`、`\\mkern`、`\\medspace` |
| M16 | `\\text{…}` や `\\texttt{…}` などのテキスト用マクロの中に `_` や `^` がある。コード名は数式の外でインラインコードにできる |

M15・M16 はブラウザーでの MathJax 描画時に起きるため、例には目視結果を記録しています。

```sh
.venv/bin/python -m unittest
```
