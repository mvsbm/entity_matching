"""Shared settings from config/settings.toml: paths, datasets, schema and standardization, validated on load."""
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import get_args

from er.config import Data, Derived, Normalizer, Standardization


@dataclass(frozen=True)
class Settings:
    root: Path                                # project root; every path below is resolved against it
    paths: dict[str, Path]
    data: Data
    standardize: Standardization


def project_root(start: Path | None = None) -> Path:
    """The nearest folder at or above `start` (default: the working folder) that holds pyproject.toml."""
    here = (start or Path.cwd()).resolve()
    for folder in (here, *here.parents):
        if (folder / "pyproject.toml").exists():
            return folder
    raise FileNotFoundError(f"no pyproject.toml at or above {here}")


def load_settings(path: Path | None = None) -> Settings:
    root = project_root(Path(path).parent if path else None)
    cfg = tomllib.loads((Path(path) if path else root / "config" / "settings.toml").read_text(encoding="utf-8"))
    paths = {name: root / rel for name, rel in cfg["paths"].items()}

    s = cfg["standardize"]
    assert len(s["kana_fold_from"]) == len(s["kana_fold_to"]), "kana_fold_from / kana_fold_to must align character by character"
    derived = tuple(Derived(name=d["name"], sources=tuple(map(tuple, d["sources"])), normalize=tuple(d.get("normalize", ())))
                    for d in s["derived"])
    assert len({d.name for d in derived}) == len(derived), "duplicate derived column names"
    unknown = {n for d in derived for n in d.normalize} - set(get_args(Normalizer))
    assert not unknown, f"unknown normalizers: {unknown}"

    return Settings(
        root=root,
        paths=paths,
        data=Data(silver_dir=paths["silver"], labels_dir=paths["labels"], gold_dir=paths["gold"],
                  artifacts_dir=paths["artifacts"], experiments_dir=paths["experiments"], models_dir=paths["models"],
                  datasets=tuple(cfg["datasets"]["all"]), unique_id=cfg["schema"]["unique_id"], entity_id=cfg["schema"]["entity_id"],
                  show_rows=cfg["display"]["show_rows"]),
        standardize=Standardization(kana_fold=dict(zip(s["kana_fold_from"], s["kana_fold_to"])),
                                    legal_forms=tuple(s["legal_forms"]), prefectures=tuple(s["prefectures"]),
                                    address_replacements=tuple(map(tuple, s["address_replacements"])),
                                    address_cut_at=s["address_cut_at"], derived=derived),
    )
