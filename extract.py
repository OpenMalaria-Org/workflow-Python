from pathlib import Path
import gzip
import struct
import time

import numpy as np
import pandas as pd


def _read_exact(con, n, path):
    data = con.read(n)
    if len(data) != n:
        raise ValueError(f"Truncated binary output: {path}")
    return data


def read_monitoring_binary(path):
    path = Path(path)
    open_file = gzip.open if path.name.endswith(".gz") else open

    with open_file(path, "rb") as con:
        header = _read_exact(con, 28, path)

        magic = header[:8]
        version, integer_rows, double_rows = struct.unpack("<IQQ", header[8:])

        if magic != b"OMOUTBIN" or version != 2:
            raise ValueError(f"Unsupported OpenMalaria binary format: {path}")

        rows = integer_rows + double_rows

        survey = np.frombuffer(_read_exact(con, 4 * rows, path), dtype="<i4").copy()
        age_group = np.frombuffer(_read_exact(con, 4 * rows, path), dtype="<i4").copy()
        measure = np.frombuffer(_read_exact(con, 4 * rows, path), dtype="<i4").copy()

        integer_values = np.frombuffer(
            _read_exact(con, 4 * integer_rows, path), dtype="<i4"
        ).copy()
        double_values = np.frombuffer(
            _read_exact(con, 8 * double_rows, path), dtype="<f8"
        ).copy()

        if con.read(1):
            raise ValueError(f"Invalid binary output size: {path}")

    value = np.concatenate((integer_values.astype(float), double_values))

    return pd.DataFrame({
        "survey": survey,
        "ageGroup": age_group,
        "measure": measure,
        "value": value,
    })


def read_monitoring_output(path):
    path = Path(path)

    if path.name.endswith(".bin") or path.name.endswith(".bin.gz"):
        return read_monitoring_binary(path)

    return pd.read_csv(
        path,
        sep="\t",
        header=None,
        names=["survey", "ageGroup", "measure", "value"],
        compression="infer",
    )


def to_df(scenarios, experiment_folder):
    info_count = 0
    max_info_count = 100
    n = len(scenarios)
    data = []

    for _, scenario in scenarios.iterrows():
        index = scenario["index"]
        if isinstance(index, float) and index.is_integer():
            index = int(index)

        if "outputFile" in scenarios.columns:
            f = Path(experiment_folder) / scenario["outputFile"]
        else:
            f = Path(experiment_folder) / "txt" / f"{index}.txt"

        if not f.exists():
            if info_count < max_info_count:
                print(f"Warning: File {f} is missing")
                if info_count == max_info_count - 1:
                    print("Further missing files will not be shown")
            info_count += 1
        else:
            d = read_monitoring_output(f)
            d["index"] = index
            data.append(d)

    if data:
        result = pd.concat(data, ignore_index=True)
    else:
        result = pd.DataFrame(columns=["survey", "ageGroup", "measure", "value", "index"])

    if info_count > 0:
        print(f"Warning: {info_count}/{n} files are missing")

    if result.empty:
        print("Error: Dataframe is empty because no outputs were found")
        print("       Check the log files and make sure OpenMalaria is able to run")

    return result


def extract(scenarios, experiment_folder, overwrite=False):
    print("Extracting results...")
    output_file = Path(experiment_folder) / "output.pkl"

    if output_file.exists() and not overwrite:
        raise FileExistsError(
            f"Output file already exists: {output_file}. Use overwrite=True to replace it."
        )

    if "outputFile" not in scenarios.columns:
        scenarios = pd.read_csv(Path(experiment_folder) / "scenarios.csv")

    start_time = time.time()
    df = to_df(scenarios, experiment_folder)
    print(f"Extract time: {time.time() - start_time:.3f} seconds")

    if df.empty:
        print("Error: extraction failed, output dataframe is empty")
        print(f"       {output_file} not saved")
    else:
        start_time = time.time()
        df.to_pickle(output_file)
        print(f"Write time: {time.time() - start_time:.3f} seconds")

    return df
