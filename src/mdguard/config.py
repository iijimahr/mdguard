"""設定の探索と、TOML の値から CLI の既定値への変換。"""

from dataclasses import dataclass
from pathlib import Path
import re
import tomllib


@dataclass(frozen=True)
class IndexRule:
    base: Path
    glob: str
    index: str
    label: str
    hidden: bool


@dataclass(frozen=True)
class Metric:
    paths: list[str]
    pattern: re.Pattern
    count: str
    follow_symlinks: bool


class Config:
    def __init__(self, path=None):
        self.path = path
        self.data = {}
        if path is not None:
            with path.open("rb") as config:
                self.data = tomllib.load(config)

    def get(self, section, key, kind):
        table = self.table(self.data, section)
        value = table.get(key)
        if value is not None and (
            not isinstance(value, kind) or not value
            or (kind is list and not all(isinstance(item, str) and item for item in value))
        ):
            expected = "文字列の配列" if kind is list else "文字列"
            raise ValueError(f"{self.path}: {section}.{key} は空でない{expected}で指定する")
        return value

    def table(self, parent, key):
        table = parent.get(key, {})
        if not isinstance(table, dict):
            raise ValueError(f"{self.path}: [{key}] はテーブルで指定する")
        return table

    def relative(self, value, key):
        if isinstance(value, str) and value:
            path = Path(value)
            if not path.is_absolute() and ".." not in path.parts:
                return path
        raise ValueError(f"{self.path}: {key} は検査する根の配下の相対パスで指定する")

    def globs(self, values, key):
        if not isinstance(values, list):
            raise ValueError(f"{self.path}: {key} は glob の配列で指定する")
        for value in values:
            self.relative(value, key)
        return values

    def flag(self, table, key, default):
        value = table.get(key, default)
        if not isinstance(value, bool):
            raise ValueError(f"{self.path}: {key} は真偽値で指定する")
        return value

    def index_rules(self):
        rows = self.table(self.data, "index").get("rules", [])
        if not isinstance(rows, list) or not all(isinstance(row, dict) for row in rows):
            raise ValueError(f"{self.path}: index.rules はテーブルの配列で指定する")
        rules = []
        for row in rows:
            base = self.relative(row.get("base", "."), "index.rules.base")
            pattern = row.get("glob")
            self.relative(pattern, "index.rules.glob")
            index = row.get("index")
            if index != "nearest-readme":
                self.relative(index, "index.rules.index")
            label = row.get("label", (base / pattern).as_posix())
            if not isinstance(label, str) or not label:
                raise ValueError(f"{self.path}: index.rules.label は空でない文字列で指定する")
            rules.append(IndexRule(base, pattern, index, label, self.flag(row, "hidden", True)))
        return rules

    def link_paths(self):
        table = self.table(self.data, "links")
        paths = self.globs(table["paths"], "links.paths") if "paths" in table else None
        return paths, self.globs(table.get("exclude", []), "links.exclude")

    def external_allow(self):
        value = self.get("links", "external_allow", str)
        return self.relative(value, "links.external_allow") if value is not None else None

    def metrics(self):
        rows = self.table(self.table(self.data, "ratchet"), "metrics")
        metrics = {}
        for name in rows:
            key = f"ratchet.metrics.{name}"
            row = self.table(rows, name)
            if not name or any(char.isspace() for char in name) or name.startswith("#"):
                raise ValueError(f"{self.path}: 指標名 {name!r} は上限ファイルの先頭列に書けない")
            paths = self.globs(row.get("paths"), f"{key}.paths")
            count = row.get("count", "lines")
            if count not in ("lines", "matches"):
                raise ValueError(f"{self.path}: {key}.count は lines または matches で指定する")
            pattern = row.get("pattern")
            if not isinstance(pattern, str):
                raise ValueError(f"{self.path}: {key}.pattern は正規表現の文字列で指定する")
            try:
                compiled = re.compile(pattern)
            except re.error as exc:
                raise ValueError(f"{self.path}: {key}.pattern: {exc}") from exc
            metrics[name] = Metric(paths, compiled, count, self.flag(row, "follow_symlinks", False))
        return metrics

    def run_path(self, key):
        value = self.get("run", key, str)
        return self.path.parent / value if value is not None else None


def load_config(start, top, explicit=None):
    if explicit is not None:
        return Config(Path(explicit).absolute())
    for directory in (start, *start.parents):
        path = directory / ".mdguard.toml"
        if path.is_file():
            return Config(path)
        if top is None or directory == top:
            break
    return Config()
