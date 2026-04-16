---
name: refactor
description: Extracts notebook cells into src/ modules following the project conventions in CLAUDE.md. Invoke when asked to refactor a modeling notebook into library code, move logic from a notebook cell into an existing src/ file, or populate a src/ placeholder module. Always reads the notebook in full before writing anything.
---

You are refactoring Jupyter notebook cells into Python library modules for a Bayesian Marketing Mix Modeling workbench built on Google's Meridian. Your job is to extract logic cleanly, follow the conventions established in this codebase, and never change the notebook.

## What you are doing

Notebooks are where modeling decisions get made. `src/` is where stable, reusable logic lives once the decisions are settled. Your job is to translate notebook cells into callable Python functions — config-driven, validated, well-structured — without adding features, abstractions, or opinions beyond what the notebook already expresses.

## Step 1 — Read everything before writing anything

Before producing a single line of code:

1. Read the full target notebook (it is JSON; parse `cell['source']` for each cell)
2. Read the target `src/` file if it already has content
3. Read `configs/{client_id}.yaml` if one exists for the notebook's client
4. Read `src/data_prep.py` as the canonical style reference

Do not skim. Cells you skip become bugs.

## Step 2 — Categorize every code cell

Walk the notebook cell by cell and assign each to one of these buckets:

| Bucket | What it contains | Goes where |
|---|---|---|
| **data_prep** | Load CSV, date filter, Monday alignment, perfect-index gap-fill, Black Friday indicator, float32 casting, validation | `src/data_prep.py` |
| **model_config** | Prior distributions, `DataFrameInputDataBuilder`, `ModelSpec`, `Meridian` constructor | `src/model_config.py` |
| **utils** | Helpers used by more than one module (e.g. `load_config`, date math) | `src/utils.py` |
| **run** | `mmm.sample_prior(...)`, `mmm.sample_posterior(...)` — execution, not library code | Skip — belongs in the notebook |
| **analysis** | `Analyzer`, `Summarizer`, `Visualizer`, `BudgetOptimizer` — post-fit analysis | Skip — future `src/analysis.py`, not in scope |
| **imports** | `import ...` statements | Consolidate at the top of the target module |
| **commented-out alternative** | Cells that are entirely commented out (alternative approaches) | Drop — the chosen approach is the one that's uncommented |
| **markdown / display** | Markdown cells, `df.head()`, `print(...)` standalone, `IPython.display` | Drop |

If a cell spans two buckets (e.g., builds the prior AND constructs the model), split it at the natural boundary.

## Step 3 — Apply the transformation rules

### 3a. Replace hardcoded values with config lookups

Everything that was hardcoded in the notebook must come from the config dict:

| Notebook hardcode | Config replacement |
|---|---|
| `pd.read_csv("/absolute/path/to/file.csv")` | `pd.read_csv(config["data_path"])` |
| `start_date = pd.to_datetime("2024-03-01")` | `pd.to_datetime(config["start_date"])` (optional key) |
| `channels = ["Brand", "Non_Brand", ...]` | `config["channels"]` |
| `kpi_col = "Revenue"` | `config["kpi_column"]` |
| `knots=26` | `config.get("knots", 26)` — keep the default equal to what the notebook used |
| `n_chains=1, n_adapt=200, ...` | `config["mcmc"]["dev"]` / `config["mcmc"]["prod"]` |
| ROI ranges dict | `config["prior_roi_ranges"]` |
| `target_contribution = 0.60` | `config["target_contribution"]` |

**Never** replace a hardcoded value with something that wasn't in the config file. If the config doesn't have a field, add it with the notebook's value as the default in `config.get("key", notebook_value)`.

### 3b. Function signature convention

Every public function accepts `config: dict[str, Any]` as its primary argument. Do not add extra parameters unless the notebook already used them as variables.

```python
# Right
def build_input_data(df: pd.DataFrame, config: dict[str, Any]) -> InputData:

# Wrong — introduces a parameter the notebook didn't have
def build_input_data(df: pd.DataFrame, config: dict[str, Any], scale_media: bool = True) -> InputData:
```

### 3c. What goes in `utils.py`

`utils.py` holds helpers that are either:
- Used by more than one `src/` module, OR
- Pure utility functions with no Meridian dependency (date math, config loading)

`load_config` lives in `utils.py` (not in `data_prep.py` or `model_config.py`). If `src/data_prep.py` already defines `load_config`, move it to `utils.py` and import it from there.

### 3d. Commented-out cells

If a cell is entirely commented out in the notebook (alternative prior strategy, commented-out holdout setup, etc.), drop it from the module. The uncommented code is the settled decision. Do not carry forward alternatives as comments — they live in git history and the notebook.

Exception: if there is a single commented-out line that is a deliberate future hook (e.g. `# roi_calibration_period = ...`), preserve it as a comment in the function body with its original context.

### 3e. Cells that are partially commented

If a cell has some active lines and some commented-out lines, extract only the active lines. Drop the commented-out lines unless they are the exception above.

## Step 4 — Write the module

### File header

```python
"""
src/{module_name}.py
~~~~~~~~~~~~~~~~~~~~
<One sentence describing what this module does in the context of the pipeline.>

Public API
----------
function_one(args)  → ReturnType
function_two(args)  → ReturnType
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

# stdlib imports here (alphabetical)

# third-party imports here (alphabetical)
import numpy as np
import pandas as pd
import yaml
```

### Section dividers

Use this exact style — a `# ──` prefix, the section name, and a trailing line of `─` characters to column 80:

```python
# ── Public API ────────────────────────────────────────────────────────────────

# ── Internal helpers ──────────────────────────────────────────────────────────

# ── Test call ─────────────────────────────────────────────────────────────────
```

### Docstrings

Public functions get a full numpydoc-style docstring:
- One-line summary
- `Steps` section (numbered list of what the function does, matching the notebook's cell sequence)
- `Parameters` section
- `Returns` section
- `Raises` section (only if the function raises)

```python
def prepare_data(config: dict[str, Any]) -> pd.DataFrame:
    """
    Load, align, engineer features, and validate a weekly MMM DataFrame.

    Steps
    -----
    1. Load CSV from ``config['data_path']``
    2. ...

    Parameters
    ----------
    config : dict
        Loaded from ``configs/{client_id}.yaml``.
        Required keys: ...
        Optional keys: ...

    Returns
    -------
    pd.DataFrame
        ...

    Raises
    ------
    ValueError
        If ...
    """
```

Private helpers (`_` prefix) get a one-liner only:

```python
def _black_friday_week_starts(years) -> set[pd.Timestamp]:
    """Return the Monday of Black Friday week for each year in *years*."""
```

### Inline comments

Only add inline comments where the logic is non-obvious or where it explains a deliberate choice from the notebook. Copy the notebook's original comments where they are useful. Do not add comments restating what the code obviously does.

```python
# Right — explains a non-obvious correctness requirement
# Population is a per-geo constant, so propagate it within each geo
# BEFORE zeroing everything else — otherwise new rows would inherit 0.

# Wrong — restates the obvious
# Cast KPI to float32
df[kpi_col] = df[kpi_col].astype(np.float32)
```

### Step numbering in function bodies

Use the same step-numbered comment style as `data_prep.py`:

```python
# ── 1. Load ────────────────────────────────────────────────────────────────
# ── 2. Date filter (optional) ──────────────────────────────────────────────
# ── 3. Monday alignment ────────────────────────────────────────────────────
```

## Step 5 — Test call

Every module gets a `if __name__ == "__main__":` block at the bottom. It must:

1. Load the client config from the relevant `configs/` file
2. Call each public function in pipeline order
3. Print enough output to verify correctness without being noisy — shape, date range, key column names, a spot-check of any derived column (e.g. `black_friday` count, zero-population check)
4. Exit cleanly (`sys.exit(0)`)

The test call should be runnable from the repo root: `python src/{module}.py`

## Module responsibility map

### `src/data_prep.py`

```
load_config(path) → dict                    # if not yet in utils.py
prepare_data(config) → pd.DataFrame
  ├─ load CSV
  ├─ date filter
  ├─ Monday alignment
  ├─ perfect (date × geo) index + gap-fill
  ├─ geo dropping
  ├─ black_friday indicator
  ├─ float32 casting
  └─ _validate(df, config)
_black_friday_week_starts(years) → set
_validate(df, config) → None
```

### `src/model_config.py`

```
build_input_data(df, config) → InputData
  └─ DataFrameInputDataBuilder chain:
       .with_kpi()
       .with_media()
       .with_organic_media()    # only if organic_channels non-empty
       .with_controls()
       .with_population()
       .build()

build_prior(config) → PriorDistribution
  ├─ roi mode:          lognormal_dist_from_range per channel → PriorDistribution(roi_m=...)
  └─ contribution mode: Beta(a, b) per channel   → PriorDistribution(contribution_m=...)

build_model_spec(config, prior) → ModelSpec

build_model(input_data, model_spec) → Meridian
```

### `src/utils.py`

```
load_config(path) → dict
```

(Add other shared helpers here as they emerge — do not pre-create empty stubs.)

## What NOT to do

- **Do not change the notebook.** Not a single cell, not the filename.
- **Do not add features** the notebook doesn't have (extra validation, additional logging, new config keys the notebook never used).
- **Do not create abstractions for single-use code.** Three similar lines in a function body are fine. Only extract a helper if it will be called from more than one place.
- **Do not add docstrings or type annotations to code you did not write** (i.e. code you found already written in the src/ file you are editing).
- **Do not add error handling for things that cannot go wrong** (e.g. don't validate that `config["channels"]` is a list — trust the YAML loader).
- **Do not add compatibility shims, feature flags, or "future extensibility."** Write for the notebook that exists, not a hypothetical future notebook.
- **Do not split a single logical step across multiple functions** just to make functions smaller. If the notebook does gap-filling and float32 casting in the same conceptual block, keep them in the same function.
- **Do not create `__init__.py` or package structure** unless asked. `src/` is a flat directory of modules.
- **Do not rename notebook variables** when extracting them unless the name is a Python reserved word or conflicts with a function argument.

## Prior mode reference

The notebooks use two prior modes. Know which one the target notebook uses before writing `build_prior`.

**ROI mode** (`prior_type: roi` in config):
```python
# Config stores (low, high) 95% CI ranges per channel
# e.g. prior_roi_ranges: {Brand: [1.3, 10.6], ...}
roi_dists = [
    prior_distribution.lognormal_dist_from_range(
        low=config["prior_roi_ranges"][ch][0],
        high=config["prior_roi_ranges"][ch][1],
        mass_percent=config.get("prior_roi_mass_percent", 0.95),
    )
    for ch in config["channels"]
]
roi_loc   = tf.cast([d.loc   for d in roi_dists], tf.float32)
roi_scale = tf.cast([d.scale for d in roi_dists], tf.float32)
return prior_distribution.PriorDistribution(
    roi_m=tfd.LogNormal(loc=roi_loc, scale=roi_scale)
)
```

**Contribution mode** (`prior_type: contribution` in config):
```python
# Config stores target_contribution and prior_concentration
n = len(config["channels"])
per_ch = config["target_contribution"] / n
c      = config["prior_concentration"]
a, b   = per_ch * c, (1.0 - per_ch) * c
return prior_distribution.PriorDistribution(
    contribution_m=tfd.Beta(
        concentration1=tf.cast([a] * n, tf.float32),
        concentration0=tf.cast([b] * n, tf.float32),
    )
)
```

## Organic channels in `build_input_data`

Only call `.with_organic_media()` if `config.get("organic_channels", [])` is non-empty. The organic column convention is `{channel}_Views`.

```python
organic_chs = config.get("organic_channels", [])
if organic_chs:
    builder = builder.with_organic_media(
        df,
        organic_media_cols=[f"{ch}_Views" for ch in organic_chs],
        organic_media_channels=organic_chs,
        media_time_col=config["date_column"],
        geo_col=config["geo_column"],
    )
```

## Style reference: `src/data_prep.py`

When in doubt about any convention — section dividers, docstring format, comment style, test call structure, how to handle config keys — read `src/data_prep.py`. It is the canonical example. Match it exactly.
