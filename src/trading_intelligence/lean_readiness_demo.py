"""Four practical offline prerequisites; this does not execute LEAN."""
import json
from pathlib import Path


def lean_readiness_demo(directory: Path) -> dict:
    from .lean_export_demo import lean_export_demo
    from .baseline import baseline_demo
    from .cash_ledger_demo import cash_ledger_demo
    from .readiness import readiness_demo
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    exported = lean_export_demo(directory / "export")
    from .lean_custom_data import parse_bundle_line
    sample_line = (directory / "export" / "bundle" / "bars.csv").read_text().splitlines()[1]
    sample = parse_bundle_line(sample_line, exported)
    exported["reader_sample"] = {
        "economic_date": sample["row"]["date"],
        "emitted_at": sample["event_time"].isoformat(),
        "economic_end": sample["economic_end"].isoformat(),
        "engine_executed": False,
    }
    result = {
        "origin": "synthetic_fixture",
        "parts": {
            "verified_data_bundle": exported,
            "frozen_baseline_experiment": baseline_demo(directory / "baseline"),
            "cash_position_reconciliation": cash_ledger_demo(directory / "ledger"),
            "configuration_diagnostic": readiness_demo(directory / "readiness"),
        },
        "external_access_verified": False,
        "real_dataset_admitted": False,
        "lean_runtime_executed": False,
        "training_implemented": False,
        "live_trading": False,
        "orders_sent": 0,
    }
    (directory / "report.json").write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
    return result
