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
| `mdguard index ROOT [--exempt FILE]` | 設定した項目名が索引に載っているかを確認。除外表には `パス 理由` を 1 項目ずつ書く |
| `mdguard links ROOT` | `](path)` や `](path#anchor)` の相対パスを確認 |
| `mdguard ratchet ROOT LIMITS` | 文書の指標を上限と比較。設定に `run.ratchet` があれば `LIMITS` は省略可 |
| `mdguard run ROOT [--name NAME] [--exempt FILE] [--ratchet FILE] [--math-under DIR]` | 検査ごとに `OK  ` / `NG  ` を 1 行出し、NG の下に詳細を先頭 10 行まで表示。NG があれば終了コード 1 |
| `mdguard selftest` | 種の木と記録した数式例で検査器を確認 |

単独の `index`、`links`、`ratchet` は合格なら出力が空で、検出結果は 1 件ずつ出力します。検出結果があっても終了コードは 0 です。数式検査は検出やファイル読み取りの失敗があれば 1 を返し、`--summary` で規則ごとの件数を表示します。`--select M6` や `--ignore M13,M5` で規則を指定できます。

`math --selftest` は保存した例を使い、`math --verify-github` は GitHub の Markdown API に送信して結果を照合します。通信するのは `--verify-github` を指定した場合だけです。

## 設定ファイル

```toml
# .mdguard.toml
[math]
paths = ["README.md", "guides/*.md", "packages/*.md", ":(exclude,glob)**/archive/**"]

[index]
rules = [
    { base = "guides", glob = "**/*.md", index = "nearest-readme" },
    { base = "releases", glob = "*.md", index = "RELEASES.md" },
]

[links]
paths = ["README.md", "guides/**/*.md", "reference/**/*.md"]
exclude = ["guides/archive/**/*.md"]
external_allow = "checks/external-links.txt"

[ratchet.metrics.dated_headings]
paths = ["guides/**/*.md"]
pattern = '^#+ .*20[0-9]{2}-[0-9]{2}-[0-9]{2}'
count = "lines"

[ratchet.metrics.long_lines]
paths = ["reference/conventions.md"]
pattern = '^.{401,}'
count = "lines"

[ratchet.metrics.source_refs]
paths = ["guides/**/*.md"]
pattern = '[A-Za-z0-9_]\.(hpp|cpp|h|cu|py|sh|mk|c):[0-9]+'
count = "matches"

[run]
name = "文書"
exempt = "checks/index-exempt.txt"
ratchet = "checks/limits.txt"
math_under = "."
# math_paths = ["README.md", "guides/*.md"]  # run の数式対象だけ上書きする場合
```

- `math.paths` は Git ルート相対の Git pathspec の配列です。通常の `guides/*.md` は `guides/` の深い階層にも一致します。パスの除外にも Git pathspec を使えます。
- `--under DIR` と `run.math_under` は Git ルート相対のディレクトリを指定します。`.` は設定の対象全体です。`math --repo --list` は Git ルート相対のパスを 1 行ずつ表示し、対象が 0 本なら失敗します。
- `math --repo` は作業ディレクトリ、文書検査は `ROOT` から Git の根まで上がって最初の `.mdguard.toml` を読みます。Git の外では起点のみを見ます。子の設定に `math.paths` がなければ Git の根の設定を参照します。
- `--config FILE` はコマンドの前後どちらでも指定でき、そのファイルを使います。設定内の `exempt` と `ratchet` は設定ファイルのあるディレクトリ相対、CLI のファイル引数は呼び出し元のディレクトリ相対です。
- CLI の値が設定より優先されます。`run` は索引とリンクの結果を表示し、上限ファイルと数式の対象ディレクトリがそれぞれ指定された場合に対応する検査も行います。`--exempt -`、`--ratchet -`、`--math-under -` で設定の指定を外せます。

文書検査の glob は `ROOT` 相対です。`*` は 1 階層内に、`**/*.md` は直下と下位階層に一致します。ドットで始まる名前も含み、`**` の再帰ではシンボリックリンク先のディレクトリをたどりません。

- `index.rules` の `glob` は `base`（省略時は `ROOT`）を起点にファイルとディレクトリを選びます。`index = "nearest-readme"` は各項目の親から `base` まで最も近い `README.md` を探し、`README.md` 自体は点呼の対象から外します。固定の索引を使う場合は `ROOT` 相対のファイル名を書きます。`hidden = false` で `base` 以下の隠し項目を外し、`label` で `run` の件数表示名を指定できます。既定では索引ルールはありません。
- `links.paths` を省略すると、Git 内では `ROOT` 配下の追跡済み Markdown、Git 外では `**/*.md` を検査します。明示した glob は作業ツリー上のファイルを選びます。`links.exclude` で対象を外し、`paths = []` で対象を空にできます。
- リンク先は Git の根、Git 外では `ROOT` を境界とします。境界外への相対リンクを許すには、`links.external_allow` で `ROOT` 相対の許可表を指定し、`/absolute/path/ ### 2 ### 理由` の形式で解決後の絶対パスの接頭辞と出現回数の上限を書きます。先頭から最初に一致する項目を適用し、リンク先の実在にかかわらず出現ごとに数えます。設定または許可表がなければ境界外は許可されません。
- `ratchet.metrics` で名前ごとに、対象の glob と Python の正規表現を指定します。正規表現は改行を除いた各行に適用します。`count = "lines"`（既定）は一致のある行を 1 回、`"matches"` は重ならない一致を出現ごとに数えます。同じファイルが複数の glob に一致しても各指標で 1 回読みます。`follow_symlinks = true` で glob に一致したファイルへのシンボリックリンクも読みます。既定の指標はありません。ラチェットを実行する場合は指標を定義し、上限ファイルに `dated_headings 3` のように指標名と整数を 1 行ずつ書きます。

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

## ライセンス

BSD 3-Clause License（[LICENSE](LICENSE)）。
