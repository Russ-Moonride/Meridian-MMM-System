"""
app/data.py
~~~~~~~~~~~
File I/O layer for the Dash app.
Reads from outputs/{client_id}/ and configs/.
All paths resolve relative to the repository root regardless of working directory.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd
import yaml

REPO_ROOT = Path(__file__).parent.parent
CONFIGS_DIR = REPO_ROOT / "configs"

# Channel color palette — shared across all pages
CHANNEL_COLORS: dict[str, str] = {
    "Baseline":   "#ADB5BD",
    "Brand":      "#4C72B0",
    "Non_Brand":  "#55A868",
    "DVD":        "#C44E52",
    "Retargeting": "#8172B2",
    "Prospecting": "#CCB974",
    "Shopping":   "#64B5CD",
    "Amazon":     "#FF7F0E",
    "Facebook":   "#3B5998",
    "Instagram":  "#E1306C",
    "YouTube":    "#CC0000",
}


# ── Internal ──────────────────────────────────────────────────────────────────

def _all_configs() -> dict[str, tuple[dict, Path]]:
    """Scan configs/ and return {client_id: (config_dict, yaml_path)}."""
    result: dict[str, tuple[dict, Path]] = {}
    for path in sorted(CONFIGS_DIR.glob("*.yaml")):
        try:
            with open(path) as f:
                cfg = yaml.safe_load(f)
            if cfg and "client_id" in cfg:
                result[cfg["client_id"]] = (cfg, path)
        except Exception:
            pass
    return result


def _output_dir(client_id: str) -> Path:
    """Resolve the output directory for a client from its config."""
    configs = _all_configs()
    if client_id in configs:
        cfg, _ = configs[client_id]
        return REPO_ROOT / cfg.get("output_path", f"outputs/{client_id}")
    return REPO_ROOT / "outputs" / client_id


# ── Public API ────────────────────────────────────────────────────────────────

def list_clients() -> list[dict[str, Any]]:
    """Return all configured clients with their status info."""
    clients = []
    for client_id, (cfg, _) in _all_configs().items():
        clients.append({
            "client_id": client_id,
            "config": cfg,
            "status": get_status(client_id),
        })
    return clients


def get_status(client_id: str) -> dict[str, Any]:
    """Load status.json, or return a no-run placeholder."""
    path = _output_dir(client_id) / "status.json"
    if path.exists():
        with open(path) as f:
            return json.load(f)
    return {"status": "no_run", "client_id": client_id}


def get_contributions(client_id: str) -> pd.DataFrame | None:
    """Load contributions.csv. Returns None if no model run exists."""
    path = _output_dir(client_id) / "contributions.csv"
    if not path.exists():
        return None
    return pd.read_csv(path, parse_dates=["date"])


def get_diagnostics(client_id: str) -> dict | None:
    """Load diagnostics.json. Returns None if no model run exists."""
    path = _output_dir(client_id) / "diagnostics.json"
    if not path.exists():
        return None
    with open(path) as f:
        return json.load(f)


def get_config(client_id: str) -> dict[str, Any]:
    """Return the parsed config dict for a client."""
    configs = _all_configs()
    if client_id not in configs:
        raise KeyError(f"No config found for client_id: {client_id!r}")
    return configs[client_id][0]


def get_config_raw(client_id: str) -> str:
    """Return the raw YAML string for display / editing."""
    configs = _all_configs()
    if client_id not in configs:
        raise KeyError(f"No config found for client_id: {client_id!r}")
    _, path = configs[client_id]
    return path.read_text()


def save_config(client_id: str, yaml_str: str) -> None:
    """Validate YAML syntax and write back to the config file on disk."""
    yaml.safe_load(yaml_str)          # raises yaml.YAMLError on bad syntax
    configs = _all_configs()
    if client_id not in configs:
        raise KeyError(f"No config found for client_id: {client_id!r}")
    _, path = configs[client_id]
    path.write_text(yaml_str)
