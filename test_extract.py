# Self-check: python test_extract.py
import shutil
import tempfile
from pathlib import Path

import pandas as pd

from extract import extract

TEMP = ["out", "log", "xml", "commands.txt", "densities.csv", "scenario_50.xsd"]


def make_experiment(missing_output):
    folder = Path(tempfile.mkdtemp())
    for name in ["out", "log", "xml"]:
        (folder / name).mkdir()
    (folder / "commands.txt").write_text("cmd\n")
    (folder / "densities.csv").write_text("a\n")
    (folder / "scenario_50.xsd").write_text("<xs:schema/>\n")
    for i in ([1] if missing_output else [1, 2]):
        (folder / "out" / f"{i}.txt").write_text(f"{i}\t0\t0\t1.5\n{i}\t1\t3\t2.5\n")
    return pd.DataFrame(
        {"index": [1, 2], "seed": [1, 2], "outputFile": ["out/1.txt", "out/2.txt"]}
    ), folder


def check(remove_temp_files, missing_output, cleaned):
    scenarios, folder = make_experiment(missing_output)
    try:
        df = extract(scenarios, folder, overwrite=True, remove_temp_files=remove_temp_files)
        assert not df.empty
        assert (folder / "output.parquet").exists()
        for name in TEMP:
            assert (folder / name).exists() != cleaned, f"{name} cleanup wrong"
    finally:
        shutil.rmtree(folder)


check(remove_temp_files=True, missing_output=False, cleaned=True)
check(remove_temp_files=False, missing_output=False, cleaned=False)
check(remove_temp_files=True, missing_output=True, cleaned=False)
print("OK")
