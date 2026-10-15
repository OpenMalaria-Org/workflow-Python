from pathlib import Path
import shutil

import matplotlib.pyplot as plt
import pandas as pd

from scenarios import cj, create_template, read_xml, variable, write_scenarios, xml_new_root
from run import run
from extract import extract

# IMPORTANT: If using Slurm, check and adapt job.sh to your system
slurm = {
    "account": "chitnis",
    "partition": "scicore",
    "job_name": "OpenMalaria",
    "qos": "30min",
    "time": "00:30:00",
    "mem_per_cpu": "1G",
    "cpus_per_task": 16,
    "batch_size": 16,
    # number of job in array = N / batch_size
    # if batch_size = cpus_per_task then one OM instance = one CPU = faster
    # if batch_size > cpus_per_task then multiple OM instances per cpus = slower but less Slurm jobs
    # just leave it 16 / 16, 32 / 32, 64 / 64
}

if shutil.which("sbatch") is None: slurm = None  # slurm = None if not available, e.g. running on a laptop

om = {
    "version": 50,
    "path": str(Path("../fork/openMalaria-50.0").resolve()),
    "output_format": "bin.gz",  # "bin", "bin.gz", "txt", or "txt.gz"
}

experiment_folder = "experiment"

# Creation of the XML template
# ############################
#
# The template defines how each scenario XML is created:
# - the first argument is the base XML file to use
# - XPath expressions are used to select where values are written
# - scalars or strings are fixed across all scenarios
# - XML nodes can be inserted for more flexibility
# - variable("name") are placeholders and will be replaced during scenario generation
# The same variable can be referenced by multiple XPaths.
template = create_template(
    # Base XML specification
    "snippets/base.xml",

    # Fixed parameters
    ("demography/@popSize", 1000),
    ("monitoring/@startDate", "1950-01-01"),  # 50 years burnin (start date - 50 years)
    ("monitoring/surveys/surveyTime", "2000-01-01"),  # start date
    ("monitoring/surveys/surveyTime/@repeatStep", "5d"),  # survey every 5d (1y is also common)
    ("monitoring/surveys/surveyTime/@repeatEnd", "2020-01-01"),  # end date

    # Using snippets for more flexibility
    ("interventions/@name", "GVI example"),
    ("interventions", xml_new_root("human")),
    ("interventions/human", read_xml("snippets/GVI.component.xml")),
    ("interventions/human", read_xml("snippets/GVI.deployment.xml")),
    ("interventions/human/deployment[@name='GVI_example']/timed/deploy/@coverage", 0.7),

    # Placeholder variables
    ("entomology/@scaledAnnualEIR", variable("eir")),
    ("healthSystem/DecisionTree5Day/pSeekOfficialCareUncomplicated1/@value", variable("access")),
    ("healthSystem/DecisionTree5Day/pSeekOfficialCareUncomplicated2/@value", variable("access")),
    ("model/computationParameters/@iseed", variable("seed")),
)

# Creation of the scenarios table
# ###############################
#
# The table contains one row per scenario and:
# - it must contain an index column
# - it must reference all previously declared variable names
# Additional columns are allowed.

# Example 1: full-factorial expansion using the Cross-Join (CJ) product:
scenarios = cj(
    eir=[5, 20],
    access=0.04,
    seed=range(1, 4),
)
scenarios.insert(0, "index", range(1, len(scenarios) + 1))

# Example 2: Latin hypercube sampling: (pip install scipy)
# from scipy.stats.qmc import LatinHypercube
# n = 6
# x = LatinHypercube(d=2).random(n)
#
# scenarios = pd.DataFrame({
#     "eir": 5 + x[:, 0] * (20 - 5),          # qunif(x, 5, 20)
#     "access": 0.02 + x[:, 1] * (0.20 - 0.02),  # qunif(x, 0.02, 0.20)
#     "seed": range(1, n + 1),
# })
# scenarios.insert(0, "index", range(1, len(scenarios) + 1))

write_scenarios(template, scenarios, experiment_folder, om, validate_xml=True, overwrite=False)
run(scenarios, experiment_folder, om, slurm, overwrite=False)
df = extract(scenarios, experiment_folder, overwrite=False)

# The workflow ends here.

# Example plotting
# ##################

# Load saved results if starting from an existing experiment folder
scenarios = pd.read_csv(Path(experiment_folder) / "scenarios.csv")
df = pd.read_pickle(Path(experiment_folder) / "output.pkl")

d = df.dropna().copy()  # remove NA values
d = d[d["survey"] != 1]  # remove first survey (due to accumulating data during the burn-in period)
d = d.groupby(["index", "measure", "survey"], as_index=False)["value"].sum()  # aggregate age-groups

# merge with the scenarios table to have all the metadata (eir, access, seed, etc.) in the same dataframe
d = d.merge(scenarios, on="index")
d = d.sort_values(["eir", "seed", "survey", "measure"])

nPatent = d[d["measure"] == 3].copy()
nUncomp = d[d["measure"] == 14].copy()
nHost = d[d["measure"] == 0].copy()
inputEIR = d[d["measure"] == 35].copy()
simulatedEIR = d[d["measure"] == 36].copy()

# align by scenario/survey rather than relying on row order
keys = ["index", "survey"]
host = nHost[keys + ["value"]].rename(columns={"value": "host"})

prevalence = nPatent.merge(host, on=keys)
prevalence["value"] = prevalence["value"] / prevalence["host"]

incidence = nUncomp.merge(host, on=keys)
incidence["value"] = incidence["value"] / incidence["host"]

eir = pd.concat([
    inputEIR.assign(type="input"),
    simulatedEIR.assign(type="simulated"),
])

fig, axes = plt.subplots(3, 1, figsize=(9, 12))

for eir_value, group in prevalence.groupby("eir"):
    mean = group.groupby("survey", as_index=False)["value"].mean()  # stat_summary(fun = mean)
    axes[0].plot(mean["survey"], mean["value"], label=str(eir_value))
axes[0].set(xlabel="Survey", ylabel="Prevalence")
axes[0].legend(title="EIR")

for eir_value, group in incidence.groupby("eir"):
    mean = group.groupby("survey", as_index=False)["value"].mean()
    axes[1].plot(mean["survey"], mean["value"], label=str(eir_value))
axes[1].set(xlabel="Survey", ylabel="Clinical Incidence")
axes[1].legend(title="EIR")

for (eir_value, kind), group in eir.groupby(["eir", "type"]):
    mean = group.groupby("survey", as_index=False)["value"].mean()
    axes[2].plot(
        mean["survey"], mean["value"],
        linestyle="--" if kind == "input" else "-",
        label=f"{eir_value} ({kind})",
    )
axes[2].set(xlabel="Survey", ylabel="EIR")
axes[2].legend(title="EIR")

plt.tight_layout()
plt.show()
