"""
utils/taxonomy.py — Laudon Ch.11, C7: MEL taxonomy and expertise location.

Loads knowledge/taxonomy.yaml (versioned, hot-reloadable — same discipline as
utils/inference.py's rule base) and exposes the OECD-DAC criterion mapping for a given
DIMENSION_MAP dimension. This is the substrate for the benchmark/systemic-gaps features and an
eventual "organisations like yours score X on Verification" comparison — actually wiring it
into the existing benchmark bucketing (utils/audits.py's audit_aggregate_stats) is a further,
separate step, deliberately not attempted here.

No Streamlit import, no API calls — pure read of a static YAML file, same UI-free discipline
as evaluator.py/diagnostics.py.
"""
from __future__ import annotations
import os

import yaml

_TAXONOMY_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "knowledge", "taxonomy.yaml"
)


def load_taxonomy() -> dict:
    """Re-reads knowledge/taxonomy.yaml fresh on every call -- hot-reloadable,
    same convention as utils/inference.py::load_rule_base(). Returns {} if
    the file is missing or malformed rather than raising."""
    if not os.path.isfile(_TAXONOMY_PATH):
        return {}
    try:
        with open(_TAXONOMY_PATH, "r", encoding="utf-8") as f:
            loaded = yaml.safe_load(f)
        return loaded if isinstance(loaded, dict) else {}
    except Exception:
        return {}


def get_evaluation_types() -> list:
    return load_taxonomy().get("evaluation_types", [])


def get_result_levels() -> list:
    return load_taxonomy().get("result_levels", [])


def get_oecd_dac_criterion(dimension: str) -> str | None:
    """The OECD-DAC 2019 criterion name for one of the 4 DIMENSION_MAP
    dimensions framework_crosswalk.py actually cites under OECD-DAC
    (Directness/Definition/Scope/Governance), or None for the other 4
    (Verification/Recency/Measurement/Integrity) -- "not directly assessed,"
    never a force-mapped guess."""
    mapping = load_taxonomy().get("oecd_dac_mapping", {})
    return mapping.get(dimension)
