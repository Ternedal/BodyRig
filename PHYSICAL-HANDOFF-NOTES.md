# Temporary physical-handoff validation notes

This file belongs only to the scratch validation branch for the PR #83 continuation.

The change creates a fresh Gate A for the exact final promoted package, reusing only the original hash-bound physical session/readiness as source lineage. Fresh skin/topology QA and a fresh materialized runtime are generated for the promoted bytes. The existing canonical acceptance state machine remains authoritative for Windows, Quest and final release.

No physical PASS or production activation is created by this software change. The temporary validation branch must not become a new integration authority; successful validation is intended to be folded back into PR #83.
