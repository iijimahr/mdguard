"""設定の探索と、TOML の値から CLI の既定値への変換。"""

from pathlib import Path
import tomllib


class Config:
    def __init__(self, path=None):
        self.path = path
        self.data = {}
        if path is not None:
            with path.open("rb") as config:
                self.data = tomllib.load(config)

    def get(self, section, key, kind):
        table = self.data.get(section, {})
        if not isinstance(table, dict):
            raise ValueError(f"{self.path}: [{section}] はテーブルで指定する")
        value = table.get(key)
        if value is not None and (
            not isinstance(value, kind) or not value
            or (kind is list and not all(isinstance(item, str) and item for item in value))
        ):
            expected = "文字列の配列" if kind is list else "文字列"
            raise ValueError(f"{self.path}: {section}.{key} は空でない{expected}で指定する")
        return value

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
