# IMMploy Locum Booking performance baseline

Measured locally on 31 July 2026. This is a development baseline, not a production capacity claim.

## Dataset and environment

- PostgreSQL 16.14
- Database size: approximately 11 MB
- 367 candidates and 6 current shift records at measurement time
- Host: 16 GB RAM, 10 logical CPUs
- PostgreSQL settings observed: `shared_buffers=128MB`, `work_mem=4MB`, `maintenance_work_mem=64MB`, `effective_cache_size=4GB`
- `pg_stat_statements` is not currently preloaded or installed

## Warm authenticated API measurements

Each endpoint was requested 20 times using the real Django/DRF stack and local PostgreSQL connection. Times include request handling and serialization.

| Endpoint | Items | SQL queries | p50 | p95 |
|---|---:|---:|---:|---:|
| Shift list | 6 | 1 | 2.54 ms | 3.81 ms |
| Candidate directory | 367 | 2 | 32.37 ms | 65.01 ms |
| Vacancy creation options | 2 groups | 2 | 5.96 ms | 8.82 ms |
| Facility/role rate default | 2 values | 2 | 1.04 ms | 1.65 ms |
| Eligible candidate shortlist | 1 | 4 | 5.73 ms | 7.33 ms |

## Query-plan improvement applied

The candidate-overlap query previously annotated an `EXISTS` value and then filtered it. PostgreSQL consequently evaluated an avoidable duplicate subplan. It now filters directly with `NOT EXISTS`.

Representative `EXPLAIN (ANALYZE, BUFFERS)` results on the same data:

| Candidate eligibility plan | Before | After |
|---|---:|---:|
| Execution time | 0.432 ms | 0.181 ms |
| Shared buffers hit | 42 | 30 |
| Planning time | 3.296 ms | 1.617 ms |

A 30-request endpoint recheck after the change measured shortlist p50 at 5.23 ms and p95 at 7.14 ms, with the same four-query bound and eligibility behavior.

Nested vacancy creation was also profiled at realistic batch sizes. The original model-by-model path repeated validation and response-fetch queries for every child shift. The serializer now validates the nested payload once, inserts the already validated child rows in one PostgreSQL bulk statement inside the same atomic transaction, and serializes from a bounded prefetch.

| Shifts created | Before: time / queries | After: time / queries |
|---:|---:|---:|
| 1 | 46.06 ms / 30 | 41.56 ms / 14 (cold request) |
| 7 | 40.30 ms / 130 | 11.63 ms / 12 |
| 31 | 146.18 ms / 538 | 13.20 ms / 12 |
| 100 | 451.51 ms / 1,711 | 26.92 ms / 12 |

The transaction and all-or-nothing rollback behavior remain covered by regression tests. A permanent 31-shift query-bound test prevents the linear-query regression from returning. Booking confirmation measured p50 at 7.68 ms and p95 at 8.99 ms over 20 real create requests, with the existing transactional locking and concurrency protection unchanged.

## Facility-linked role lookup

The 31 July legacy synchronization imported 35,588 valid client/role rate mappings from `tbl_job_functions_client_vals` into PostgreSQL. Ordinary vacancy-form requests never query legacy MySQL. The facility lookup uses the PostgreSQL client foreign-key index, joins the small profession table, and applies any site-specific learned rate override in at most three SQL queries.

For a representative facility with 95 linked roles, 50 warm authenticated requests measured p50 at 4.043 ms and p95 at 4.886 ms. The underlying `EXPLAIN (ANALYZE, BUFFERS)` completed in 1.450 ms with 18 shared-buffer hits; PostgreSQL used a bitmap index scan on `client_id`. No speculative additional index was added.

## Decisions

The database is not presently the user-visible bottleneck. It is only about 11 MB, the measured operational endpoints are below 10 ms p95 except the full 367-row candidate directory, and the query planner correctly prefers sequential scans for tiny tables.

Do **not** apply generic production values such as `work_mem=64MB` or allocate 25–40% of host RAM to `shared_buffers` on this development system. `work_mem` is per sort/hash operation and per concurrent query, so blanket increases can multiply memory consumption. Durability, WAL, autovacuum, and cache settings should only be changed after measuring the production host and workload.

## Testing and production readiness targets

- Shift board and creation options: p95 below 200 ms
- Candidate shortlist: p95 below 300 ms with representative candidate and booking volumes
- Booking confirmation: p95 below 500 ms without lock contention
- Zero duplicate confirmed bookings under concurrent submissions
- Vacancy creation remains atomic at 1, 7, 31, and 100 generated shifts
- Add pagination or virtual rendering before the active directory grows beyond a few thousand candidates
- Enable `pg_stat_statements` in the production-like PostgreSQL deployment, then rank tuning work by total execution time and call count
- Add PgBouncer only when measured concurrent connection demand warrants it
- Add indexes only when representative `EXPLAIN (ANALYZE, BUFFERS)` plans demonstrate scan or sort cost; current tiny-table sequential scans are faster than forced index access
