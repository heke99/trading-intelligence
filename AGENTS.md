# Project instructions

- Keep the Collective2 importer read-only. Do not add trading, order submission, subscriptions, or model training to this foundation.
- Run tests offline with synthetic fixtures. Never use a real API key, trader export, or authenticated request in tests or CI.
- Keep secrets, original trader data, and generated databases out of Git; inspect the staged file list before committing.
- Preserve raw evidence and label source, strategy, record type, timezone basis, and hypothetical versus synthetic origin accurately.
- Reproduce a verified bug with a failing regression test before changing its implementation. Keep `training_ready=false` and `full_history_verified=false` until separately justified.
