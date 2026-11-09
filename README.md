# OpenMalaria Workflow

Run large parameter sweeps of [OpenMalaria](https://github.com/openmalaria/openmalaria) simulations with a few lines of code. Outputs are aggregated into a single [Parquet](https://parquet.apache.org/) file that you can easily read and process (example included).

Available in [R](https://github.com/OpenMalaria-Org/workflow-R) and [Python](https://github.com/OpenMalaria-Org/workflow-Python). Same API, same workflow.

## Features

- **Template-based scenarios**: start from one base XML, set any value with an XPath expression. Scalars are fixed; `variable(name)` placeholders can be used for sweeps. Add, remove and modify whole XML snippets for complex interventions (example included).
- **Schema validation**: every generated scenario is validated against the official OpenMalaria XSD before it ever runs — typos fail fast, not after hours of simulation.
- **Flexible design**: full-factorial grids, Latin hypercube sampling, or any table you can build; extra metadata columns travel with each scenario.
- **Scales anywhere**: runs in parallel on your machine, or submits a Slurm job array on a cluster (with `--wait`) — same code, detected automatically.
- **Fast I/O**: monitoring outputs (txt or binary, optionally gzipped) are merged into one compressed Parquet file, ready for `data.table` / `pandas`.
- **Self-cleaning**: temporary XML/output files are removed once every scenario was extracted successfully.

## How it works

```
scenarios table ──write_scenarios()──▶ experiment/xml/{1..N}.xml
                                              │
                                        run() │  (local parallel or Slurm array)
                                              ▼
                                     experiment/out/* ──extract()──▶ output.parquet
```

1. **`create_template`** — a base XML plus XPath → value/`variable()` mappings.
2. **A scenarios table** — one row per scenario, with an `index` column and one column per variable.
3. **`write_scenarios`** — generates and validates N scenario files.
4. **`run`** — executes them (Slurm if available, local cores otherwise).
5. **`extract`** — parses all outputs into one Parquet file.

## Quick start

```r
template <- create_template(
    "snippets/base.xml",
    "demography/@popSize" = 2000,
    "monitoring/surveys/surveyTime" = "2000-01-01",
    "entomology/@scaledAnnualEIR" = variable(eir),
    "model/computationParameters/@iseed" = variable(seed)
)

scenarios <- CJ(eir = c(5, 20), seed = 1:3)   # full-factorial grid
scenarios[, index := .I]

write_scenarios(template, scenarios, "experiment", om)
run(scenarios, "experiment", om)
df <- extract(scenarios, "experiment")
```

The Python workflow is identical, replacing `CJ` with `cj` and using `pandas` instead of `data.table`. See `main.R` / `main.ipynb` for a fully commented example, and `example.plot.R` / `example.plot.ipynb` for turning the results into plots.

## Requirements

- An [OpenMalaria](https://github.com/openmalaria/openmalaria) release (path set in the `om` config)
- R (`data.table`, `xml2`, `nanoparquet`, `lhs`) or Python (`pandas`, `lxml`, `pyarrow`; `scipy` for Latin hypercube sampling)
- Optional: Slurm for cluster runs (adapt `job.sh` to your cluster)
