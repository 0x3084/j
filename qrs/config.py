"""Central paths and configuration loading."""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = Path(os.environ.get("QRS_DATA_DIR", ROOT / "data"))
RAW_DIR = DATA_DIR / "raw"
PROC_DIR = DATA_DIR / "processed"
PAPER_DIR = DATA_DIR / "paper"
CONFIG_DIR = ROOT / "configs"
REPORT_DIR = ROOT / "reports"

for _d in (RAW_DIR, PROC_DIR, PAPER_DIR, REPORT_DIR):
    _d.mkdir(parents=True, exist_ok=True)


@lru_cache(maxsize=None)
def load_yaml(name: str) -> dict:
    with open(CONFIG_DIR / name) as f:
        return yaml.safe_load(f)


def universe() -> dict:
    return load_yaml("universe.yaml")


def etf_specs() -> dict[str, dict]:
    """Per-ETF spec with defaults merged in."""
    u = universe()["etf"]
    out = {}
    for sym, spec in u["instruments"].items():
        s = dict(u["defaults"])
        s.update(spec or {})
        out[sym] = s
    return out


def crypto_specs() -> dict:
    return universe()["crypto"]
