"""A repeatable offline demonstration, containing invented data only."""

import argparse
from datetime import datetime
import json
from pathlib import Path

from .contracts import AssetKind, DataOrigin, Entity, Instrument, Listing, Use
from .store import EvidenceStore


def demo(directory: Path) -> dict:
    directory.mkdir(parents=True, exist_ok=True)
    first = datetime.fromisoformat("2026-01-01T12:00:00+00:00")
    corrected = datetime.fromisoformat("2026-01-05T12:00:00+00:00")
    effective = datetime.fromisoformat("2025-01-01T00:00:00+00:00")
    with EvidenceStore(directory / "evidence.sqlite3") as store:
        store.register_source("synthetic-demo", DataOrigin.SYNTHETIC)
        store.set_permissions("synthetic-demo", known_at=effective, uses={Use.STORAGE, Use.RESEARCH})
        store.register_entity(Entity("demo-company", "Invented example company"))
        store.register_instrument(Instrument("demo-equity", "demo-company", AssetKind.EQUITY))
        store.register_listing(Listing("demo-old-listing", "demo-equity", "XNAS", "USD"))
        store.register_listing(Listing("demo-new-listing", "demo-equity", "XNYS", "USD"))
        old = store.ingest(source_id="synthetic-demo", record_id="listing-map", revision_id="1",
                           payload=b'{"listing":"demo-old-listing"}', published_at=first, received_at=first)
        new = store.ingest(source_id="synthetic-demo", record_id="listing-map", revision_id="2",
                           payload=b'{"listing":"demo-new-listing"}', published_at=first,
                           received_at=corrected, correction_of=old)
        for at, listing, evidence in [(first, "demo-old-listing", old), (corrected, "demo-new-listing", new)]:
            store.put_identifier(mapping_id="demo-map", provider="synthetic", value="DEMO",
                                 listing_id=listing, valid_from=effective, known_at=at, evidence_id=evidence)
        before = store.resolve_identifier("synthetic", "DEMO", effective_at=first, as_of=first)
        after = store.resolve_identifier("synthetic", "DEMO", effective_at=first, as_of=corrected)
        return {"origin": DataOrigin.SYNTHETIC.value, "before_correction": before,
                "after_correction": after, "counts": store.counts(),
                "training_implemented": False, "live_trading": False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    command = commands.add_parser("demo", help="Run an invented offline evidence and identity example")
    command.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(demo(args.out), indent=2))


if __name__ == "__main__":
    main()
