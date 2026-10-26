# Isolated synthetic LEAN observer smoke

This is one concrete backtesting engine smoke, without broker credentials, broker orders or profitability claims. The harness creates two invented daily bars with distinct UTC observation times, then asks LEAN to deliver them as a non-tradable custom-data stream. Economic dates and raw close/currency stay separate from availability. It does not consume private source databases or the Mac's real captures.

## Run on the configured ARM64 Mac

The user has already pulled the exact image below. With Docker running, execute from the repository:

```sh
git pull --ff-only
PYTHONPATH=src python3 -m trading_intelligence.lean_smoke prepare-run \
  --out "$HOME/ti-lean-smoke-001" --timeout 300
```

Use a new dedicated output directory: an existing run is never overwritten or reused. The command prepares the bundle/config/code, runs Docker once, saves logs/evidence and prints a compact final result. No keys, SEC contact or `.env` mount are needed. The already-installed local image is required; `--pull never` prevents implicit downloads.

Pinned runtime:

- Image: `quantconnect/lean@sha256:afc3a126d3ba294784a3f11dff38cdfed020672f021e02df7b24f7e2335ba0ca`
- Platform: `linux/arm64`
- Launcher: `/Lean/Launcher/bin/Debug/QuantConnect.Lean.Launcher.dll`

The Docker command uses `--network none`, drops capabilities and disables privilege escalation. Only `<run>/input` (read-only) and `<run>/output` (writable) are mounted. The input copies Python source files, a standalone observer algorithm, synthetic bundle and local config; it does not mount the repository, host home, Docker socket, databases or environment files. No host environment values are passed into the container. The image's built-in `/Lean/Data`, working/composer directory and Python-library environment remain intact. Object-store/result/log paths point to the dedicated output. Automatic close avoids an interactive launcher prompt.

## Evidence and acceptance

Files remain together under the dedicated directory:

- `input-manifest.json`: pinned image/platform, source/config/bundle hashes and the exact two expected observations. Preparation explicitly reports engine execution unverified.
- `docker-command.json` and `docker-command.sh`: exact reviewable Docker arguments.
- `output/engine.log`: captured container stdout/stderr; additional LEAN result/log files stay in output.
- `output/observer-evidence.json`: actual algorithm callback observations and engine UTC times, counts and zero-order assertions.
- `output/*-summary.json`: LEAN's final saved result, independently checked by the host harness.
- `run-result.json`: passed, failed or blocked verdict after a run attempt.

Success requires unchanged input hashes, fresh output, Docker exit zero, no engine error markers, exact economic-date/availability/close/currency observations, increasing engine times that never precede availability, exactly two observations and zero orders/order events. LEAN's final summary must also have `state.Status == Completed`, empty `RuntimeError`/`StackTrace`, `OrderCount == 0` and a populated `EndTime`. An algorithm's end callback alone cannot establish success. A unique scoped container name allows timeout/failure cleanup without touching other containers.

A passed result verifies only this synthetic custom-data observation path. It does not establish admitted historical data, native equity sessions/actions, broker fills, fee models, full cash reconciliation, strategy quality or live readiness. The custom observer never submits orders and has no external price subscription or default SPY benchmark feed.

## Development verification and source references

Docker is unavailable in the development environment used for this delivery. The prepare path, parser/config contracts, isolation arguments, mocked success/failure artifacts, timeout cleanup and rejection of stale/modified/early/error/order evidence are tested offline. **No actual engine execution is claimed here.** The ARM64 Mac command above produces the evidence needed for that separate acceptance.

`--prepare-only` after `prepare-run` creates inspectable files without starting Docker and always leaves engine execution unverified. It is useful for offline CI, not an engine acceptance result.

Compatibility reference `f3d841e60dfd010ee5fc293ea893e56952484108` is an upstream API/config checkpoint, not proof that the image was built from that exact source commit. Primary sources inspected:

- https://github.com/QuantConnect/Lean/blob/f3d841e60dfd010ee5fc293ea893e56952484108/Launcher/config.json
- https://github.com/QuantConnect/Lean/blob/f3d841e60dfd010ee5fc293ea893e56952484108/Configuration/LeanArgumentParser.cs
- https://github.com/QuantConnect/Lean/blob/f3d841e60dfd010ee5fc293ea893e56952484108/Engine/Results/BacktestingResultHandler.cs
- https://github.com/QuantConnect/Lean/blob/f3d841e60dfd010ee5fc293ea893e56952484108/Engine/Results/BaseResultsHandler.cs
- https://www.quantconnect.com/docs/v2/writing-algorithms/importing-data/streaming-data/custom-securities/csv-format-example

The wrapper and algorithm are own-written; no upstream implementation is vendored.
