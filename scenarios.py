from copy import deepcopy
from itertools import product
from pathlib import Path
import shutil

import pandas as pd
from lxml import etree


XSI_NS = "http://www.w3.org/2001/XMLSchema-instance"
etree.register_namespace("xsi", XSI_NS)


def is_xml(x):
    return isinstance(x, etree._Element)


def xml_new_root(name):
    return etree.Element(name)


def read_xml(path):
    return etree.parse(str(path)).getroot()


def s(scaffold, *replacements):
    """Create an XML-to-scenario mapping.

    Each replacement is an (XPath, value) tuple.

    Fixed value:
        ("demography/@popSize", 1000)

    Scenario variable:
        ("entomology/@scaledAnnualEIR", {"eir": [5, 20]})
    """
    if any(
        not isinstance(r, tuple) or len(r) != 2 or not isinstance(r[0], str) or not r[0]
        for r in replacements
    ):
        raise ValueError(
            'Each replacement must be an (XPath, value) tuple, e.g. '
            '("demography/@popSize", 200)'
        )

    def valid(value):
        if is_xml(value):
            return True
        if isinstance(value, dict):
            return (
                len(value) == 1
                and bool(next(iter(value)))
                and len(next(iter(value.values()))) > 0
            )
        return not isinstance(value, (list, tuple, set))

    if not all(valid(value) for _, value in replacements):
        raise ValueError(
            "Use scalar or XML fixed values, or {'name': values} for varying values"
        )

    return {"scaffold": scaffold, "replacements": list(replacements)}


def mapping_variables(mapping):
    # Match R's duplicated(..., fromLast = TRUE): if several XPaths map to the
    # same scenario column, the last declaration supplies its initial values.
    variables = []
    seen = set()

    for _, value in reversed(mapping["replacements"]):
        if isinstance(value, dict):
            name, values = next(iter(value.items()))
            if name not in seen:
                variables.append((name, list(values)))
                seen.add(name)

    variables.reverse()
    return variables


def create_scenarios(mapping):
    variables = mapping_variables(mapping)

    if not variables:
        return pd.DataFrame({"index": [1]})

    names = [name for name, _ in variables]
    values = [values for _, values in variables]

    # itertools.product varies the last iterable fastest, while R expand.grid()
    # varies the first variable fastest. Reverse twice to preserve R ordering.
    rows = [
        tuple(reversed(combo))
        for combo in product(*reversed(values))
    ]

    scenarios = pd.DataFrame(rows, columns=names)
    scenarios.insert(0, "index", range(1, len(scenarios) + 1))
    return scenarios


def _namespaces(root):
    return {prefix: uri for prefix, uri in root.nsmap.items() if prefix}


def _find_targets(root, path):
    namespaces = _namespaces(root)

    if "/@" in path:
        parent_path, attribute = path.rsplit("/@", 1)
        nodes = root.xpath(parent_path, namespaces=namespaces)
        return "attribute", nodes, attribute

    nodes = root.xpath(path, namespaces=namespaces)
    return "element", nodes, None


def write_scenarios(mapping, scenarios, experiment_folder, om,
                    validate_xml=True, overwrite=False):
    if "index" not in scenarios.columns:
        raise ValueError("scenarios must contain an index column")

    if scenarios["index"].isna().any() or scenarios["index"].duplicated().any():
        raise ValueError("scenario indices must be unique and non-missing")

    variables = mapping_variables(mapping)
    missing = [name for name, _ in variables if name not in scenarios.columns]
    if missing:
        raise ValueError("Missing scenario columns: " + ", ".join(missing))

    schema = None
    if validate_xml:
        schema_path = Path(om["path"]) / f'scenario_{om["version"]}.xsd'
        schema = etree.XMLSchema(etree.parse(str(schema_path)))

    xml_folder = Path(experiment_folder) / "xml"

    if xml_folder.exists() and not overwrite:
        raise FileExistsError(
            f"XML folder already exists: {xml_folder}. Use overwrite=True to replace it."
        )

    if overwrite and xml_folder.exists():
        shutil.rmtree(xml_folder)

    xml_folder.mkdir(parents=True)

    for row in scenarios.index:
        index = scenarios.at[row, "index"]

        doc = etree.parse(str(mapping["scaffold"]))
        root = doc.getroot()

        root.set("schemaVersion", str(om["version"]))
        root.set(
            f"{{{XSI_NS}}}schemaLocation",
            f'http://openmalaria.org/schema/scenario_{om["version"]} '
            f'scenario_{om["version"]}.xsd',
        )

        for path, mapped_value in mapping["replacements"]:
            value = mapped_value

            # {'eir': [...]} means: use scenarios['eir'] for this row.
            if isinstance(value, dict):
                variable = next(iter(value))
                value = scenarios.at[row, variable]

            target_type, nodes, attribute = _find_targets(root, path)
            if not nodes:
                raise ValueError(f"XPath did not match: {path}")

            if is_xml(value):
                if target_type == "attribute":
                    raise ValueError(f"Cannot add XML to an attribute: {path}")

                for node in nodes:
                    node.append(deepcopy(value))

            elif target_type == "attribute":
                for node in nodes:
                    node.set(attribute, str(value))

            else:
                for node in nodes:
                    node.text = str(value)

        if schema is not None and not schema.validate(doc):
            errors = "\n".join(str(error) for error in schema.error_log)
            raise ValueError(f"Invalid scenario {index}:\n{errors}")

        doc.write(
            str(xml_folder / f"{index}.xml"),
            encoding="UTF-8",
            xml_declaration=True,
        )

    print(f"{len(scenarios)} scenarios created")
