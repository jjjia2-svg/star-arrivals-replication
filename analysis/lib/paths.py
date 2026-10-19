"""Single source of truth for locations. Usage: from analysis.lib.paths import load_paths

`$SAR_PATHS_CONFIG` names an alternative `paths.yaml`. It exists so that "run this package the way a
replicator would" is an operation rather than a file edit: the M3 Task 8 review found the pipeline
layer's default run documented as self-contained when 14 of its 15 stages need a read-only legacy
tree, and the test that was supposed to prevent that checked a declaration against itself. The
honest replacement runs the real stages with the legacy roots pointed somewhere empty, and doing
that by rewriting a tracked file from inside a test is worse than giving the reader a switch.
`analysis/lib/paths.R` honours the same variable, so the two halves cannot drift.

Values may be written as `${VAR:-default}`: `$VAR` when it is set and non-empty, otherwise
`default`. That is how the roots this package does not ship (the author's private trees and the
OpenAlex extraction) are pointed somewhere on a given machine without editing a tracked file.
"""
import os
import re
from pathlib import Path
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]

#: env var naming an alternative config file. Absolute, and it must exist - a typo here would
#: otherwise fall back to the real config and silently measure the wrong thing.
CONFIG_ENV = "SAR_PATHS_CONFIG"


def config_file() -> Path:
    """The `paths.yaml` in force: `$SAR_PATHS_CONFIG` if set, else `config/paths.yaml`."""
    override = os.environ.get(CONFIG_ENV, "").strip()
    if not override:
        return REPO_ROOT / "config" / "paths.yaml"
    cfg = Path(override).expanduser()
    if not cfg.is_absolute():
        raise ValueError(f"${CONFIG_ENV} must be an absolute path, got {override!r}")
    if not cfg.is_file():
        raise FileNotFoundError(f"${CONFIG_ENV} names a file that does not exist: {cfg}")
    return cfg


#: `${VAR:-default}` - the only interpolation form paths.yaml uses
_ENV_DEFAULT = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*):-([^}]*)\}")


def expand(value: str) -> str:
    """`${VAR:-default}` -> `$VAR` if set and non-empty, else `default`. Other text is unchanged."""
    return _ENV_DEFAULT.sub(lambda m: os.environ.get(m.group(1), "").strip() or m.group(2), value)


def load_paths(config_file_path: Path | None = None) -> dict:
    cfg = config_file_path or config_file()
    raw = yaml.safe_load(cfg.read_text())
    out = {}
    for k, v in raw.items():
        p = Path(expand(str(v))).expanduser()
        out[k] = p if p.is_absolute() else (REPO_ROOT / p).resolve()
    out["repo_root"] = REPO_ROOT
    return out
