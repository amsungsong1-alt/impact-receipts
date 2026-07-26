"""
test_taxonomy.py — golden tests for utils/taxonomy.py (Laudon Ch.11 MEL taxonomy, C7):
loading knowledge/taxonomy.yaml and the OECD-DAC criterion mapping.

No pytest, no network calls. Run with: python test_taxonomy.py
"""

from utils import taxonomy


def run_taxonomy_loads_cleanly():
    failures = []
    data = taxonomy.load_taxonomy()

    if not data:
        failures.append("load_taxonomy() returned an empty dict -- knowledge/taxonomy.yaml failed to load")

    for key in ("version", "sectors", "evaluation_types", "result_levels", "oecd_dac_mapping"):
        if key not in data:
            failures.append(f"taxonomy.yaml is missing expected top-level key {key!r}")

    if failures:
        print("FAILED:")
        for f in failures:
            print("  -", f)
        raise SystemExit(1)
    print("PASS: taxonomy loads cleanly — all expected top-level keys present.")


def run_evaluation_types_and_result_levels():
    failures = []
    eval_types = taxonomy.get_evaluation_types()
    result_levels = taxonomy.get_result_levels()

    if "Baseline" not in eval_types or "Impact evaluation" not in eval_types:
        failures.append(f"expected evaluation_types to include Baseline/Impact evaluation, got {eval_types}")
    if result_levels != ["Output", "Outcome", "Impact"]:
        failures.append(f"expected result_levels to be the standard logframe hierarchy, got {result_levels}")

    if failures:
        print("FAILED:")
        for f in failures:
            print("  -", f)
        raise SystemExit(1)
    print("PASS: evaluation_types/result_levels — expected values present.")


def run_oecd_dac_mapping():
    """Only 4 of the 8 DIMENSION_MAP dimensions have a real OECD-DAC citation
    anywhere in this codebase (framework_crosswalk.FRAMEWORKS["OECD-DAC"]) --
    the mapping must reflect that honestly, not force-map the other 4."""
    failures = []

    mapped_cases = [
        ("Directness", "Effectiveness"),
        ("Definition", "Relevance"),
        ("Scope", "Coherence"),
        ("Governance", "Sustainability"),
    ]
    for dimension, expected in mapped_cases:
        got = taxonomy.get_oecd_dac_criterion(dimension)
        if got != expected:
            failures.append(f"expected {dimension} -> {expected!r}, got {got!r}")

    unmapped_cases = ["Verification", "Recency", "Measurement", "Integrity"]
    for dimension in unmapped_cases:
        got = taxonomy.get_oecd_dac_criterion(dimension)
        if got is not None:
            failures.append(
                f"{dimension} has no real OECD-DAC citation anywhere in this codebase -- "
                f"expected None (not directly assessed), got {got!r}"
            )

    # An unknown/malformed dimension name must degrade to None, never raise.
    if taxonomy.get_oecd_dac_criterion("NotARealDimension") is not None:
        failures.append("an unrecognized dimension name should return None, not a force-mapped guess")
    if taxonomy.get_oecd_dac_criterion("") is not None:
        failures.append("an empty string dimension should return None")

    if failures:
        print("FAILED:")
        for f in failures:
            print("  -", f)
        raise SystemExit(1)
    print("PASS: OECD-DAC mapping — 4 real citations verified, the other 4 dimensions correctly "
          "return None (not directly assessed), unknown input degrades safely.")


def run_degrades_gracefully_on_missing_file():
    """load_taxonomy() must return {} (not raise) when knowledge/taxonomy.yaml
    doesn't exist -- matches utils/inference.py's degrade-gracefully convention."""
    failures = []
    original_path = taxonomy._TAXONOMY_PATH
    taxonomy._TAXONOMY_PATH = "/nonexistent/path/that/does/not/exist.yaml"
    try:
        data = taxonomy.load_taxonomy()
        if data != {}:
            failures.append(f"expected {{}} for a missing taxonomy file, got {data}")
        if taxonomy.get_oecd_dac_criterion("Directness") is not None:
            failures.append("expected None when the taxonomy file can't load, got a value")
        if taxonomy.get_evaluation_types() != []:
            failures.append("expected [] for evaluation_types when the taxonomy file can't load")
    finally:
        taxonomy._TAXONOMY_PATH = original_path

    if failures:
        print("FAILED:")
        for f in failures:
            print("  -", f)
        raise SystemExit(1)
    print("PASS: missing taxonomy file degrades to {}/[]/None everywhere, never raises.")


if __name__ == "__main__":
    run_taxonomy_loads_cleanly()
    run_evaluation_types_and_result_levels()
    run_oecd_dac_mapping()
    run_degrades_gracefully_on_missing_file()
