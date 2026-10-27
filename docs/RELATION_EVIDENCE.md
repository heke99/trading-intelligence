# Synthetic reviewed relation evidence

This bounded Phase 1c contract proof supports supplied **synthetic UTF-8 text only**. It does not admit real data, run an LLM, verify a reviewer's identity, infer causality or produce predictions/orders. A declared review is metadata, not independent semantic certification.

`RelationEvidenceStore` extends the existing `ArtifactRegistryStore`, reusing original-byte hashes, exact source dependencies, operational registration time, research permission checks at historical and current cutoffs, and confirmed incident blocking. No upstream source or new package is introduced.

A relation version binds registered entity IDs, directional type (`supplies_to`, `customer_of`, `consolidated_by`, `competitor_of`), exact evidence ID, Unicode character offsets and matching nonempty text, declared reviewer and affirmed/denied status. Offsets are zero-based half-open Python string indices, not UTF-8 byte offsets. Missing spans and copied/example text that does not match the source are rejected. A matching span does not verify entity resolution, negation, relation semantics or truth. Entity registration alone does not establish a historically valid identity assertion.

Economic validity is `[valid_from, valid_until)`; a null end means a declared open interval, not a prediction of permanent validity. Knowledge and actual registration remain distinct. Corrections must explicitly extend the current version of the same relation identity with strictly later declared knowledge. Direction/type/entity changes require a different relation family. A denial can retract a previously asserted relation.

Historical queries first choose the visible version head, then apply validity. A later closure/denial therefore cannot resurrect an older open interval or alter the earlier knowledge snapshot. Current rights revocation and confirmed incidents still block retrieval at historical cutoffs. Queries fail closed on an unusable visible artifact rather than silently omitting it. Artifact-byte or dependency corruption is checked by the shared registry.

This small proof scans relation artifacts and requires an externally serialized single writer. It is not a concurrent graph service; no locking/fencing, production indexes or transactional family-head reservation is implemented. Ambiguous visible heads block reading. No relation-chain traversal, exposure percentage, contradiction resolution, automatic source-revision invalidation, evidence-admission review, LangExtract integration or economic-value evaluation is included. Source corrections must be explicitly reviewed into new relation versions; old source bytes remain archived. Existing per-source permission declarations remain distinct from genuine data admission.

Run the reproducible invented-data proof:

```sh
PYTHONPATH=src python3 -m trading_intelligence.relation_evidence_demo
PYTHONPATH=src python3 -m unittest discover -s tests -p test_relation_evidence.py -v
```

The old cutoff shows the original open relation while the corrected cutoff shows it closed. Both reports remain `research_admitted=false` and `orders=0`. Tests cover source spans with non-ASCII text, restart/idempotence, backdating, correction boundaries, denial, conflicting branches, identity changes, current revocation and confirmed incidents. They do not establish analyst intelligence or alpha. The frozen forward pilot is unchanged.
