# Two-source captured admission assessment

The reported Mac observer pass proves propagation of 17 captured rows, not admission for a strategy backtest. The earlier `DataAdmissionStore.assess` addresses one price page and calendar under one source. Real captures use separate source identities and a synchronization job with potentially multiple pages. This assessment supports that actual shape without copying data into market snapshots or declaring it admitted.

## Existing Mac captures

With the project virtual environment active, run:

```sh
git pull --ff-only
PYTHONPATH=src python3 -m trading_intelligence.captured_admission assess \
  --database data/research.sqlite3 \
  --price-source alpaca-prices --price-import apple-october-prices-001 \
  --calendar-source alpaca-calendar --calendar-import calendar-october-001 \
  --listing apple-xnas --purpose historical_replay \
  --out "$HOME/ti-admission-$(date -u +%Y%m%dT%H%M%SZ)"
```

Docker, keys and new network requests are not required. The command opens the existing database read-only, creates no database/schema/review records, and uses a fresh private output directory. Missing or corrupt captures fail rather than creating a replacement database. `status=blocked` is an assessment result, not a failed LEAN invocation. Missing review records and unknown historical publication are expected to appear for the current captures. Send the terminal assessment, not the database or credentials.

The packet contains `inspection.json`, `scope.json`, `assessment.json` and an explicitly unreviewed `review-template.json`; terminal output includes their SHA256 hashes. Keep it local: it contains exact observations and route/account identifiers. Each file has mode 600 inside a mode 700 directory. A hash protects content binding, not provider authentication or reviewer identity.

## Scope and reviews

`capture_scope` binds both source/import identities, canonical listing, selected dates/feed and a fingerprint of the complete validated inspection excluding only assessment clock/hash. All page capture IDs/raw hashes, provenance/query/route, calendar lineage, row values and original times are therefore bound. Rechecking at a later operational time retains the scope. Changing a source, import, page, route or data changes it and requires new applicable reviews.

The existing immutable `DataAdmissionStore.record_review` accepts this version-2 scope. Storage/research rights, provenance, temporal basis and coverage require separate evidence-backed reviews **for each source**. Templates have no reviewer, decision, proof references, expiry or default rights approval. They are requests for actual review, not scripts to mark everything allowed. Review evidence must already be archived under the matching source; operational review times cannot be backdated. Source terms, feed entitlement and calendar/listing applicability need actual evidence, not invented declarations. Do not relabel the calendar venue solely to make a check pass.

Every assessment revalidates raw bytes, job pagination, exact dates, route/identity, current source uses and latest nonexpired applicable reviews. A missing reviews table means no reviews; it is not silently created. Denials, expiry, source revocation, mismatched temporal basis and invalid archived evidence remain effective. The legacy single-source assessor rejects the new scope with a pointer to this assessor rather than misinterpreting it.

## Purpose and next dependency

- `forward_observation` uses `observed_receipt_and_processing`; even all valid declared reviews establish only caller-declared eligibility for that purpose. They do not establish independent certification, historical trading availability or source authentication.
- `historical_replay` uses `documented_publication_vintage` and is hard-blocked while publication/vintage remains unknown. Receipt on 26 October cannot make the earlier October bars known at their historical closes. A temporal review cannot override this.
- A calendar/listing venue mismatch is a hard block for both purposes; it cannot be approved away by a review.

The report shows original first/last availability and how many rows were available by their own session close. It does not roll a missed next-session baseline intention to a later opening or fabricate missing future calendar coverage. Even declared forward eligibility leaves `dataset_admitted`, `publication_verified`, `training_ready`, `full_history_verified`, `promotion_performed`, profitability and live trading false. Baseline blockers separately retain real-data admission, corporate-action coverage, executable price/cost assumptions and frozen experiment binding.

Next resolve the evidence gaps from the actual Mac report. Genuine historical replay needs a documented historical vintage, applicable sessions and corporate-action coverage; a forward experiment instead needs a frozen protocol before future outcomes and subsequent time-correct captures. Neither branch permits turning the existing successful observer inspection directly into a trading-price or training dataset. Export/promotion and the frozen LEAN cash/cost run remain later dependencies.

## Verification

Fifteen invented-source regression cases cover separate sources, stable clock-independent binding, all pages, substitutions and corruption, missing tables, rights revocation, denial/expiry, venue mismatch, unknown publication despite all allow assertions, wrong-source proof rejection, caller transactions, read-only database preservation, private packet hashes and a real local CLI subprocess. They exercise local contract behavior; no genuine provider dataset was admitted and no new LEAN engine run was performed.
