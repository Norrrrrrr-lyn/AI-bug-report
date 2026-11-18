"""Run the paper's numerical analyses directly from labeled_reports.jsonl."""

import argparse
import hashlib
import os
from pathlib import Path
import platform
import time

for name in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS"):
    os.environ.setdefault(name, "1")


def main():
    root = Path(__file__).resolve().parent
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=root / "data/labeled_reports.jsonl")
    parser.add_argument("--output", type=Path, default=root / "results")
    parser.add_argument("--only", choices=["descriptive", "comparisons", "materials", "temporal", "regression"])
    parser.add_argument("--bootstrap", type=int, default=5000,
                        help="Use 5000 for paper results; smaller values are only for quick checks")
    args = parser.parse_args()
    if not args.input.is_file():
        parser.error("--input must point to labeled_reports.jsonl")
    if args.bootstrap < 2:
        parser.error("--bootstrap must be at least 2")
    if args.output.resolve() == args.input.resolve().parent or args.input.resolve().parent in args.output.resolve().parents:
        parser.error("Write results outside the input data directory")

    import numpy as np
    import pandas as pd
    import scipy
    import statsmodels
    from analysis.common import load_data, write_json
    from analysis import comparisons, descriptive, materials, regression, temporal

    print("Reading labeled reports", flush=True)
    df, replies, units = load_data(args.input)
    args.output.mkdir(parents=True, exist_ok=True)
    calls = {
        "descriptive": lambda: descriptive.run(df, replies, args.output),
        "comparisons": lambda: comparisons.run(df, args.output, args.bootstrap),
        "materials": lambda: materials.run(units, args.output),
        "temporal": lambda: temporal.run(df, args.output, args.bootstrap),
        "regression": lambda: regression.run(df, args.output),
    }
    elapsed = {}
    for name in ([args.only] if args.only else calls):
        print(name, flush=True)
        start = time.monotonic()
        calls[name]()
        elapsed[name] = round(time.monotonic() - start, 2)
        print(f"  finished in {elapsed[name]} s", flush=True)
    write_json(args.output / "run.json", dict(
        analyses=list(elapsed), bootstrap=args.bootstrap, comparison_seed=20260101,
        temporal_seed=20261106, seconds=elapsed,
        input_sha256=hashlib.sha256(args.input.read_bytes()).hexdigest(),
        versions=dict(python=platform.python_version(), numpy=np.__version__, scipy=scipy.__version__,
                      pandas=pd.__version__, statsmodels=statsmodels.__version__)))


if __name__ == "__main__":
    main()
