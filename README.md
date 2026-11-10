# OpenMalaria Workflow

Create, run, and analyse large sets of [OpenMalaria](https://github.com/OpenMalaria-Org/openmalaria) simulations without editing individual XML files or collecting outputs by hand. Define your experiment in Python, run it locally or on a Slurm cluster, and collect the results in [Parquet](https://parquet.apache.org/) files for analysis.

The workflow is available in [Python](https://github.com/OpenMalaria-Org/workflow-Python) and [R](https://github.com/OpenMalaria-Org/workflow-R), using the same overall approach.

## How it works

A workflow experiment is defined by **two inputs**:

- **A template**: a base OpenMalaria XML scenario, with XPath expressions identifying values to replace. Replacements can be fixed values or variables read from the scenarios table. The template can also add XML snippets, for example to configure interventions.
- **A scenarios table**: one row per simulation, with a unique `index`, the values of the template variables, and optionally other metadata to keep with the results.

The workflow generates an XML file for each row, runs OpenMalaria, and combines the outputs into a dataset that can be linked back to the input parameters:

```text
  Base XML + template                 Scenarios table
       (XPath rules)                 (one row per run)
               \                       /
                \                     /
                  write_scenarios()
                 (generate + validate)
                          |
                  xml/<index>.xml
                          |
                        run()
                 (local or Slurm)
                    /           \
          Raw model outputs    scenarios.parquet
                    |           (input parameters)
                 extract()           |
                    |                |
              output.parquet         |
               (model results)       |
                    \                /
                      Join on index
                           |
                        Analysis
```

The following example walks through these steps using Python. A complete runnable example is also provided in [`main.ipynb`](main.ipynb).

### 1. Configure OpenMalaria and the workflow

Start in the repository directory, load the workflow functions, and point to an OpenMalaria release:

```python
import pandas as pd

from scenarios import cj, create_template, variable, write_scenarios
from run import run
from extract import extract

om = {
    "version": 49,
    "path": "/absolute/path/to/openmalaria-release",
    "output_format": "txt",
}

experiment_folder = "experiment"
```

The directory in `om["path"]` should contain the `openMalaria` executable, the matching `scenario_49.xsd` schema, and `densities.csv`.

### 2. Define the XML template

Create a template from a base XML scenario. In this example, the population size is **fixed** across all runs, while the entomological inoculation rate (`eir`) and random seed (`seed`) are **variables**:

```python
template = create_template(
    "snippets/base.xml",
    ("demography/@popSize", 2000),
    ("entomology/@scaledAnnualEIR", variable("eir")),
    ("model/computationParameters/@iseed", variable("seed")),
)
```

The first element of each pair is an XPath expression that locates the attribute to modify. Each `variable("name")` refers to a column in the scenarios table created below.

### 3. Choose the simulations to run

Create a scenarios table with two EIR values and three random seeds, giving **six simulations**:

```python
scenarios = cj(eir=[5, 20], seed=range(1, 4))
scenarios.insert(0, "index", range(1, len(scenarios) + 1))
```

| index | eir | seed |
|------:|----:|-----:|
| 1 | 5  | 1 |
| 2 | 5  | 2 |
| 3 | 5  | 3 |
| 4 | 20 | 1 |
| 5 | 20 | 2 |
| 6 | 20 | 3 |

Each row defines one simulation. The `index` identifies the simulation throughout the workflow and links its results back to its input parameters. The table can be generated with a factorial grid, Latin hypercube sampling, or any custom design; it can also contain extra columns for later analysis.

### 4. Generate and validate the XML scenarios

```python
write_scenarios(template, scenarios, experiment_folder, om)
```

For each row, `write_scenarios()` starts from the base XML, applies the fixed and variable replacements, and validates the resulting scenario against the OpenMalaria XSD. It writes one file per simulation to `experiment/xml/<index>.xml`.

### 5. Run the simulations

```python
run(scenarios, experiment_folder, om)
```

By default, `run()` executes the scenarios locally. It can also submit a Slurm job array (see [Running on a Slurm cluster](#running-on-a-slurm-cluster)). The workflow records the scenario parameters and expected output filenames in `experiment/scenarios.parquet` and writes the raw model outputs to the experiment directory.

### 6. Extract and analyse the results

```python
extract(scenarios, experiment_folder)

results = pd.read_parquet("experiment/output.parquet")
parameters = pd.read_parquet("experiment/scenarios.parquet")

results = results.merge(parameters, on="index")
```

`extract()` reads the monitoring outputs (text or binary, optionally gzipped) and combines them into `experiment/output.parquet`. **One simulation generally produces multiple result rows**, for example across surveys, age groups and measures. Each result row retains the simulation's `index`, so the join adds its input parameters (`eir`, `seed`, etc.) to the model results (`survey`, `ageGroup`, `measure`, `value`).

Once **all** scenario outputs have been successfully extracted, temporary XML files, raw outputs and logs are removed by default. If some outputs are missing, available results are still extracted but temporary files are retained for inspection. The two Parquet files remain available for analysis. See [`example.plot.ipynb`](example.plot.ipynb) for a plotting example.

## Running on a Slurm cluster

To use Slurm, define a `slurm` configuration and pass it to `run()`:

```python
run(scenarios, experiment_folder, om, slurm)
```

See [`main.ipynb`](main.ipynb) for a complete configuration example. Adapt [`job.sh`](job.sh) to your cluster's modules, dependencies and GNU Parallel setup. Slurm jobs are submitted as an array, and the workflow waits for the array to finish before continuing to extraction.

In the provided `main.ipynb`, Slurm is selected when `sbatch` is available; otherwise, it uses local execution. When calling `run()` directly, local execution is the default unless you explicitly pass a `slurm` configuration.

## Features

- **Flexible experiment design:** use factorial grids, Latin hypercube sampling, or any table of parameter combinations.
- **Template-based XML generation:** change values through XPath expressions, reuse variables across multiple XML fields, and insert XML snippets for complex scenarios.
- **Schema validation:** check each generated scenario against the OpenMalaria XSD before simulation.
- **Local and cluster execution:** run multiple simulations on local CPU cores or through a Slurm job array.
- **Efficient outputs:** combine text or binary monitoring outputs, compressed or uncompressed, into Parquet files.
- **Built-in cleanup:** keep the processed results and scenario metadata; remove intermediate files only when extraction is complete.

## Requirements

- An [OpenMalaria release](https://github.com/OpenMalaria-Org/openmalaria), including its executable and matching scenario XSD.
- Python packages: `pandas`, `lxml`, and `pyarrow`; `scipy` for Latin hypercube sampling. See [`requirements.txt`](requirements.txt) and [`main.ipynb`](main.ipynb) for the repository's setup.
- Optional: Slurm and GNU Parallel for cluster execution (with a cluster-specific [`job.sh`](job.sh)).

For the equivalent R workflow, see [workflow-R](https://github.com/OpenMalaria-Org/workflow-R).
