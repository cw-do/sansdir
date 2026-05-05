# Test fixtures

## Committed (small, real)

| File | Size | Purpose |
|---|---|---|
| `test_2o5m2o5a_Iq.dat` | ~5 KB | 3-col `q I(q) σI` reduced data — Phase 5 plotting tests |
| `NG7_ORNL_B1_All_4col.dat` | ~15 KB | 4-col `q I(q) σI σq` — Phase 5 plotting tests |

## Gitignored (large, real)

The cluster-resident NeXus file used for end-to-end smoke tests is **not**
committed because GitHub rejects files >100 MB and a single SNS run is
typically several hundred MB.

| File | Size | Source |
|---|---|---|
| `EQSANS_172749.nxs.h5` | ~350 MB | `/SNS/EQSANS/IPTS-*/data/EQSANS_172749.nxs.h5` on the ORNL analysis cluster |

To enable the real-file smoke tests locally, drop the file at
`tests/data/EQSANS_172749.nxs.h5`. Tests requesting `real_nexus_path` will
otherwise auto-skip with an informative message.

## Synthetic (generated at test time)

For unit tests, prefer the `synthetic_nexus` fixture in `tests/conftest.py`,
which materializes a few-KB NeXus file under `tmp_path` with the same
hierarchy SNS uses (`/entry/instrument/bank{1,2}/...`, `/entry/DASlogs/...`,
`/entry/sample/...`). It is fast, deterministic, and works in CI.
