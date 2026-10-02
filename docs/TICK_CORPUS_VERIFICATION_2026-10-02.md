# Tick-corpus verification, 2026-10-02

Baseline: frozen upstream PR #9 head `008332051a025c01f34496ac4aeb979ee43b768c`.
The scratch checkout was absent; 87 source files were materialized from that
verified GitHub tree before editing. Local materialization is not a new upstream
implementation or an original data acquisition.

## Observed behavior

- Baseline: 434 offline tests ran successfully on local Python 3.12; 11 optional
  HDF tests were skipped because h5py is not installed locally.
- New corpus suite: 29 synthetic tests. Includes both source formats, row/byte
  limits, no equal-clock splitting, exact prices/row locators, tamper checks,
  strict inventory types, interruption receipts and installed CLI paths.
- A wholly fictional CSV with 510,001 quotes, larger than 32 MiB and 500,000 rows,
  was streamed into bounded shards and all quotes were rechecked. It is not
  exchange or broker data.
- Three defects were reproduced before their implementation fixes: copied
  positive model/expert/forward assertions; a manifest falsely promoting
  multi-shard training; non-integer counts accepted by numeric equivalence.
  Initial failing regressions were retained and now pass.
- Test helper `fail` was renamed to avoid overriding unittest's assertion
  failure method. No assertions were weakened.

Current local full suite: **463 tests**, successful, **11 optional skips**.
GitHub CI is configured to run all tests with h5py on Python 3.11/3.12/3.13,
existing fictional demos, and installed-package sharding/verification outside
the repository. This document records local evidence; the current remote head,
run identifier and CI conclusion must be read from the draft PR before claiming
remote success. Older 434-test CI proves only the older head.

## Scope and remaining limits

Original market tick archives acquired in this step: **0**. New complete
Fabio/Siva fill histories: **0**. No broker credentials, order submission,
training on these missing originals or terminal compilation occurred.

The intake layer handles one local CSV <=1 GiB, <=4,096 shards, <=4,096 bytes per
physical source line, and <=64 KiB evidence. Each shard remains <=32 MiB and
<=500,000 quotes. No ZIP extraction or network downloader was added.

The verifier checks local shard evidence against an unsigned manifest, not
publisher authenticity or the archived original. It reports
`raw_source_rechecked=false`. Calendar completeness, executable liquidity and
rights remain unverified. Whole-corpus chronological training/state continuity,
cross-shard projection/labels and a global holdout are **not implemented**.
Independent per-shard benchmarks must not be represented as one corpus-trained
model. All real-data acceptance and trading flags remain false.

Strategy-source rechecks confirm previously separated teaching versions, not new
personal fills. The updated strategy audit references the current Fabio
publisher page and explicitly retains the Siva short-heading conflict and
unverified user spelling. PDF text-index access is not completed original-image
verification. No restricted raw-data acquisition was retried.
