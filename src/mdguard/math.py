"""GitHub で表示されない数式を Markdown から探す。

GitHub の Markdown API（POST /markdown、mode=gfm）で得た表示結果を使う。
API はコメント欄と同じ解析で、ファイル表示との違いは改行を <br> にするかどうか。
M1 では例えば句読点直後の数式がファイル表示でも生の $ のまま残る。

M15・M16 は Markdown の後の MathJax の段で起きる。例の表で api_blind が
真の例はブラウザーでの目視結果を使い、--verify-github のときも比較値に使う。

修正には描画系を問わず同じ TeX になる書き方（M1・M4 は空白、\\, は
\\thinspace など）を使える。$`…`$ と ```math は GitHub 専用で、
ほかの描画系では数式として扱われない場合がある。

規則

  M1  開きの $ の左が行頭・空白・`(` 以外（和文・全角空白・`（`・`[`・`*` などは不可）
  M2  開きの $ の直後が空白
  M3  閉じの $ の直前が空白
  M4  閉じの $ の直後が ASCII 英数字か `_`（和文・記号は可）
  M5  インライン数式が行をまたぐ
  M6  `\\` + ASCII 記号の `\\` がエスケープとして消える（`\\{` → `{`、`\\,` → `,`）。
      `\\\\` はブロックの行末だけ残る
  M7  `*`・`_` が段落の中で組になって強調に食われる / 斜体の中の数式（太字は可）
  M8  中に HTML タグに見える `<…>` がある（タグとして消える）
  M9  表の行の中の `|`（セルが割れる）
  M10 $$ だけの行で始まるブロックが段落の全体でない（前後に空行が要る）
  M11 ブロックの中の行が Markdown の構造になる（行頭の `- ` `+ ` `* ` `1. ` `> ` `#`、
      `===` / `---` だけの行、空行）
  M12 箇条書きの中の複数行の $$（表示されない。```math か 1 行の $$…$$ は可）
  M13 $ の対応が取れない / 閉じの $$ が無い
  M14 中にリンク `[…](…)` かメンション `@名前` がある
  M15 GitHub の MathJax が許さないマクロ。許可リストは非公開で、
      1 つあるとブロック全体が赤いエラーになる。
      \\operatorname・\\thickspace・\\mkern・\\medspace は不可。\\mskip は可。
      → \\operatorname は \\mathrm{…}、空白は \\mskip5mu など。
      \\rule を使って下線の代わりにしても表示されない。
  M16 `\\text{…}`・`\\texttt{…}` の中の `_` `^`（GitHub の MathJax ではエラー「'_' allowed only in math mode」）。
      `\\_` は Markdown が `\\` を食べるので、コードの名前は数式の外へ（インラインコード）
  M18 表の右寄せ（`---:`）・中央寄せ（`:---:`）の列にあるインライン数式。
      iOS Safari で先頭の 1 字ほどしか表示されない（API の出力は正常で、ブラウザーの描画で欠ける）。
      → 数式を含む列は左寄せ（`---`）にする
  M17 ASCII の制御文字（U+0000–U+001F のうち TAB・LF・CR 以外と U+007F）。数式の内外を問わない。
      U+0007・U+0008・U+000B・U+000C は raw でない文字列に書いた `\\a` `\\b` `\\v` `\\f` の跡のことが多い。
      TAB・CR は、マクロの残り（`anh` `heta` `hinspace` `ext…` など、`ho` `ight` `vert` など）が続くとき
      （`\\t` `\\r` の跡）と、行末でない CR（CRLF の一部でない）だけ報告する
"""
import html
import json
import re
import sys
import unicodedata
import urllib.request
from dataclasses import dataclass
from importlib.resources import files

ASCII_PUNCT = set("!\"#$%&'()*+,-./:;<=>?@[\\]^_`{|}~")

# 標準の TeX の別名（\\thickspace・\\medspace は MathJax で確かめられなかったので \\mskip）
ESC_HINT = {
    "{": r"\lbrace", "}": r"\rbrace", "|": r"\Vert", ",": r"\thinspace", "!": r"\negthinspace",
    ";": r"\mskip5mu", ":": r"\mskip4mu",
    "%": "末尾なら % を数式の外へ（`$27$%`）",
    "_": "コードの名前なら数式の外へ（インラインコード）",
}

RE_FENCE = re.compile(r"^([ \t]*(?:>[ \t]?)*(?:[ \t]*(?:[-*+]|\d+[.)])[ \t]+)?[ \t]*)(`{3,}|~{3,})(.*)$")
RE_PREFIX = re.compile(r"^((?:[ \t]*>)*[ \t]*)((?:[-*+]|\d+[.)])(?:[ \t]+|$))?[ \t]*")
RE_HEADING = re.compile(r"^#{1,6}(\s|$)")
# 中身の空いた箇条書き（`+` だけの行）は段落を割り込めないので構造にならない。`-` `=` だけの行は見出しの下線
RE_BLOCKISH = re.compile(r"^(?:(?:[-+*]|\d+[.)])[ \t]+\S|>|#{1,6}(?:\s|$)|=+\s*$|-+\s*$)")
RE_QUOTE = re.compile(r"^[ \t]*(?:>[ \t]?)*[ \t]*")
RE_TAG = re.compile(r"<(?:[A-Za-z][A-Za-z0-9-]*(?:\s[^<>]*)?/?|/[A-Za-z][A-Za-z0-9-]*\s*)>")
RE_DELIM_CELL = re.compile(r"^\s*(:?)-+(:?)\s*$")
RE_LINK = re.compile(r"\[[^\]]*\]\(")
RE_MENTION = re.compile(r"(?<![A-Za-z0-9])@[A-Za-z0-9]")
DISALLOWED = {"operatorname", "thickspace", "mkern", "medspace"}   # GitHub の MathJax が許さない（目視で確かめたものだけ足す。\\mskip は可）
RE_MACRO = re.compile(r"\\([A-Za-z]+)")
RE_TEXTMODE = re.compile(r"\\(?:text|texttt|textrm|textbf|textit|textsf|mbox)\{([^{}]*)\}")
RE_CTRL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")   # TAB・LF・CR は除く
CTRL_ESC = {"\a": "a", "\b": "b", "\v": "v", "\f": "f"}
# TAB・CR は普通の文書にもある（字下げ・CRLF）ので、LaTeX のマクロの残りが続くときだけ報告する。
# raw でない文字列の "\tanh"・"\theta"・"\thinspace"・"\text"、"\rho"・"\right"・"\rvert" の跡
RE_TAB_MACRO = re.compile(r"\t(?=(?:ext(?:bf|rm|it|sf|tt|style|normal|up)?|frac|binom|anh?|au|heta|hinspace|hickspace|imes|ilde|o|op|riangle[a-z]*)(?![A-Za-z]))")
RE_CR_MACRO = re.compile(r"\r(?=(?:ho|ight[a-z]*|vert|Vert|angle|brace|brack|ceil|floor|m|aisebox)(?![A-Za-z]))")
RE_LONE_CR = re.compile(r"\r(?!$)")   # 行末（CRLF の CR）でない CR


@dataclass
class Finding:
    line: int
    col: int
    rule: str
    msg: str


@dataclass
class Span:
    kind: str     # inline / display / backtick
    start: int    # 段落の文字列の中の位置（開きの $ から閉じの $ の後ろまで）
    end: int
    src: str
    pos: tuple = (0, 0)   # 開きの $ の (行, 列)、1 始まり。lint_text が埋める
    endpos: tuple = (0, 0)   # 閉じの $ の後ろの (行, 列)


def ws(c):
    return c == "" or c.isspace()


def punct(c):
    return c in ASCII_PUNCT or c == "\0" or (c != "" and unicodedata.category(c).startswith("P"))


class Para:
    """行の束を 1 本の文字列にし、位置を元の (行, 列) に戻せるようにする。"""

    def __init__(self, rows):
        # rows: [(行番号 0 始まり, 内容が始まる列, 内容)]
        self.rows = rows
        self.text = "\n".join(r[2] for r in rows)
        self.offs = []
        o = 0
        for r in rows:
            self.offs.append(o)
            o += len(r[2]) + 1

    def where(self, pos):
        k = 0
        while k + 1 < len(self.offs) and self.offs[k + 1] <= pos:
            k += 1
        ln, c0, _ = self.rows[k]
        return ln + 1, c0 + (pos - self.offs[k]) + 1


def mask_code(text):
    """インラインコードの中身を \\0 にする。$`…`$ は数式として拾い、$ ごと潰す。"""
    t = list(text)
    spans = []
    i = 0
    while i < len(text):
        if text[i] == "\\" and i + 1 < len(text) and text[i + 1] in ASCII_PUNCT:
            i += 2
            continue
        if text[i] != "`":
            i += 1
            continue
        j = i
        while j < len(text) and text[j] == "`":
            j += 1
        n = j - i
        m = re.compile(r"(?<!`)" + "`" * n + r"(?!`)").search(text, j)
        if not m:
            i = j
            continue
        if i > 0 and text[i - 1] == "$" and m.end() < len(text) and text[m.end()] == "$":
            spans.append(Span("backtick", i - 1, m.end() + 1, text[i - 1:m.end() + 1]))
            for k in range(i - 1, m.end() + 1):
                t[k] = "\0"
        else:
            for k in range(i, m.end()):
                t[k] = "\0"
        i = m.end()
    return "".join(t), spans


def dollar_pairs(text):
    """(開き, 閉じ, 長さ) の組と、閉じの無い開き。$ は次の $ で、$$ は次の $$ で閉じる。"""
    pos, i = [], 0
    while i < len(text):
        if text[i] == "\\" and i + 1 < len(text) and text[i + 1] in ASCII_PUNCT:
            i += 2
            continue
        if text[i] == "$":
            pos.append(i)
        i += 1
    pairs, lone, k = [], [], 0
    while k < len(pos):
        o = pos[k]
        n = 2 if k + 1 < len(pos) and pos[k + 1] == o + 1 else 1
        if n == 1:
            if k + 1 < len(pos):
                pairs.append((o, pos[k + 1], 1))
                k += 2
            else:
                lone.append((o, 1))
                k += 1
            continue
        m = next((m for m in range(k + 2, len(pos) - 1) if pos[m + 1] == pos[m] + 1), None)
        if m is None:
            lone.append((o, 2))
            k += 2
        else:
            pairs.append((o, pos[m], 2))
            k = m + 2
    return pairs, lone


def emphasis_pairs(text):
    """CommonMark の delimiter run の規則で * と _ の組を作る（長さの細部は省く）。"""
    runs, i = [], 0
    while i < len(text):
        c = text[i]
        if c == "\\" and i + 1 < len(text) and text[i + 1] in ASCII_PUNCT:
            i += 2
            continue
        if c not in "*_":
            i += 1
            continue
        j = i
        while j < len(text) and text[j] == c:
            j += 1
        b = text[i - 1] if i > 0 else ""
        a = text[j] if j < len(text) else ""
        left = not ws(a) and (not punct(a) or ws(b) or punct(b))
        right = not ws(b) and (not punct(b) or ws(a) or punct(a))
        if c == "*":
            op, cl = left, right
        else:
            op = left and (not right or punct(b))
            cl = right and (not left or punct(a))
        runs.append(dict(c=c, s=i, e=j, n=j - i, op=op, cl=cl))
        i = j
    pairs, stack = [], []
    for r in runs:
        if r["cl"]:
            for k in range(len(stack) - 1, -1, -1):
                o = stack[k]
                if o["c"] != r["c"]:
                    continue
                if (o["cl"] or r["op"]) and (o["n"] + r["n"]) % 3 == 0 and not (o["n"] % 3 == 0 and r["n"] % 3 == 0):
                    continue
                pairs.append((o, r))
                del stack[k:]
                break
            else:
                if r["op"]:
                    stack.append(r)
        elif r["op"]:
            stack.append(r)
    return pairs


def check_content(body, base, display, in_table, add):
    """数式の中身（$ を除いた部分）の検査。base は body の先頭の段落内の位置。"""
    i = 0
    while i < len(body):
        if body[i] == "\\" and i + 1 < len(body):
            c = body[i + 1]
            if c in ASCII_PUNCT:
                eol = c == "\\" and (i + 2 >= len(body) or body[i + 2] == "\n")
                last = display and body[i + 2:].strip() == ""
                if display and eol and not last:
                    pass   # ブロックの行末の \\ は残る
                elif in_table and c == "|":
                    pass   # 表の \| は表のエスケープ（数式には | が渡る）
                else:
                    hint = ESC_HINT.get(c)
                    if c == "\\":
                        hint = "`\\\\` の直後で改行する（ブロックの行末だけ残る）" if display else "ブロックにして `\\\\` を行末に"
                    add(base + i, "M6", f"`\\{c}` の `\\` がエスケープとして消える"
                        + (f"（→ `{hint}`）" if hint and hint.startswith("\\") else f"（→ {hint or '書き換えるか数式の外へ'}）"))
            i += 2
            continue
        i += 1
    for m in RE_MACRO.finditer(body):
        if m.group(1) in DISALLOWED and (m.start() == 0 or body[m.start() - 1] != "\\"):
            add(base + m.start(), "M15", f"`\\{m.group(1)}` は GitHub で許されない（ブロック全体がエラー。→ "
                + ("`\\mathrm{…}`）" if m.group(1) == "operatorname" else "`\\mskip5mu` など）"))
    for m in RE_TEXTMODE.finditer(body):
        for k, c in enumerate(m.group(1)):
            if c in "_^" and (k == 0 or m.group(1)[k - 1] != "\\"):
                add(base + m.start(1) + k, "M16", f"`{m.group()}` の中の `{c}` は GitHub でエラー（→ コードの名前なら数式の外へ）")
                break
    for m in RE_TAG.finditer(body):
        add(base + m.start(), "M8", f"`{m.group()}` が HTML タグとして消える（→ `<` の後に空白か `\\lt`）")
    for m in RE_LINK.finditer(body):
        add(base + m.start(), "M14", "数式の中の `[…](` がリンクになる")
    for m in RE_MENTION.finditer(body):
        add(base + m.start(), "M14", f"数式の中の `{m.group()}` がメンションになる")
    if in_table:
        for k, c in enumerate(body):
            if c == "|" and (k == 0 or body[k - 1] != "\\"):
                add(base + k, "M9", "表の中の `|` がセルを割る（→ `\\vert` / `\\Vert`）")


def check_emphasis(text, spans, add):
    for o, c in emphasis_pairs(text):
        for sp in spans:
            if sp.kind == "backtick":
                continue
            inside = [r for r in (o, c) if sp.start < r["s"] < sp.end]
            if inside:
                r = inside[0]
                hint = "`\\ast`" if r["c"] == "*" else "`_` の後に空白（`_ {…}`。TeX は空白を無視する）"
                add(r["s"], "M7", f"`{r['c'] * r['n']}` が数式の外の `{(c if r is o else o)['c']}` と組になり強調に食われる（→ {hint}）")
            elif o["s"] < sp.start and sp.end <= c["s"] and min(o["n"], c["n"]) == 1:
                add(sp.start, "M7", "斜体の中の数式は表示されない（太字なら可）")


def opener_ok(text, o, in_table, strong_ends):
    """開きの $ の左。行頭・空白・( か、要素の切れ目（コード・タグ・リンク・太字の区切り）。"""
    p = text[o - 1] if o > 0 else "\n"
    if p in " \t\n(\0" or (in_table and p == "|") or o in strong_ends:
        return True
    if text[max(0, o - 2):o] == "~~":
        return True
    if p == ">":
        return re.search(r"<[A-Za-z/][^<>]*>$", text[:o]) is not None
    return p == ")" and re.search(r"\]\([^()\s]*\)$", text[:o]) is not None


def lint_inline(para, in_table, out):
    text, spans = mask_code(para.text)

    def add(pos, rule, msg):
        ln, col = para.where(pos)
        out.append(Finding(ln, col, rule, msg))

    for sp in spans:
        if in_table and "|" in sp.src:
            add(sp.start, "M9", "表の中の `|` は $`…`$ の中でもセルを割る（→ `\\vert` / `\\Vert`）")
    pairs, lone = dollar_pairs(text)
    for o, n in lone:
        add(o, "M13", f"`{'$' * n}` の閉じが無い")
    strong_ends = {r["e"] for pr in emphasis_pairs(text) for r in pr if min(pr[0]["n"], pr[1]["n"]) >= 2}
    links = [(m.start(), m.end()) for m in re.finditer(r"\[([^\[\]]*)\]\(", text)]
    for o, c, n in pairs:
        sp = Span("inline", o, c + n, para.text[o:c + n])
        spans.append(sp)
        body = para.text[o + n:c]
        if any(a < o and c + n < b for a, b in links):
            add(o, "M14", "リンクの文字の中の数式は表示されない")
        if "\0" in text[o + n:c]:
            add(o, "M14", "数式の中のコードスパン（`…`）で数式が切れる")
        if not opener_ok(text, o, in_table, strong_ends):
            add(o, "M1", f"開きの `{'$' * n}` の左が「{text[o - 1]}」（→ 前に空白を入れる。太字の `**` の前なら閉じの `**` の後にも）")
        if body[:1].isspace():
            add(o, "M2", f"開きの `{'$' * n}` の直後が空白")
        if body[-1:].isspace():
            add(c, "M3", f"閉じの `{'$' * n}` の直前が空白")
        nx = text[c + n] if c + n < len(text) else ""
        if nx.isascii() and (nx.isalnum() or nx == "_"):
            add(c, "M4", f"閉じの `{'$' * n}` の直後が「{nx}」（→ 空白を入れる）")
        if "\n" in body:
            add(o, "M5", "インライン数式が行をまたぐ")
        check_content(body, o + n, False, in_table, add)
    check_emphasis(text, spans, add)
    return spans


def lint_display(para, out):
    text, _ = mask_code(para.text)

    def add(pos, rule, msg):
        ln, col = para.where(pos)
        out.append(Finding(ln, col, rule, msg))

    o = para.text.index("$$")
    c = para.text.rindex("$$")
    body = para.text[o + 2:c]
    check_content(body, o + 2, True, False, add)
    sp = Span("display", o, c + 2, para.text[o:c + 2])
    check_emphasis(text, [sp], add)
    return [sp]


def split_lines(lines, math_fences):
    """各行を (種別, 内容の列, 内容, リスト内か, 行頭にリスト記号か) にする。"""
    info = []
    fence = None
    comment = False
    in_list = False
    prev_blank = True
    for ln in lines:
        if comment:
            info.append(("skip", 0, "", in_list, False))
            if "-->" in ln:
                comment = False
            continue
        m = RE_FENCE.match(ln)
        if fence:
            if m and m.group(2)[0] == fence[0] and len(m.group(2)) >= len(fence) and ln[m.end():].strip() == "":
                fence = None
            info.append(("skip", 0, "", in_list, False))
            continue
        if m:
            fence = m.group(2)
            if m.group(3).strip().startswith("math"):
                math_fences.append(len(info))
            info.append(("skip", 0, "", in_list, False))
            continue
        if "<!--" in ln and "-->" not in ln.split("<!--", 1)[1]:
            comment = True
        pm = RE_PREFIX.match(ln)
        marker = pm.group(2) is not None
        content = ln[pm.end():]
        if marker and not content.strip() and not prev_blank:
            marker = False   # 空の項目は段落を割り込めない（続きの行）
            content = ln[len(pm.group(1)):]
        blank = content.strip() == "" and not marker
        indent = len(ln) - len(ln.lstrip())
        if marker:
            in_list = True
        elif not blank and indent == 0 and prev_blank and not ln.lstrip().startswith(">"):
            in_list = False
        kind = "blank" if blank else "text"
        if not blank and content.startswith("|"):
            kind = "table"
        elif not blank and RE_HEADING.match(content):
            kind = "heading"
        info.append((kind, pm.end(), content, in_list, marker))
        prev_blank = blank
    return info


def split_cells(row):
    """表の行を `|` で切る。`\\|` はセルを割らない（コードスパンの中の `|` は割る）。"""
    cells, cur, i = [], "", 0
    while i < len(row):
        if row[i] == "\\" and i + 1 < len(row) and row[i + 1] == "|":
            cur += row[i:i + 2]
            i += 2
            continue
        if row[i] == "|":
            cells.append(cur)
            cur = ""
        else:
            cur += row[i]
        i += 1
    cells.append(cur)
    s = row.strip()
    if s.startswith("|"):
        cells = cells[1:]
    if s.endswith("|") and not s.endswith("\\|"):
        cells = cells[:-1]
    return cells


def table_aligns(info):
    """表の各行（区切り行を除く）について、列ごとの寄せ（"left"・"right"・"center"・None）を返す。"""
    aligns = {}
    n = len(info)
    i = 0
    while i < n:
        if info[i][0] != "table":
            i += 1
            continue
        j = i
        while j < n and info[j][0] == "table":
            j += 1
        if j - i >= 2:
            delim = [RE_DELIM_CELL.match(c) for c in split_cells(info[i + 1][2])]
            if delim and all(delim):
                cols = [{("", ""): None, (":", ""): "left", ("", ":"): "right", (":", ":"): "center"}[m.groups()]
                        for m in delim]
                for k in range(i, j):
                    if k != i + 1:
                        aligns[k] = cols
        i = j
    return aligns


def column_of(text, pos):
    """表の行の pos が何列目か（0 始まり）。先頭の `|` の前なら -1。"""
    count, i = 0, 0
    while i < pos:
        if text[i] == "\\" and i + 1 < len(text) and text[i + 1] == "|":
            i += 2
            continue
        if text[i] == "|":
            count += 1
        i += 1
    return count - 1 if text.lstrip().startswith("|") else count


def lint_text(src):
    lines = src.split("\n")
    math_fences = []
    info = split_lines(lines, math_fences)
    aligns = table_aligns(info)
    out, paras = [], []
    for i, ln in enumerate(lines):
        for m in RE_CTRL.finditer(ln):
            c = m.group()
            esc = CTRL_ESC.get(c)
            out.append(Finding(i + 1, m.start() + 1, "M17", f"制御文字 U+{ord(c):04X} がある"
                               + (f"（raw でない文字列の `\\{esc}` がエスケープとして効いた跡かも。→ `\\\\{esc}` か r\"…\" に）" if esc else "")))
        hits = {m.start(): "t" for m in RE_TAB_MACRO.finditer(ln)}
        hits.update({m.start(): "r" for m in RE_CR_MACRO.finditer(ln)})
        for m in RE_LONE_CR.finditer(ln):
            hits.setdefault(m.start(), "")
        for col, esc in sorted(hits.items()):
            c = ln[col]
            out.append(Finding(i + 1, col + 1, "M17", f"制御文字 U+{ord(c):04X} がある"
                               + (f"（raw でない文字列の `\\{esc}` がエスケープとして効いた跡かも。→ `\\\\{esc}` か r\"…\" に）" if esc
                                  else "（行末でない CR）")))
    used = [False] * len(lines)
    n = len(lines)
    # ブロック数式（$$ で始まり、同じ行で閉じない）
    for i in range(n):
        kind, c0, content, in_list, marker = info[i]
        if used[i] or kind != "text":
            continue
        s = content.strip()
        if not s.startswith("$$") or "$$" in s[2:]:
            continue
        j = i + 1
        while j < n and info[j][0] != "skip" and "$$" not in info[j][2]:
            j += 1
        if j >= n or info[j][0] == "skip":
            out.append(Finding(i + 1, c0 + 1, "M13", "閉じの `$$` が無い"))
            continue
        for k in range(i, j + 1):
            used[k] = True
        pi = info[i - 1] if i > 0 else ("blank",)
        if pi[0] == "text" and not pi[2].rstrip().endswith("$$"):
            out.append(Finding(i, 1, "M10", "ブロック数式の前に空行が要る"))
        tail = info[j][2].split("$$", 1)[1].strip()
        if tail:
            out.append(Finding(j + 1, c0 + 1, "M10", f"閉じの `$$` の後ろに「{tail[:10]}」がある（→ 改行する）"))
        ni = info[j + 1] if j + 1 < n else ("blank",)
        if ni[0] == "text" and not ni[4] and not ni[2].strip().startswith("$$"):
            out.append(Finding(j + 2, 1, "M10", "ブロック数式の後に空行が要る"))
        if in_list:
            out.append(Finding(i + 1, c0 + 1, "M12", "箇条書きの中の複数行の `$$` は表示されない（→ 1 行の `$$…$$` に）"))
        for k in range(i + 1, j + 1):
            kk, ck, ct, _, mk = info[k]
            raw = lines[k].lstrip()
            if k < j and kk == "blank":
                out.append(Finding(k + 1, 1, "M11", "ブロック数式の中の空行で段落が切れる"))
            elif mk or RE_BLOCKISH.match(raw.lstrip(">").lstrip() if raw.startswith(">") and lines[i].lstrip().startswith(">") else raw):
                if not raw.startswith("$$"):
                    out.append(Finding(k + 1, len(lines[k]) - len(raw) + 1, "M11",
                                       f"行頭の「{raw[:3].strip()}」が Markdown の構造になる（→ 前に `{{}}` を置く）"))
        rows = [(i, c0, content)]
        for k in range(i + 1, j + 1):   # 続きの行は箇条書きの記号を剥がさない（数式の中身）
            q = RE_QUOTE.match(lines[k]).end()
            rows.append((k, q, lines[k][q:]))
        paras.append(("display", Para(rows)))
    # 残りを段落に束ねる
    cur = []

    def flush():
        if cur:
            paras.append(("inline", Para(list(cur))))
            cur.clear()

    for i in range(n):
        kind, c0, content, _, marker = info[i]
        if used[i] or kind in ("skip", "blank"):
            flush()
            continue
        if kind in ("table", "heading"):
            flush()
            paras.append((kind, Para([(i, c0, content)])))
            continue
        if marker:
            flush()
        cur.append((i, c0, content))
    flush()
    spans = [((k + 1, 0), Span("fence", 0, 0, "")) for k in math_fences]
    for kind, p in paras:
        found = []
        if kind == "display":
            sp = lint_display(p, found)
        else:
            sp = lint_inline(p, kind == "table", found)
            cols = aligns.get(p.rows[0][0]) if kind == "table" else None
            for s in sp if cols else ():
                k = column_of(p.text, s.start)
                if s.kind == "inline" and 0 <= k < len(cols) and cols[k] in ("right", "center"):
                    ln, col = p.where(s.start)
                    word = "右寄せ" if cols[k] == "right" else "中央寄せ"
                    found.append(Finding(ln, col, "M18", f"{word}の列の数式は iOS Safari で先頭しか表示されない（→ 列を左寄せ `---` に）"))
        for s in sp:
            s.pos, s.endpos = p.where(s.start), p.where(s.end)
            spans.append((s.pos, s))
        out += found
    out.sort(key=lambda f: (f.line, f.col, f.rule))
    spans.sort(key=lambda x: x[0])
    return out, [s for _, s in spans]


# ---- GitHub との突き合わせ --------------------------------------------------

def norm(s):
    s = s.replace("<br>", "")
    for _ in range(2):
        s = html.unescape(s)
    return re.sub(r"\s+", " ", s).strip()


def github_ok(src, rendered):
    """数式の候補がすべて、中身を変えずに math-renderer になったか。"""
    _, spans = lint_text(src)
    got = re.findall(r"<math-renderer[^>]*>(.*?)</math-renderer>", rendered, re.S)
    rest = re.sub(r"<math-renderer.*?</math-renderer>|<code.*?</code>", "", rendered, flags=re.S)
    if "$" in rest:
        return False   # 数式にならずに残った $
    if len(got) != len(spans):
        return False
    return all(s.kind == "fence" or norm(g) == norm(s.src.replace("$`", "$").replace("`$", "$"))
               for g, s in zip(got, spans))


def render_github(cases):
    src = "\n\n".join(f"QQCASE{i}QQ\n\n{c}" for i, c in enumerate(cases))
    req = urllib.request.Request(
        "https://api.github.com/markdown", data=json.dumps({"text": src, "mode": "gfm"}).encode(),
        headers={"Content-Type": "application/json", "Accept": "application/vnd.github+json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        body = r.read().decode()
    parts = re.split(r"<p[^>]*>QQCASE(\d+)QQ</p>", body)
    return {int(parts[k]): parts[k + 1] for k in range(1, len(parts), 2)}


def run_cases(live):
    data = json.loads(files("mdguard").joinpath("cases.json").read_text(encoding="utf-8"))
    cases = data["cases"]
    # 閉じない HTML タグは後ろの例を巻き込むので、タグを含む例は最後に回す
    order = sorted(range(len(cases)), key=lambda i: RE_TAG.search(cases[i]["src"]) is not None)
    if live:
        got = render_github([cases[i]["src"] for i in order])
    bad = 0
    for pos, i in enumerate(order):
        cs = cases[i]
        found, _ = lint_text(cs["src"])
        lint_ok = not found
        if live and not cs.get("api_blind"):
            gh = github_ok(cs["src"], got.get(pos, ""))
        else:
            gh = cs["github_ok"]   # api_blind はブラウザーでの目視結果
        msg = []
        if live and gh != cs["github_ok"]:
            msg.append(f"GitHub が変わった（記録 {cs['github_ok']} → 今 {gh}）")
        if lint_ok != gh:
            msg.append(f"検査 {'OK' if lint_ok else 'NG'} / GitHub {'OK' if gh else 'NG'}"
                       + "".join(f" [{f.rule} {f.msg}]" for f in found))
        if msg:
            bad += 1
            print(f"✗ {cs['src']!r}: " + "; ".join(msg))
    teeth = sum(1 for c in cases if not c["github_ok"])
    print(f"{len(cases) - bad}/{len(cases)} 一致（GitHub で壊れる例 {teeth}、保存した記録"
          + ("、今の GitHub で取り直し" if live else "") + "）")
    return 1 if bad else 0


def check(inputs, *, ignore='', select='', summary=False):
    ign = set(filter(None, ignore.split(",")))
    sel = set(filter(None, select.split(",")))
    total = {}
    unread = 0
    for name, path in inputs:
        try:
            # CRLF だけを LF にする。read_text の改行の変換は単独の CR も改行にするので、
            # raw でない "\rho" などの跡（行の途中の CR）が M17 で見つからなくなる
            raw = sys.stdin.buffer.read() if path is None else path.read_bytes()
            src = raw.decode("utf-8").replace("\r\n", "\n")
        except (OSError, UnicodeDecodeError) as e:
            print(f"{name}: 読めない（{e}）", file=sys.stderr)
            unread += 1  # ★ 読めないファイルも不合格（黙って飛ばすと検査が消える）
            continue
        found, _ = lint_text(src)
        for x in found:
            if x.rule in ign or (sel and x.rule not in sel):
                continue
            total[x.rule] = total.get(x.rule, 0) + 1
            if not summary:
                print(f"{name}:{x.line}:{x.col}: {x.rule} {x.msg}")
    if summary or total:
        key = lambda r: int(r[1:])
        print("計 " + "  ".join(f"{r} {total[r]}" for r in sorted(total, key=key)) if total else "計 0", file=sys.stderr)
    return 1 if total or unread else 0
