# Source-cited event scenario analysis

This additive research layer connects the [event pipeline](EVENT_PIPELINE.md) to
OpenAI Responses. It produces conditional economic investigation scenarios from
the existing verified event/facility context. It does not forecast returns,
compare executable market prices, evaluate portfolio risk or submit orders.

## Data path

1. `EventAnalysisStore` reuses `EventContextStore` and the same SQLite database.
   It verifies historical/current research rights, original hashes, event revisions,
   canonical company/listing identities and dated supplied facility assertions.
2. `prepare_analysis` freezes the context, deterministic typed facts, exact prompt,
   output schema, model, code digest, token limit and expiration before inference.
   Every factual citation must resolve to a fact in that packet. External source
   text is data, never an instruction to the reader.
3. `start_analysis` commits an exclusive dispatch claim before the paid operation.
   `OpenAIEventReader` makes one bounded HTTPS POST to the fixed Responses endpoint,
   using strict structured outputs and `store:false`. No tools, broker credentials,
   automatic retries, redirects or alternative endpoints are configured.
4. The parser rejects refusal, incomplete responses, tool calls and malformed JSON.
   The store validates citations, company/listing identity, explicit uncertainties,
   counterarguments, invalidation conditions and follow-up checks. Investigation
   requires alternatives including no disruption; missing/ambiguous context forces
   abstention. Geographic proximity never certifies damage.
5. Accepted cards preserve exact response bytes and metadata, input/response hashes
   and completion availability. They cannot appear at the earlier input cutoff.
   Corrections create new requests/cards; they do not rewrite old analyses.

The prompt can consider adverse, beneficial, mixed, unknown or no economic effects.
These are conditional hypotheses, not long/short instructions. Valid JSON and a
valid citation establish linkage, not that the model's interpretation is true.
All model prose remains unverified. No win probability, return target or order
field is accepted in the machine-readable schema.

## Offline proof

```sh
PYTHONPATH=src python3 -m trading_intelligence event-analysis-demo --out data/event-analysis-demo
```

The fictional near-facility event yields adverse/no-disruption alternatives via
the actual Responses transport/parser with an injected synthetic response. A
later source correction moves the event away and yields abstention. A fresh
process can reproduce the report and retrieve the original card. This command
needs no key or network and is included in CI.

## One API-backed analysis

Use an existing source-configured database with reviewed event/facility records.
Set `OPENAI_API_KEY` in the process environment, or select an ignored local env
file using `--env-file .env.local`. That option reads only the named credential;
it does not execute the file or export other credentials. Never commit this file.

```sh
PYTHONPATH=src python3 -m trading_intelligence event-analyze \
  --database data/events.sqlite3 \
  --request-id UNIQUE_REQUEST_ID --analysis-id UNIQUE_CARD_ID \
  --source-id REVIEWED_EVENT_SOURCE --event-id NATIVE_EVENT_ID \
  --as-of TIMEZONE_AWARE_INPUT_CUTOFF --expires-at TIMEZONE_AWARE_EXPIRATION \
  --radius-km 100 --model ACCOUNT_ACCESSIBLE_MODEL_SNAPSHOT \
  --max-output-tokens 4096 --env-file .env.local \
  --external-processing-reviewed
```

Replace the uppercase arguments with actual registered IDs, timezone-aware ISO
timestamps and an account-accessible model. The investigation radius is not a
damage estimate. Prefer a dated model snapshot where available. The CLI hashes
the package source actually running and stores that digest with the request.

The external-processing flag signals the operator's dispatch decision; it is not
independent entitlement certification. Storage/research declarations alone do
not establish a license to transmit a vendor dataset to an external AI service.
Review source/product rights before selecting real or licensed inputs. API usage
uses the configured Platform project's billing and usage controls.

An identical completed request/card returns its archived result without another
API call. Reusing an ID with changed input is a conflict. Pending or failed claims
cannot be resubmitted automatically: inspect the archived state, then explicitly
create a new request ID if another call is appropriate. A crash after the remote
response and before recording can leave pending state; this does not establish
that no remote processing or billing occurred. Failure journals contain fixed
sanitized codes, not provider bodies or secrets. Responses arriving after expiry
remain audit records marked `expired_on_arrival`.

## Evaluation and remaining integration

Historical cutoffs freeze supplied evidence, but cannot remove facts a pretrained
model may already know. Every card explicitly marks historical predictive
evaluation invalid. This is not an alpha backtest or a calibrated impact model.
CI and offline tests use only synthetic fixtures. A live API check on synthetic
evidence verifies API integration only, not real-world forecast quality.

Event requests/cards have their own immutable dependencies. Generic typed event
bindings in `ArtifactRegistryStore`/`OutcomeQueueStore`, semantic claim review,
cross-source incident resolution, production facility/supplier coverage and the
100–200-case quality evaluation remain future work. No model is trained or
automatically promoted here.

Next, reviewed operating-status/news evidence and point-in-time market inputs can
support a separately evaluated comparison of remaining opportunities after costs.
Only an accepted strategy may later feed the deterministic portfolio/risk/LEAN
boundary. The frozen forward pilot is unaffected by these scenario cards.

## Official API references

- [Structured outputs](https://developers.openai.com/api/docs/guides/structured-outputs)
- [Responses create](https://developers.openai.com/api/reference/resources/responses/methods/create)

The transport uses Python's standard library; no additional runtime dependency
or trading engine was installed.
