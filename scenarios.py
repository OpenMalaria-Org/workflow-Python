from copy import deepcopy
from itertools import product
from pathlib import Path
import re
import shutil

import numpy as np
import pandas as pd
from lxml import etree


XSI_NS = "http://www.w3.org/2001/XMLSchema-instance"
etree.register_namespace("xsi", XSI_NS)


def is_xml(x):
    return isinstance(x, etree._Element)


def xml_new_root(name):
    return etree.Element(name)


def read_xml(path):
    parser = etree.XMLParser(remove_blank_text=True)
    return etree.parse(str(path), parser).getroot()


class ScenarioVariable:
    """A scenario-column placeholder created with variable()."""

    def __init__(self, name):
        self.name = name

    def __str__(self):
        return self.name


def variable(name):
    if not isinstance(name, str) or not name:
        raise ValueError("variable() must contain a column name")
    return ScenarioVariable(name)


def is_variable(x):
    return isinstance(x, ScenarioVariable)


def create_template(scaffold, *replacements):
    """Create an XML template used to generate each scenario XML.

    Each replacement is an (XPath, value) tuple:

    Fixed scalar:
        ("demography/@popSize", 200)
    XML node (snippets offer more flexibility):
        ("interventions/human", read_xml("snippets/GVI.component.xml"))
    Placeholder variable:
        ("entomology/@scaledAnnualEIR", variable("eir"))

    The same variable can be referenced by multiple XPaths, and multiple
    nodes can be inserted at the same XPath.
    """
    if any(
        not isinstance(r, tuple) or len(r) != 2 or not isinstance(r[0], str) or not r[0]
        for r in replacements
    ):
        raise ValueError(
            'Name each replacement with its XPath, e.g. '
            '("demography/@popSize", 200)'
        )

    def valid(x):
        return (
            is_xml(x)
            or is_variable(x)
            or not isinstance(x, (list, tuple, set, dict))
        )

    if not all(valid(value) for _, value in replacements):
        raise ValueError(
            "Use scalar or XML fixed values, or variable(name) for scenario variables"
        )

    return {"scaffold": scaffold, "replacements": list(replacements)}


def template_variables(template):
    # unique(): keep variables in order of first appearance
    return list(dict.fromkeys(
        str(value)
        for _, value in template["replacements"]
        if is_variable(value)
    ))


def cj(**columns):
    """Cross-join (full-factorial) expansion, like data.table::CJ().

    Each column is sorted, deduplicated and expanded into every combination
    of values; scalars are recycled. The last column varies fastest,
    matching R's CJ() ordering.
    """
    names = list(columns)
    values = []

    for name in names:
        value = columns[name]
        if np.isscalar(value) or isinstance(value, (str, bytes)):
            value = [value]
        values.append(sorted(set(value)))

    # itertools.product varies the last iterable fastest, which matches
    # data.table::CJ() ordering.
    rows = list(product(*values))

    return pd.DataFrame(rows, columns=names)


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


def write_scenarios(template, scenarios, experiment_folder, om,
                    validate_xml=True, overwrite=False):

    if "index" not in scenarios.columns:
        raise ValueError("The scenarios table must contain an index column")

    if scenarios["index"].isna().any() or scenarios["index"].duplicated().any():
        raise ValueError("The scenario indices must be unique and non-missing")

    variables = template_variables(template)
    missing = [name for name in variables if name not in scenarios.columns]

    if missing:
        raise ValueError(
            "The following variables were mapped but are missing from the "
            "scenarios table: " + ", ".join(missing)
        )

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

    xml = Path(template["scaffold"]).read_bytes()

    xml = re.sub(
        rb"http://openmalaria\.org/schema/scenario_\d+",
        f'http://openmalaria.org/schema/scenario_{om["version"]}'.encode(),
        xml,
    )

    # remove_blank_text + pretty_print reformat the document like xml2 does
    parser = etree.XMLParser(remove_blank_text=True)

    for row in range(len(scenarios)):
        index = scenarios["index"].iat[row]

        root = etree.fromstring(xml, parser)
        doc = etree.ElementTree(root)

        root.set("schemaVersion", str(om["version"]))
        root.set(
            f"{{{XSI_NS}}}schemaLocation",
            f'http://openmalaria.org/schema/scenario_{om["version"]} '
            f'scenario_{om["version"]}.xsd',
        )

        for path, value in template["replacements"]:
            # variable("name") means:
            # use the value from scenarios["name"] for this row
            if is_variable(value):
                value = scenarios[value.name].iat[row]

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

        # write the XML declaration exactly like xml2/libxml2 does
        with open(xml_folder / f"{index}.xml", "wb") as f:
            f.write(b'<?xml version="1.0" encoding="UTF-8" standalone="no"?>\n')
            doc.write(f, encoding="UTF-8", xml_declaration=False, pretty_print=True)

    print(f"{len(scenarios)} scenarios created")
