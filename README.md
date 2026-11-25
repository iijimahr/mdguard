# mdguard

mdguard は Markdown を検査する CLI です。

- GitHub で表示が崩れる数式を見つけます。
- ファイルやディレクトリの索引への掲載漏れを見つけます。
- 相対リンクのリンク先を確認します。
- 文書の指標を記録した上限と比べます（ラチェット）。

## インストール

Python 3.11 以上が必要です。実行時に使う Python ライブラリは標準ライブラリのみです。設定で数式の対象を選ぶ `math --repo` と `run` の数式検査には Git が必要です。

mdguard のソースディレクトリで実行します。

```sh
python3 -m venv .venv
.venv/bin/pip install -e .
. .venv/bin/activate
mdguard --help
```

## クイックスタート

### 1. 設定なしで数式を検査する

検査したいファイルを渡します。

```sh
mdguard math README.md
```

たとえば、次の内容の `README.md` を検査します。

```markdown
# 文書

数式は $a\,b$ です。

[はじめに](guides/start.md)
```

標準出力にファイル名、行、列、規則番号、診断が出ます。

```text
README.md:3:7: M6 `\,` の `\` がエスケープとして消える（→ `\thinspace`）
```

標準エラー出力には規則ごとの件数が出ます。

```text
計 M6 1
```

この例では、`$a\,b$` を `$a\thinspace b$` に直すと、出力なしで終了コード `0` になります。

### 2. 設定を置いてまとめて検査する

Git リポジトリのルートに、次の最小構成の `.mdguard.toml` を置きます。前の例を続ける場合は、リンク先の `guides/start.md` も作成します。

```toml
[math]
paths = ["README.md", "guides/*.md"]

[run]
name = "文書"
math_under = "."
```

`links.paths` を省略すると、Git 内では追跡済みの Markdown がリンク検査の対象です。例のファイルをステージしてから実行します。

```sh
git add README.md guides/start.md .mdguard.toml
mdguard run .
```

```text
OK  文書の索引の点呼（文書: 対象ルールなし）
OK  文書の相対リンクの検査に合格（文書）
OK  文書の数式が GitHub で壊れない（文書: mdguard math --repo --under . で 0 件）
```

索引を検査するには `index.rules` を追加します。ラチェットを実行するには指標を定義し、上限ファイルを `run.ratchet` に指定します。

## コマンド

`ROOT` は文書検査の起点です。第 1 引数に指定します。以下の例では現在のディレクトリを示す `.` を使います。

### `math`

GitHub で表示が崩れる数式を検出します。

```sh
mdguard math README.md guides/
printf '%s\n' '値$x$' | mdguard math -
mdguard math --select M6 --summary README.md
mdguard math --ignore M13,M5 README.md
mdguard math --repo --under guides --list
```

- ファイルとディレクトリを指定できます。標準入力は `-` で指定します。
- `--select` は指定した規則だけを検査し、`--ignore` は指定した規則を除きます。複数の規則はカンマ区切りです。
- `--summary` は個別の診断を省き、規則ごとの件数を標準エラー出力に表示します。
- `--repo` は設定の Git pathspec で対象を選びます。必要なら `--under DIR` で範囲を絞れます。
- `--list` はパスを 1 行ずつ表示します。`--repo` と併用すると Git ルート相対のパスが出ます。
- `math --selftest` は保存済みの数式例と照合します。
- `math --verify-github` は数式例を GitHub の Markdown API に送信し、取得した結果と照合します。mdguard が外部通信するのはこのオプションを指定したときだけです。

**終了コード**　`0` は検出なし、一覧表示の成功、または数式例の一致です。`1` は検出、読み取り失敗、`--repo` の対象が 0 本の場合などです。`2` は引数の誤りや設定ファイルの読み込み失敗などです。

### `index`

設定した項目の名前が索引に載っているかを確認します。

```sh
mdguard index .
mdguard index . --exempt checks/index-exempt.txt
```

`--exempt FILE` で除外表を指定できます。1 行に `パス 理由` の形式で 1 項目を書きます。

**終了コード**　検査を実行できれば `0` です。合格時は出力が空で、掲載漏れなどは 1 件ずつ表示します。引数や設定のエラーは `2` です。

### `links`

`](path)` や `](path#anchor)` の相対パスを確認します。

```sh
mdguard links .
```

**終了コード**　検査を実行できれば `0` です。合格時は出力が空で、壊れたリンクなどは 1 件ずつ表示します。引数や設定のエラーは `2` です。

### `ratchet`

文書の指標を上限ファイルと比較します。

```sh
mdguard ratchet . checks/limits.txt
```

`ratchet.metrics` に指標を定義します。`run.ratchet` に上限ファイルを設定していれば、第 2 引数 `LIMITS` は省略できます。

**終了コード**　検査を実行できれば `0` です。合格時は出力が空で、上限超過などは 1 件ずつ表示します。引数や設定のエラーは `2` です。

### `run`

索引と相対リンクをまとめて検査します。上限ファイルを指定するとラチェットも実行します。数式の対象ディレクトリを指定すると数式も検査します。

```sh
mdguard run .
mdguard run . --name 文書 --exempt checks/index-exempt.txt --ratchet checks/limits.txt --math-under guides
```

検査ごとに `OK` または `NG` の行が出ます。`NG` の下には詳細を先頭 10 行まで表示し、続けて対処のヒントを表示します。

クイックスタートの `guides/start.md` に `[書き方](missing.md)` を追記すると、次のように出力します。

```text
OK  文書の索引の点呼（文書: 対象ルールなし）
NG  壊れた相対リンクがある（文書: 1 件）
    guides/start.md: missing.md
    → リンク元からの相対パスとリンク先を確認する
OK  文書の数式が GitHub で壊れない（文書: mdguard math --repo --under . で 0 件）
```

**終了コード**　すべて合格なら `0`、`NG` があれば `1` です。`ROOT` が見つからない場合など、検査を始める前のエラーは `2` です。

### `selftest`

テスト用の文書ツリーと記録済みの数式例で検査器の動作を確かめます。

```sh
mdguard selftest
```

**終了コード**　すべて期待どおりなら `0`、期待と違う結果があれば `1` です。

## 設定ファイル

数式とリンクから始める場合は、[クイックスタート](#クイックスタート)の最小構成を使えます。

### `[math]`

| キー | 型 | 既定 | 意味 |
|---|---|---|---|
| `paths` | 文字列の配列 | 未設定 | Git ルート相対の Git pathspec。`math --repo` の対象を選ぶ |

### `[index]`

| キー | 型 | 既定 | 意味 |
|---|---|---|---|
| `rules` | テーブルの配列 | `[]` | 索引の検査ルール |

`rules` の各要素に次のキーを指定します。

| キー | 型 | 既定 | 意味 |
|---|---|---|---|
| `base` | 文字列 | `"."` | 項目を探す起点。`ROOT` 相対 |
| `glob` | 文字列 | 必須 | 項目を選ぶ glob。`base` 相対 |
| `index` | 文字列 | 必須 | `"nearest-readme"` または `ROOT` 相対の索引ファイル |
| `hidden` | 真偽値 | `true` | `base` 以下の隠し項目を含める |
| `label` | 文字列 | `base` と `glob` をつないだパス | `run` で件数を表示するときの名前 |

```toml
[index]
rules = [
    { base = "guides", glob = "**/*.md", index = "nearest-readme" },
    { base = "releases", glob = "*.md", index = "RELEASES.md" },
]
```

### `[links]`

| キー | 型 | 既定 | 意味 |
|---|---|---|---|
| `paths` | 文字列の配列 | Git 内は `ROOT` 配下の追跡済み Markdown、Git 外は `["**/*.md"]` | リンク元を選ぶ glob。`[]` で対象を空にする |
| `exclude` | 文字列の配列 | `[]` | リンク元を除外する glob |
| `external_allow` | 文字列 | 未設定 | 境界外への相対リンクを認める許可表。`ROOT` 相対 |

### `[ratchet.metrics.<指標名>]`

指標ごとにテーブルを定義します。既定の指標はありません。

| キー | 型 | 既定 | 意味 |
|---|---|---|---|
| `paths` | 文字列の配列 | 必須 | 対象ファイルを選ぶ glob |
| `pattern` | 文字列 | 必須 | 行ごとに適用する Python の正規表現 |
| `count` | 文字列 | `"lines"` | `"lines"` は一致のある行数、`"matches"` は一致の回数 |
| `follow_symlinks` | 真偽値 | `false` | glob に一致したファイルへのシンボリックリンクも読む |

```toml
[ratchet.metrics.dated_headings]
paths = ["guides/**/*.md"]
pattern = '^#+ .*20[0-9]{2}-[0-9]{2}-[0-9]{2}'

[ratchet.metrics.long_lines]
paths = ["reference/conventions.md"]
pattern = '^.{401,}'

[ratchet.metrics.source_refs]
paths = ["guides/**/*.md"]
pattern = '[A-Za-z0-9_]\.(hpp|cpp|h|cu|py|sh|mk|c):[0-9]+'
count = "matches"
```

この設定に対応する上限ファイルの例です。

```text
dated_headings 3
long_lines 0
source_refs 2
```

### `[run]`

| キー | 型 | 既定 | 意味 |
|---|---|---|---|
| `name` | 文字列 | 未設定 | 結果に表示する名前。`run` には `--name` かこのキーが必要 |
| `exempt` | 文字列 | 未設定 | 索引の除外表。`index` でも使用 |
| `ratchet` | 文字列 | 未設定 | ラチェットの上限ファイル。`ratchet` でも使用 |
| `math_under` | 文字列 | 未設定 | 数式の対象ディレクトリ。Git ルート相対 |
| `math_paths` | 文字列の配列 | `math.paths` | `run` の数式対象だけを上書きする Git pathspec |

## 細則

### 設定の探索と優先順位

- `math --repo` は作業ディレクトリから設定を探します。文書検査は `ROOT` から探します。
- Git の中では起点から Git ルートまでさかのぼり、最初に見つかった `.mdguard.toml` を読みます。Git の外では起点だけを見ます。
- 数式検査で使う `math.paths` が子の設定になければ、Git ルートの設定を参照します。
- `--config FILE` はコマンドの前後どちらでも指定できます。この場合、数式の対象は指定した設定ファイルから読みます。
- 設定の `run.exempt` と `run.ratchet` は設定ファイルのあるディレクトリ相対です。
- CLI のファイル引数は呼び出し元のディレクトリ相対です。
- CLI の値が設定より優先されます。`--exempt -`、`--ratchet -`、`--math-under -` で対応する設定を無効にできます。

### 数式の Git pathspec

- `math.paths` の通常の `guides/*.md` は、`guides/` の下位階層にも一致します。
- 除外にも Git pathspec を使えます。たとえば `":(exclude,glob)**/archive/**"` を配列に加えます。
- `--repo` は追跡済みの Markdown と、Git が無視していない未追跡の Markdown を列挙します。
- 作業ツリーから削除済みの項目は対象から外します。
- `--under DIR` と `run.math_under` は Git ルート相対です。`.` は設定の対象全体を指します。

### 文書検査の glob

- 文書検査の glob は `ROOT` 相対です。`index.rules.glob` の起点は `base` です。
- `*` は 1 階層内、`**/*.md` は直下と下位階層に一致します。
- ドットで始まる名前も含みます。
- `**` の再帰はシンボリックリンク先のディレクトリをたどりません。

### 索引の掲載判定

- `index.rules.glob` はファイルとディレクトリを選びます。
- `"nearest-readme"` は各項目の親から `base` までさかのぼり、最も近い `README.md` を探します。この方式では `README.md` 自体を検査対象から外します。
- 固定の索引ファイルを指定した場合は、そのファイル自体を検査対象から外します。
- 項目名が索引のいずれかの行に含まれていれば掲載済みとします。
- 除外表のパスは `ROOT` 相対です。除外表に存在しない項目が残っていれば報告します。

### リンクの境界と許可表

- `links.paths` を明示すると、glob は作業ツリー上のファイルを選びます。
- リンク先はリンク元のディレクトリから解決します。フラグメント（`#anchor`）は検査対象から外します。
- 境界は Git ルートです。Git の外では `ROOT` が境界です。
- 境界内のリンク先が存在しなければ報告します。Git に無視されるパスは報告から除きます。
- 境界外への相対リンクは、許可表で認められた範囲と件数に限ります。許可表が未設定か見つからない場合は、境界外へのリンクをすべて報告します。
- 許可表は 1 行に `/absolute/path/ ### 2 ### 理由` の形式で書きます。末尾が `/` の絶対パスの接頭辞と、出現回数の上限を指定します。
- 解決後の絶対パスに対して、表の先頭から最初に一致する項目を適用します。
- リンク先の実在にかかわらず、リンクの出現ごとに数えます。

### ラチェットの数え方

- 検査には指標と上限ファイルが必要です。上限ファイルには `dated_headings 3` のように、指標名と整数の上限を 1 行ずつ書きます。
- 正規表現は各行の末尾の LF を除いて適用します。
- `count = "lines"` は、何回一致してもその行を 1 回と数えます。
- `count = "matches"` は、重ならない一致を出現ごとに数えます。
- 同じファイルが複数の glob に一致しても、各指標で 1 回だけ読みます。
- 計測値が上限ちょうどなら合格です。

## 数式の規則

| 規則 | GitHub で表示が崩れる書き方 |
|---|---|
| M1 | 開きの `$` が行頭・許容される空白・`(` などの直後にない。和文・全角空白・全角括弧の直後などでは `$` がそのまま残る |
| M2 | 開きの `$` の直後が空白 |
| M3 | 閉じの `$` の直前が空白 |
| M4 | 閉じの `$` の直後が ASCII 英数字または `_` |
| M5 | インライン数式が改行をまたぐ |
| M6 | `\,` や `\{` のバックスラッシュが Markdown のエスケープとして消える。`\,` は `\thinspace` で表せる |
| M7 | `*` や `_` が Markdown の強調になる。または数式が斜体の中にある。太字の中は可 |
| M8 | 数式中の `<…>` が HTML タグと解釈されて消える |
| M9 | 表の中の数式にエスケープしていない縦棒（U+007C）があり、セルが割れる。`\vert` や `\Vert` を使える |
| M10 | 複数行の `$$` ブロックが段落全体を占めていない。前後の段落とは空行で区切る |
| M11 | 数式ブロックに空行や、Markdown の箇条書き・引用・見出し・区切りとして解釈される行がある |
| M12 | 箇条書き内に複数行の `$$` ブロックがある。1 行の `$$…$$` や GitHub の `math` フェンスは可 |
| M13 | `$` の対応が取れない。または閉じの `$$` がない |
| M14 | 数式中にリンク、メンション、インラインコードがある。またはリンクの表示テキストに数式がある |
| M15 | GitHub の MathJax が許可しないマクロを使う。検出対象は `\operatorname`、`\thickspace`、`\mkern`、`\medspace` |
| M16 | `\text{…}` や `\texttt{…}` などのテキスト用マクロの中に `_` や `^` がある。コード名は数式の外でインラインコードにできる |
| M17 | ASCII の制御文字（U+0000〜U+001F のうち TAB・LF・CR 以外と U+007F DEL）がある。数式の内外を問わず報告する。U+0007・U+0008・U+000B・U+000C は、raw でない文字列（Python の `"\alpha"` など）で `\a`・`\b`・`\v`・`\f` がエスケープとして効いた跡であることが多い。TAB・CR は普通の文書にもあるので、LaTeX のマクロの残りが続くとき（`\tanh`・`\theta`・`\thinspace`・`\text` の `\t`、`\rho`・`\right`・`\rvert` の `\r` の跡）と、行末でない CR（CRLF の一部でない）だけ報告する。`\\` を重ねるか raw 文字列（`r"…"`）にする |
| M18 | 表の右寄せ（`---:`）・中央寄せ（`:---:`）の列にインライン数式がある。iOS Safari では先頭の 1 字ほどしか表示されない。数式を含む列は左寄せ（`---`）にする |

M15・M16・M18 はブラウザーでの描画時に起きます。M18 は GitHub の API の出力（HTML）では正常で、iOS Safari での目視でだけ確認しています。該当する例には目視結果を記録しており、`math --verify-github` でもその記録を参照します。

M17 は数式に限らずファイル全体を検査します。GitHub の表示と突き合わせる例の表（`cases.json`）には含めず、単体テストで確かめます。

## 開発

リポジトリのルートで、インストールに使った仮想環境を有効にして実行します。

```sh
python3 -m unittest
python3 -m mdguard selftest
```

ソースから直接実行する場合は、それぞれのコマンドの前に `PYTHONPATH=src` を付けます。

## ライセンス

BSD 3-Clause License（[LICENSE](LICENSE)）。
