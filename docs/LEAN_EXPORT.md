# Deterministic daily bundle contract

`export_bundle(store, source_id, listing_id, expected_dates, as_of=..., directory=...)` exports a complete explicitly declared replay scope. The current implementation accepts synthetic sources only. Real-source export fails closed until an approved admission report can be bound to this exact artifact, source, identity, scope and knowledge cutoff.

`verify_bundle(directory)` returns `{manifest, bars, synthetic, lean_runtime_verified}`. Files are `bars.csv`, `replay.json` and `manifest.json`. The manifest preserves the replay snapshot/evidence lineage, cutoff, explicit listing/currency and SHA-256 file hashes. CSV columns are date,start,end,currency,open,high,low,close,volume,available_at. Prices remain raw; no split/dividend adjustment or fictitious returns are introduced. Read verification checks hashes, chronology/scope, currency and equality with the replay's original daily bodies. An existing destination cannot silently change to another bundle.

Economic bar end and information availability are different. Consumers must obtain each row's available_at (maximum session/bar known_at), also retained in `manifest.replay.records`; they cannot trade at that bar's opening or closing price using facts first known later. The bundle is a candidate own-data interface for a future LEAN worker, not a completed LEAN importer, execution simulator or successful runtime trial.

Hashes detect accidental modification against the supplied manifest. This is not a signed provenance certificate: an attacker able to replace all files and hashes can create another self-consistent bundle. Original source bytes remain in the evidence store and are referenced by hash rather than repackaged. No historical availability, authoritative calendar, complete universe, data license or training readiness is certified.

`lean_export_demo(directory)` creates two invented dates and exports them reproducibly. It never downloads data or starts LEAN. Tests cover repeat/reimport, file tampering, altered dates/currency and rejection of unbound real sources. The own-written optional PythonData class below is a concrete integration contract; an actual engine run remains a separate motor trial. No upstream implementation is copied here.

## Concrete optional PythonData adapter

`lean_custom_data.lean_data_type(bundle_directory)` constructs an own-written `PythonData` subclass when LEAN's `AlgorithmImports` is installed. Its `get_source` returns the verified local CSV via `SubscriptionDataSource`/`SubscriptionTransportMedium.LOCAL_FILE`; its `reader` accepts only exact rows from the verified bundle. The pure helper `parse_bundle_line` is independently runnable and tested without LEAN.

The subscription must declare UTC data timezone and `fill_forward=False`. Both `time` and `end_time` are the row's observed `available_at`, so the economic bar date is not used to emit information early. Economic date/start/end and currency remain separate properties. Live reads are blocked. Nonmonotonic availability order fails closed. This custom stream is for observation/research; it does not inherit native equity corporate-action, exchange-session or fill semantics and must not be traded as if its late observed close were an executable price.

Compatibility reference: QuantConnect/Lean commit `f3d841e60dfd010ee5fc293ea893e56952484108`, inspected API `Common/Python/PythonData.cs`. This records the upstream API checkpoint only; no engine has been installed or executed. The adapter's mechanics are tested with a small API test double, not a simulated claim of a LEAN run. Before deployment, pin and install a compatible runtime and run the full engine acceptance trial.

Official documentation: https://www.quantconnect.com/docs/v2/writing-algorithms/importing-data/streaming-data/custom-securities/key-concepts and https://www.quantconnect.com/docs/v2/writing-algorithms/importing-data/streaming-data/custom-securities/csv-format-example . These describe overriding `get_source`/`reader`, setting `end_time` to information availability and the limits of custom-security modeling. The wrapper and verification policy here are our own code.

Export operations also require current storage and research permissions, evaluated with an injectable operational clock; a historical `as_of` cannot bypass current revocation or lie in the operational future. Offline `verify_bundle` audits the frozen archive only and cannot establish current database entitlements or authorize use after a revocation.
