from concurrent.futures import ThreadPoolExecutor
from math import ceil
from pathlib import Path
import os
import shlex
import shutil
import subprocess
import time

from extract import to_df


def prepare(experiment_folder, om):
    experiment_folder = Path(experiment_folder)
    shutil.copy2(Path(om["path"]) / "densities.csv", experiment_folder)
    shutil.copy2(
        Path(om["path"]) / f'scenario_{om["version"]}.xsd',
        experiment_folder,
    )


def _quote(arg):
    arg = str(arg)
    return subprocess.list2cmdline([arg]) if os.name == "nt" else shlex.quote(arg)


def create_commands(scenarios, experiment_folder, om):
    commands = []
    output_format = om["output_format"].removesuffix(".gz")
    compress_output = om["output_format"].endswith(".gz")

    for _, scenario in scenarios.iterrows():
        index = scenario["index"]
        if isinstance(index, float) and index.is_integer():
            index = int(index)

        outputfile = scenario["outputFile"]
        exe = Path(om["path"]) / ("openMalaria.exe" if os.name == "nt" else "openMalaria")

        args = [
            exe,
            "-s", Path("xml") / f"{index}.xml",
            "--output-format", output_format,
        ]
        if compress_output:
            args.append("--compress-output")
        args += ["--output", outputfile]

        command = " ".join(_quote(arg) for arg in args)
        commands.append(command)

    Path(experiment_folder, "commands.txt").write_text(
        "\n".join(commands) + "\n",
        encoding="utf-8",
    )

    return commands


def run(scenarios, experiment_folder, om, slurm=None, overwrite=False, local_cores=None):
    if om["output_format"] not in {"bin", "bin.gz", "txt", "txt.gz"}:
        raise ValueError(f'Unknown output_format: {om["output_format"]}')

    xml_files = [
        Path(experiment_folder) / "xml" / f"{index}.xml"
        for index in scenarios["index"]
    ]
    if not all(path.exists() for path in xml_files):
        raise FileNotFoundError(
            "Scenario XML files are missing. Run write_scenarios() first."
        )

    folders = [Path(experiment_folder) / "out", Path(experiment_folder) / "log"]
    existing = [folder for folder in folders if folder.exists()]

    if existing and not overwrite:
        raise FileExistsError(
            "Output folders already exist: "
            + ", ".join(map(str, existing))
            + ". Use overwrite=True to replace them."
        )

    if overwrite:
        for folder in existing:
            shutil.rmtree(folder)

    for folder in folders:
        folder.mkdir(parents=True)

    scenarios["outputFile"] = [
        str(Path("out") / f'{index}.{om["output_format"]}')
        for index in scenarios["index"]
    ]
    scenarios.to_csv(Path(experiment_folder) / "scenarios.csv", index=False)

    print("Creating commands...")
    commands = create_commands(scenarios, experiment_folder, om)

    print("Running scenarios...")
    if slurm is None:
        run_local(commands, experiment_folder, om, local_cores)
    else:
        run_slurm(commands, experiment_folder, om, slurm)


def extract(scenarios, experiment_folder, overwrite=False):
    print("Extracting results...")
    output_file = Path(experiment_folder) / "output.csv"

    if output_file.exists() and not overwrite:
        raise FileExistsError(
            f"Output file already exists: {output_file}. Use overwrite=True to replace it."
        )

    if "outputFile" not in scenarios.columns:
        import pandas as pd
        scenarios = pd.read_csv(Path(experiment_folder) / "scenarios.csv")

    start_time = time.time()
    df = to_df(scenarios, experiment_folder)
    print(f"Extract time: {time.time() - start_time:.3f} seconds")

    if df.empty:
        print("Error: extraction failed, output dataframe is empty")
        print("       output.csv not saved")
    else:
        start_time = time.time()
        df.to_csv(output_file, index=False)
        print(f"Write time: {time.time() - start_time:.3f} seconds")

    return df


def run_slurm(commands, experiment_folder, om, slurm):
    prepare(experiment_folder, om)
    n = ceil(len(commands) / slurm["batch_size"])

    script = Path("job.sh").read_text(encoding="utf-8")
    replacements = {
        "N": n,
        "account": slurm["account"],
        "partition": slurm["partition"],
        "jobname": slurm["job_name"],
        "qos": slurm["qos"],
        "time": slurm["time"],
        "MEM_PER_CPU": slurm["mem_per_cpu"],
        "CPUS_PER_TASK": slurm["cpus_per_task"],
        "BATCH_SIZE": slurm["batch_size"],
    }

    for name, value in replacements.items():
        script = script.replace(f"@{name}@", str(value))

    Path(experiment_folder, "start_array_job.sh").write_text(
        script,
        encoding="utf-8",
    )

    print(f"Submitted {n} jobs")

    result = subprocess.run(
        ["sbatch", "--wait", "start_array_job.sh"],
        cwd=experiment_folder,
    )
    if result.returncode != 0:
        raise RuntimeError("Slurm job failed")


def run_local(commands, experiment_folder, om, cores=None):
    prepare(experiment_folder, om)

    n = len(commands)
    if n == 0:
        return
    if cores is None:
        cores = os.cpu_count() or 1
    cores = max(1, min(int(cores), n))
    print(f"Running {n} scenarios locally on {cores} cores")

    def run_one(i):
        command = commands[i - 1]
        logfile = Path(experiment_folder) / "log" / f"job_{i}.log"

        with logfile.open("w", encoding="utf-8") as log:
            result = subprocess.run(
                command,
                cwd=experiment_folder,
                shell=True,
                stdout=log,
                stderr=subprocess.STDOUT,
            )

        if result.returncode != 0:
            return f"Error in task {i}: {command}\n  See log: {logfile}"
        return None

    if cores == 1:
        results = map(run_one, range(1, n + 1))
    else:
        with ThreadPoolExecutor(max_workers=cores) as executor:
            results = executor.map(run_one, range(1, n + 1))

    errors = [error for error in results if error]
    if errors:
        print("\n".join(errors))