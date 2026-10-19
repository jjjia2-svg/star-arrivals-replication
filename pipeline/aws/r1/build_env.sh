#!/bin/bash
# R1 V3-ENV: build the cached environment layers once on an R1 instance and upload them under r1/env/.
#   build_env.sh --layers py,rmac,rcloud,tex --repo DIR --prefix s3://BUCKET/r1/env/ --out DIR
# Layout = what r1kit's boot restore and versions_check.py expect (rulings R6-R8).
set -euo pipefail
case "${SAR_HOST:-}" in ec2-r1|ec2-r1-test) ;; *) echo "R1 rule: build_env.sh runs only on an R1 instance" >&2; exit 2 ;; esac
LAYERS=""; REPO=""; PREFIX=""; OUT=""
while [ $# -gt 0 ]; do
  case "$1" in --layers) LAYERS="$2"; shift 2;; --repo) REPO="$2"; shift 2;; --prefix) PREFIX="$2"; shift 2;;
               --out) OUT="$2"; shift 2;; *) echo "unknown argument $1" >&2; exit 2;; esac
done
[[ "$PREFIX" =~ ^s3://[a-z0-9][a-z0-9.-]+[a-z0-9]/r1/env/$ ]] || { echo "refusing $PREFIX: writes go only under s3://<bucket>/r1/env/" >&2; exit 2; }
PY=/work/venv/bin/python; TMP=/work/envtmp; mkdir -p "$TMP" "$OUT"; : > "$TMP/built.tsv"
P3M_RMAC="https://p3m.dev/cran/__linux__/noble/2026-08-23"; P3M_RCLOUD="https://p3m.dev/cran/__linux__/noble/2026-09-22"
TLNET="https://ftp.math.utah.edu/pub/tex/historic/systems/texlive/2025/tlnet-final"
export DEBIAN_FRONTEND=noninteractive
RUST_TOOLCHAIN="nightly-2026-02-19"     # pola-rs/r-polars@916aff7 src/rust/rust-toolchain.toml (the renv.lock polars sha)
export RUSTUP_HOME=/opt/rust/rustup CARGO_HOME=/opt/rust/cargo
apt-get install -y -q build-essential curl cmake pkg-config perl \
  $(sed -e 's/#.*//' "$REPO/config/r1/r_runtime_apt.txt") >/dev/null   # the same list the boot restore installs
export RGL_USE_NULL=TRUE                                                  # rgl loads without a display
ver() { awk -F'\t' -v l="$1" -v n="$2" '$1==l && $2==n {print $3}' "$REPO/config/r1/expected_versions.txt"; }
pack() {   # layer path...
  local layer=$1; shift
  tar -C / -czf "$TMP/$layer.tar.gz" "$@"
  local sha; sha=$(sha256sum "$TMP/$layer.tar.gz" | cut -d' ' -f1)
  local key="r1/env/$layer-${sha:0:16}.tar.gz"
  aws s3 cp --only-show-errors "$TMP/$layer.tar.gz" "$PREFIX$layer-${sha:0:16}.tar.gz"
  printf '%s\t%s\t%s\t%s\n' "$layer" "$key" "$sha" "$(stat -c %s "$TMP/$layer.tar.gz")" >> "$TMP/built.tsv"
}
build_py() {
  python3 -m venv /work/venv && /work/venv/bin/pip install -q -r "$REPO/setup/requirements.txt"
  # V3-FINAL.a: PyMuPDF (fitz) for count_words / check_draft_text / red_diff verify; hashed, own expected row
  /work/venv/bin/pip install -q --require-hashes -r "$REPO/config/r1/requirements_final.txt"
  pack py work/venv
}
build_r() {   # layer p3m
  local layer=$1 p3m=$2 v; v=$(ver "$1" R); local lib="/opt/sar-env/rlib-$layer" deb="r-${v}_1_amd64.deb"
  mkdir -p "/opt/sar-env/$layer" "$lib"
  curl -fsSL -o "/opt/sar-env/$layer/$deb" "https://cdn.posit.co/r/ubuntu-2404/pkgs/$deb"
  apt-get install -y -q "/opt/sar-env/$layer/$deb" >/dev/null
  # rustup in its own root (no $HOME/euid mismatch under sudo); polars at the lock's commit pins RUST_TOOLCHAIN in
  # src/rust/rust-toolchain.toml, which the R build does not honour - so set it explicitly (envbuild-03)
  [ -x /opt/rust/cargo/bin/cargo ] || curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y --profile minimal --no-modify-path >/dev/null
  export PATH="/opt/rust/cargo/bin:$PATH"
  rustup toolchain install "$RUST_TOOLCHAIN" --profile minimal >/dev/null
  export RUSTUP_TOOLCHAIN="$RUST_TOOLCHAIN"
  R_PROFILE_USER=/dev/null "/opt/R/$v/bin/Rscript" --no-init-file -e "install.packages('jsonlite', lib='$lib', repos='$p3m')"
  R_PROFILE_USER=/dev/null "/opt/R/$v/bin/Rscript" --no-init-file "$REPO/pipeline/aws/r1/install_stack.R" "$layer" "$lib" "$p3m" "$REPO"
  rustc --version >> "$OUT/rust_version_$layer.txt"; unset RUSTUP_TOOLCHAIN
  pack "$layer" "opt/sar-env/$layer" "opt/sar-env/rlib-$layer"
}
build_tex() {
  mkdir -p "$TMP/tl" && cd "$TMP/tl"
  curl -fsSL -o install-tl-unx.tar.gz "$TLNET/install-tl-unx.tar.gz" && tar -xzf install-tl-unx.tar.gz --strip-components=1
  printf '%s\n' "selected_scheme scheme-basic" "TEXDIR /opt/texlive/2025" "TEXMFLOCAL /opt/texlive/texmf-local" \
    "TEXMFSYSVAR /opt/texlive/2025/texmf-var" "TEXMFSYSCONFIG /opt/texlive/2025/texmf-config" "binary_x86_64-linux 1" \
    "instopt_adjustpath 0" "tlpdbopt_autobackup 0" "tlpdbopt_install_docfiles 0" "tlpdbopt_install_srcfiles 0" > tl.profile
  perl ./install-tl --profile tl.profile --repository "$TLNET"
  /opt/texlive/2025/bin/x86_64-linux/tlmgr --repository "$TLNET" install collection-latexrecommended \
    collection-latexextra collection-fontsrecommended collection-bibtexextra collection-mathscience
  cd /work && pack tex opt/texlive
}
smoke() {   # info only (JP is the gate): fitz imports; one rmac cell vs its gold; the TeX preamble compiles
  echo "smoke_pymupdf $("$PY" -c 'import fitz;print(fitz.VersionBind)' 2>/dev/null || echo MISSING)" >> "$OUT/smoke.txt"
  local res="not run"
  if [ -x "/opt/R/$(ver rmac R)/bin/Rscript" ]; then
    mkdir -p "$TMP/smoke" && ( cd "$TMP/smoke" && SAR_OUT="$TMP/smoke" R_LIBS=/opt/sar-env/rlib-rmac R_PROFILE_USER=/dev/null \
      "/opt/R/$(ver rmac R)/bin/Rscript" "$REPO/analysis/estimation/run_p1.R" P1_fnfix_math_stats "$REPO/data/frames/p1_frame_math_stats.csv" ) \
      && res=$(cd "$REPO" && "$PY" -m analysis.lib.compare_json "$TMP/smoke/P1_fnfix_math_stats.json" analysis/expected/P1_fnfix_math_stats.json >/dev/null && echo EQUAL || echo DIFF)
  fi
  echo "smoke_rmac_P1_fnfix_math_stats $res" >> "$OUT/smoke.txt"
  if [ -d /opt/texlive/2025 ]; then
    { echo '\documentclass[12pt,a4paper]{article}\usepackage[T1]{fontenc}\usepackage[utf8]{inputenc}'
      for s in $(ver tex sty); do case $s in fontenc|inputenc) ;; *) echo "\\usepackage{$s}";; esac; done
      echo '\begin{document}x\end{document}'; } > "$TMP/smoke.tex"
    ( cd "$TMP" && /opt/texlive/2025/bin/x86_64-linux/pdflatex -interaction=nonstopmode smoke.tex >/dev/null ) \
      && echo "smoke_tex OK" >> "$OUT/smoke.txt" || { echo "smoke_tex FAIL" >> "$OUT/smoke.txt"; exit 1; }
  fi
}
IFS=, read -ra L <<< "$LAYERS"
for layer in "${L[@]}"; do
  case "$layer" in py) build_py;; rmac) build_r rmac "$P3M_RMAC";; rcloud) build_r rcloud "$P3M_RCLOUD";;
                   tex) build_tex;; *) echo "unknown layer $layer" >&2; exit 2;; esac
done
smoke
"$PY" - "$TMP/built.tsv" "$OUT" <<'PYEOF'
import json, pathlib, sys
rows = [l.split("\t") for l in pathlib.Path(sys.argv[1]).read_text().splitlines() if l.strip()]
out = pathlib.Path(sys.argv[2])
smoke = dict(l.split(" ", 1) for l in (out / "smoke.txt").read_text().splitlines()) if (out / "smoke.txt").is_file() else {}
pins = {"schema": "sar.r1.env_pins.v1", "layers": {r[0]: {"key": r[1], "sha256": r[2], "bytes": int(r[3])} for r in rows},
        "smoke": smoke}
(out / "summary.json").write_text(json.dumps(pins, indent=1) + "\n")
(out / "RESULT.txt").write_text("OK\n")
PYEOF
"$PY" "$REPO/pipeline/aws/r1/versions_check.py" --expected "$REPO/config/r1/expected_versions.txt" --repo "$REPO" \
  --layers "$LAYERS" --out "$OUT/versions.txt" || { echo "VERSIONS_DRIFT" > "$OUT/RESULT.txt"; exit 1; }
