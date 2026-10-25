"""Four distinct synthetic demonstrations; no external service or training."""
import json
from pathlib import Path


def research_foundations_demo(directory: Path) -> dict:
    from .price_demo import price_demo
    from .sec_filings import sec_demo
    from .artifacts_demo import artifacts_demo
    from .outcome_queue import outcomes_demo
    directory.mkdir(parents=True, exist_ok=True)
    result = {
        "origin": "synthetic",
        "parts": {
            "price_capture": price_demo(directory / "prices"),
            "sec_submissions": sec_demo(directory / "sec"),
            "artifact_incident_lineage": artifacts_demo(directory / "artifacts"),
            "locked_predictions_outcomes": outcomes_demo(directory / "outcomes"),
        },
        "authenticated_access_verified": False,
        "training_implemented": False,
        "training_ready": False,
        "lean_replay_implemented": False,
        "orders_sent": 0,
        "live_trading": False,
    }
    (directory / "report.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    return result
