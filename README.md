# Copilot or Culprit?

Artifact for **“Copilot or Culprit? How AI Is Changing Open-Source Bug Reporting and Maintenance.”**

This repository contains the labeled dataset, annotation prompts, and analysis code accompanying the paper, provided for anonymous peer review.

## Quick start

Requires **Python 3.12+**. Run the following commands from the repository root:

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt

python run.py
python -m analysis.verify
```

The analysis reads `data/labeled_reports.jsonl` and saves JSON and CSV results to `results/`. The verification command checks selected results against the paper after a full run. No API keys or GPU are needed.

To run a single analysis:

```bash
python run.py --only materials --output results/materials-only
```

Available analyses are `descriptive`, `comparisons`, `regression`, `materials`, and `temporal`. Use `python run.py --help` for input, output, and other options.

## Repository contents

| Path | Description |
| --- | --- |
| [`data/labeled_reports.jsonl`](data/labeled_reports.jsonl) | Report, reply, and material annotations |
| [`data/prompts.py`](data/prompts.py) | Prompts used for bug-report screening and annotation |
| [`analysis/`](analysis/) | Analyses of AI involvement, report reliability, and maintainer practices |
| [`run.py`](run.py) | Entry point for running the analyses |
| [`requirements.txt`](requirements.txt) | Pinned Python dependencies |

## Dataset

The dataset contains **120,918 bug reports from 101 open-source projects**, opened from **January 2024 through September 2026**. Each line of the JSONL file represents one report, with nested annotations for replies and technical materials.

The annotations cover AI roles and tasks, discovery methods, information completeness, maintainer-assessed validity, maintainer activities, and material handling. Observation fields provide timestamps and counts used by the analyses.

Issue links and account identifiers are replaced with local identifiers. Project names and timestamps are retained; discussion text and quoted evidence are omitted. The annotation instructions are available in `data/prompts.py`.

## Results

The analyses cover the paper's three research questions:

- **RQ1:** AI use in bug reporting.
- **RQ2:** Information completeness and technical validity.
- **RQ3:** Maintainer interactions, activities, material handling, and AI use.

Results are saved as JSON and CSV files. `results/run.json` records the input checksum, software versions, random seeds, and execution times. The default settings use 5,000 bootstrap replicates for reproducing the reported comparisons.
