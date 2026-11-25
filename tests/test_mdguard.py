import io
import json
from importlib.resources import files
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from mdguard.math import lint_text, render_github, run_cases
from mdguard.selftest import seed_checks


class MathTests(unittest.TestCase):
    def test_recorded_display_cases(self):
        # Use the installed fixture, which is also read by the public selftest.
        example_table = Path(__file__).with_name("cases.json").read_text(encoding="utf-8")
        self.assertEqual(example_table, files("mdguard").joinpath("cases.json").read_text(encoding="utf-8"))
        data = json.loads(example_table)
        self.assertEqual(len(data["cases"]), 340)
        for case in data["cases"]:
            with self.subTest(src=case["src"]):
                self.assertEqual(not lint_text(case["src"])[0], case["github_ok"])

    def test_control_characters(self):
        def found(src):
            return [(f.line, f.col, f.rule, f.msg) for f in lint_text(src)[0]]

        bel = found("a $\\frac\x07lpha$ b\n")   # raw でない "\alpha" の跡（数式の中）
        self.assertEqual([x[:3] for x in bel], [(1, 9, "M17")])
        self.assertIn("U+0007", bel[0][3])
        self.assertIn("`\\a`", bel[0][3])
        bs = found("x\n\x08eta の値\n")   # 数式の外
        self.assertEqual([x[:3] for x in bs], [(2, 1, "M17")])
        self.assertIn("U+0008", bs[0][3])
        self.assertIn("`\\b`", bs[0][3])
        self.assertNotIn("raw", found("a\x1fb\n")[0][3])
        self.assertEqual([x[:3] for x in found("a\x7f $x$ \x00\n")], [(1, 2, "M17"), (1, 8, "M17")])
        self.assertEqual(found("a\t$x$\tb\n\tc\n"), [])   # TAB は可
        self.assertEqual(found("a $x$ b\r\n\r\n$$\r\ny\r\n$$\r\n"), [])   # CRLF は可
        # raw でない "\tanh"・"\thinspace"・"\rho"・"\rvert" の跡（TAB・CR にマクロの残りが続く）
        tab = found("$1 - \tanh x$ と $a\thinspace b$\n")
        self.assertEqual([x[:3] for x in tab], [(1, 6, "M17"), (1, 18, "M17")])
        self.assertIn("U+0009", tab[0][3])
        self.assertIn("`\\t`", tab[0][3])
        cr = found("$a\rho$ と $\\lvert k\rvert$\n")
        self.assertEqual([x[:3] for x in cr], [(1, 3, "M17"), (1, 19, "M17")])
        self.assertIn("`\\r`", cr[0][3])
        self.assertEqual([x[:3] for x in found("a\rb\n")], [(1, 2, "M17")])   # 行末でない CR
        self.assertEqual(found("\ttext を字下げ\n|\ta\t|\n"), [])   # 字下げ・区切りの TAB で、マクロの残りが続かないもの

    def test_github_requires_opt_in(self):
        with patch("mdguard.math.render_github") as render, patch("sys.stdout"):
            self.assertEqual(run_cases(live=False), 0)
            render.assert_not_called()


    def test_render_github_request_and_case_mapping(self):
        html = b"<p>QQCASE0QQ</p><math-renderer>x</math-renderer><p>QQCASE1QQ</p><p>plain</p>"
        with patch("mdguard.math.urllib.request.urlopen", return_value=io.BytesIO(html)) as open_url:
            self.assertEqual(render_github(["$x$", "plain"]),
                             {0: "<math-renderer>x</math-renderer>", 1: "<p>plain</p>"})
        (request,), kwargs = open_url.call_args
        self.assertEqual(request.full_url, "https://api.github.com/markdown")
        self.assertEqual(request.get_method(), "POST")
        self.assertEqual(kwargs, {"timeout": 30})
        self.assertEqual(json.loads(request.data), {"text": "QQCASE0QQ\n\n$x$\n\nQQCASE1QQ\n\nplain", "mode": "gfm"})


class CliTests(unittest.TestCase):
    def setUp(self):
        temp = TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name).resolve()

    def write(self, name, text=""):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    def git(self, *args):
        subprocess.run(["git", *args], cwd=self.root, capture_output=True, check=True)

    def cmd(self, *args, input=None, cwd=None):
        return subprocess.run([sys.executable, "-m", "mdguard", *args], cwd=cwd or self.root,
                              input=input, capture_output=True, text=True, check=False)

    def test_doc_seed(self):
        self.assertEqual(seed_checks(self.root), ([], []))

    def test_repo_untracked_ignored_removed_and_under(self):
        self.git("init", "-q")
        self.write(".gitignore", "component/ignored.md\n")
        self.write(".mdguard.toml", '[math]\npaths = ["component/*.md", "component-other/*.md", "component.md"]\n')
        self.write("component/tracked.md", "$x$\n")
        self.write("component/removed.md", "$x$\n")
        self.write("component/forced.md", "$x$\n")
        self.git("add", "component")
        self.write(".gitignore", "component/ignored.md\ncomponent/forced.md\n")
        (self.root / "component/removed.md").unlink()
        self.write("component/deep/新しい file.md", "値$x$\n")
        self.write("component/ignored.md", "値$x$\n")
        self.write("component-other/other.md", "値$x$\n")
        self.write("component.md", "値$x$\n")
        listing = self.cmd("math", "--repo", "--under", "component", "--list")
        self.assertEqual((listing.returncode, listing.stderr), (0, ""))
        self.assertEqual(listing.stdout.splitlines(),
                         ["component/deep/新しい file.md", "component/forced.md", "component/tracked.md"])
        checked = self.cmd("math", "--repo", "--under", "component")
        self.assertEqual(checked.returncode, 1)
        self.assertIn("component/deep/新しい file.md:1:2: M1 ", checked.stdout)
        self.assertEqual(checked.stderr, "計 M1 1\n")
        empty = self.cmd("math", "--repo", "--under", "absent", "--list")
        self.assertEqual((empty.returncode, empty.stdout), (1, ""))
        self.assertIn("対象の md が 0 本", empty.stderr)

    def test_math_stdin_summary_and_explicit_files(self):
        failing = self.cmd("math", "-", input="値$x$\n")
        self.assertEqual(failing.returncode, 1)
        self.assertTrue(failing.stdout.startswith("-:1:2: M1 "))
        self.assertEqual(failing.stderr, "計 M1 1\n")
        ignored = self.cmd("math", "--ignore", "M1", "--summary", "-", input="値$x$\n")
        self.assertEqual((ignored.returncode, ignored.stdout, ignored.stderr), (0, "", "計 0\n"))
        self.write("folder/with spaces.md", "$x$\n")
        self.assertEqual(self.cmd("math", "folder", "--list").stdout, "folder/with spaces.md\n")
        missing = self.cmd("math", "missing.md")
        self.assertEqual(missing.returncode, 1)
        self.assertIn("missing.md: 読めない", missing.stderr)

    def test_links_ignore_missing_directories_and_closed_records(self):
        self.git("init", "-q")
        self.write(".gitignore", "/ignored/\n")
        self.write("guides/README.md", "[ignored](../ignored) [nested](../ignored/file.md) [anchor](#local)\n")
        self.write("records/closed/archive.md", "[missing](gone.md)\n")
        self.write("records/current.md", "[missing](gone.md#anchor)\n")
        self.git("add", ".")
        self.write("untracked.md", "[missing](gone.md)\n")
        self.assertEqual(self.cmd("links", ".").stdout, "records/closed/archive.md: gone.md\nrecords/current.md: gone.md\n")
        self.write(".mdguard.toml", '[links]\npaths = ["guides/**/*.md", "records/**/*.md", "untracked.md"]\n'
                   'exclude = ["records/closed/**/*.md"]\n')
        result = self.cmd("links", ".")
        self.assertEqual((result.returncode, result.stdout, result.stderr), (0, "records/current.md: gone.md\nuntracked.md: gone.md\n", ""))

    def test_doc_sources_sort_by_full_path(self):
        self.write("guides/a/item.md", "[missing](gone.md)\n")
        self.write("guides/a-.md", "[missing](gone.md)\n")
        self.assertEqual(self.cmd("index", ".").stdout, "")
        self.write(".mdguard.toml", '[index]\nrules = [{base="guides", glob="**/*.md", index="nearest-readme"}]\n')
        result = self.cmd("index", ".")
        self.assertEqual(result.stdout.splitlines(), [
            "guides/a-.md: 索引 guides/README.md が無い",
            "guides/a/item.md: 索引 guides/README.md が無い",
        ])
        self.assertEqual(self.cmd("links", ".").stdout.splitlines(), [
            "guides/a-.md: gone.md", "guides/a/item.md: gone.md",
        ])
        self.write("guides/README.md", "a-.md item.md\n")
        self.write("guides/a/README.md")
        self.assertEqual(self.cmd("index", ".").stdout, "guides/a/item.md: guides/a/README.md に載っていない\n")

    def test_links_explicit_config_resolves_allowance_from_checked_root(self):
        self.write("project/guides/source.md", "[external](../../assets/sample.md)\n")
        self.write("settings/check.toml", '[links]\npaths=["guides/*.md"]\nexternal_allow="config/allow.txt"\n')
        self.write("project/config/allow.txt", f"{self.root}/assets/ ### 1 ### Fixture\n")
        self.assertIn("未許可", self.cmd("links", "project").stdout)
        checked = self.cmd("links", "project", "--config", "settings/check.toml")
        self.assertEqual((checked.returncode, checked.stdout, checked.stderr), (0, "", ""))

    def test_ratchet_config_counts_matching_lines_or_matches(self):
        self.write("guides/a.md", "TODO TODO\nTODO\n")
        self.write("other/a.md", "TODO\n")
        self.write("limits.txt", "lines 0\nmatches 0\n")
        self.assertEqual(self.cmd("ratchet", ".", "limits.txt").returncode, 2)
        self.write(".mdguard.toml", """
[ratchet.metrics.lines]
paths = ["guides/**/*.md", "guides/a.md"]
pattern = 'TODO'
[ratchet.metrics.matches]
paths = ["guides/**/*.md"]
pattern = 'T(OD)O'
count = "matches"
""")
        checked = self.cmd("ratchet", ".", "limits.txt")
        self.assertEqual((checked.returncode, checked.stderr), (0, ""))
        self.assertEqual(checked.stdout.splitlines(), [
            "lines: 2 が上限 0 を越えた",
            "matches: 3 が上限 0 を越えた",
        ])
        self.write(".mdguard.toml", "[ratchet.metrics.lines]\npaths=['*.md']\npattern='['\n")
        invalid = self.cmd("ratchet", ".", "limits.txt")
        self.assertEqual(invalid.returncode, 2)
        self.assertIn("ratchet.metrics.lines.pattern", invalid.stderr)

    def test_run_config_and_detail_limit(self):
        self.git("init", "-q")
        self.write("settings/custom.toml", '[math]\npaths = ["doc/*.md"]\n[run]\n'
                   'name = "文書"\nexempt = "exempt.txt"\nratchet = "limits.txt"\nmath_under = "."\n'
                   '[links]\npaths = ["doc/**/*.md"]\n'
                   '[ratchet.metrics.markers]\npaths = ["doc/**/*.md"]\npattern = "TODO"\n')
        self.write("settings/exempt.txt", "doc/a.md 試験\n")
        self.write("settings/limits.txt", "markers 0\n")
        self.write("doc/a.md", "$x$\n")
        explicit = ("--config", "settings/custom.toml")
        checked = self.cmd(*explicit, "run", ".")
        self.assertEqual((checked.returncode, checked.stderr), (0, ""))
        lines = checked.stdout.splitlines()
        self.assertEqual(len(lines), 4)
        self.assertTrue(all(line.startswith("OK  ") for line in lines))
        self.assertIn("文書", lines[0])
        self.write("doc/README.md", "a.md\n" + "".join(f"[broken](gone{i}.md)\n" for i in range(12)))
        self.write("doc/a.md", "値$x$\n")
        checked = self.cmd("run", ".", *explicit, "--name", "上書き")
        self.assertEqual((checked.returncode, checked.stderr), (1, ""))
        self.assertIn("NG  壊れた相対リンクがある（上書き: 12 件）", checked.stdout)
        self.assertIn("    doc/README.md: gone9.md\n", checked.stdout)
        self.assertNotIn("gone10.md", checked.stdout)
        self.assertIn("NG  文書の数式", checked.stdout)
        self.assertIn("    計 M1 1\n    doc/a.md:1:2: M1 ", checked.stdout)

    def test_run_reports_index_and_ratchet_failures(self):
        self.write("doc/new.md", "## 2020-01-01\n")
        self.write(".mdguard.toml", '[index]\nrules = [{base="doc", glob="**/*.md", index="nearest-readme"}]\n'
                   '[ratchet.metrics.date_headings]\npaths = ["doc/**/*.md"]\npattern = "2020-01-01"\n')
        self.write("limits.txt", "date_headings 0\n")
        checked = self.cmd("run", ".", "--name", "文書", "--ratchet", "limits.txt")
        self.assertEqual((checked.returncode, checked.stderr), (1, ""))
        self.assertIn("NG  文書の索引の点呼（文書）が合わない（1 件）", checked.stdout)
        self.assertIn("    doc/new.md: 索引 doc/README.md が無い", checked.stdout)
        self.assertIn("NG  文書のラチェットを越えた（文書）", checked.stdout)
        self.assertIn("    date_headings: 1 が上限 0 を越えた", checked.stdout)

    def test_child_config_inherits_repo_math(self):
        self.git("init", "-q")
        self.write(".mdguard.toml", '[math]\npaths = ["docs/*.md", "project/*.md"]\n')
        self.write("project/.mdguard.toml", '[run]\nname = "Project"\nmath_under = "project"\n')
        self.write("project/README.md", "$x$\n")
        self.write("docs/README.md", "値$x$\n")
        checked = self.cmd("run", "project")
        self.assertEqual((checked.returncode, checked.stderr), (0, ""))
        self.assertEqual(len(checked.stdout.splitlines()), 3)
        listing = self.cmd("math", "--repo", "--list", cwd=self.root / "project")
        self.assertEqual(listing.stdout, "docs/README.md\nproject/README.md\n")
