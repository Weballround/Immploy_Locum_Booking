# IMMploy Locum Booking effectiveness roadmap

**Research date:** 17 August 2026; code/system audit updated 28 August 2026
**Scope:** Current Django/React application, repository documents, supplied manual screenshots, and current public product/architecture sources.

## Executive decision

IMMploy already has the difficult safety core: server-authoritative rates, permission checks, profession and compliance checks, candidate interval-overlap prevention, shift-capacity enforcement, atomic bulk booking, ranked matching, Facility-origin booking, Candidate-origin booking, and a read-only legacy reference-data sync.

The next release should **not** rewrite this booking engine. The highest-value work is an operations layer that helps consultants see what needs attention, create repeated shifts faster, make candidate decisions with less navigation, and handle offers, cancellations, replacements, and sync exceptions explicitly.

Booking write-back to the old MySQL system must remain disabled until IMMploy can perform the final availability check and booking creation atomically in the legacy database. A PostgreSQL availability check followed by an unrelated MySQL insert cannot prevent cross-system races.

## Evidence reviewed

### 28 August code and system audit addendum

The current source-protection, authorization, deployment and performance review is recorded in [`booking-system-code-and-system-audit-2026-08-28.md`](booking-system-code-and-system-audit-2026-08-28.md). It confirms that the scheduling core remains server-authoritative, but the system is not “encoded”: browser JavaScript remains inspectable and backend Python is protected by server permissions rather than obfuscation. Commercial pay/client-charge visibility needs a dedicated backend permission boundary.

A two-instance single-host web topology is prepared locally: Nginx `least_conn` balances API/Admin requests across independently restartable Gunicorn instances on loopback ports 8001 and 8002. Total concurrency remains four threads, matching the previous service, pending production measurement. This is process resilience and safer rolling maintenance—not multi-host high availability.

### Repository evidence

- `PRODUCT_RESEARCH.md`
- `BOOKING_FLOW_RESEARCH.md`
- `PERFORMANCE_BASELINE.md`
- `README.md`
- `docs/IMMploy Booking System - Simple User Manual.docx`
- `docs/legacy-booking-sync-safety.md`
- `docs/integrations/legacy-booking-field-map.md`
- all five screenshots under `docs/manual-assets/`
- current scheduling models, API views, serializers, permissions, tests, and React UI

### Current product strengths verified in code

1. `Booking.save()` locks the booking, affected shifts, and candidate in a transaction before validation.
2. Confirmed bookings enforce active Candidate, cleared compliance, compatible profession, available shift capacity, and true interval overlap checks.
3. Bulk assignment is transaction-wrapped and capped at 100 assignments.
4. Facility and Candidate booking paths create shifts and bookings atomically.
5. Candidate ranking uses completed work at the Facility/client, recency, and location signals.
6. Candidate and Facility directories have text search; calendar data is month-bounded.
7. Legacy matching/reference sync is permissioned, confirmed, audited, overlap-locked, dry-run capable, and source-read-only.

## What the screenshots show

| Screen | What works | Main effectiveness gap | Recommended response |
|---|---|---|---|
| Booking Board | Clear navigation, summary cards, status labels, prominent Add Vacancy action, and simple shift cards | Summary is passive; it does not identify urgent, aging, offered, cancelled, or failed-sync work | Turn the landing page into an action queue with urgency and saved filters |
| Add Vacancy | Facility-first flow, role-scoped rates, multiple shift rows, notes, and review before create | Repeated start/end entry is slow for weekly rosters and visually grows into a long form | Add recurrence, copy/paste, templates, duplicate detection, and a compact preview |
| Facility Calendar | Familiar monthly layout, Facility selector, status colour, and shift click-through | A month grid becomes sparse or crowded and hides operational exceptions | Add week/list views, status/role filters, overflow counts, and an unresolved-coverage side panel |
| Candidate Directory | Simple search, compliance status, role/location context, direct Book Shifts action | A large card list does not support fast slicing by role, province, Facility history, availability, or compliance risk | Add server-side facets, saved views, compact/table mode, and richer matching signals |
| Candidate Book Shifts | Good empty-state fallback from compatible open shifts to creating new shifts | Repeated dates remain manual; selected rows do not show an aggregate risk/summary view | Add repeat rules, batch summary, per-row validation, and pre-submit conflict preview |

The screenshots are a UX baseline, not a reliable current data-count source. The current import deliberately limits active legacy Candidates and clients to the rolling qualifying-activity scope while preserving older linked history as inactive.

## External market signals

Locumly's current public product and FAQ pages emphasize verified professionals,
applications and direct booking, availability, recurring schedules, emergency listings,
chat, invoicing, and reviews.[1][2] Find Your Locum and LocumFinDR emphasize
verified profiles, location/rate/availability-based decisions, open offer/application
flows, direct booking, attendance or cancellation/replacement support, and payment or
invoice visibility.[3][4] Bullhorn's current healthcare offering similarly emphasizes
instant matching of available credentialed providers, centralized credential
visibility, expiring-credential management, shift-list plus calendar coverage,
provider self-service, time capture, and accurate pay/invoicing.[5]

These sources are vendor descriptions, not independent proof that every feature works as claimed. They are still useful evidence of user expectations. IMMploy should copy the workflow principles—not build a public marketplace or payment platform unless the business actually needs one.

## Prioritized roadmap

### Phase 0 — Release safety and measurement

Complete these before broad operational rollout:

1. **Narrow scheduling permissions and deploy the completed commercial split.** Candidate-pay visibility, Client-charge/profitability visibility and approved-rate override authority are now independent local backend permissions; serializers, Admin, workbooks and React fail closed when fields are absent. Review and deploy migration `0037`, assign least-privilege groups, then continue splitting broad legacy `link_conf` authority into schedule view, Vacancy create, confirm, cancel/replace and sync permissions.
2. **Fix configurable backend proxying.** Vite currently proxies to port 8000 even when the launcher receives another backend port.
3. **Make deployment trust explicit.** Use a trusted certificate and stable hostname/address for LAN use; continue binding Django itself to loopback behind the frontend proxy.
4. **Add a booking event ledger.** Record actor, timestamp, prior state, new state, reason, source system, correlation ID, and safe metadata for every lifecycle transition.
5. **Instrument outcome metrics before optimizing.** Capture a two-week baseline before setting numerical targets.
6. **Deploy a minimal immutable release.** Exclude `.git`, tests, reports, local reconciliation artifacts, Hermes files and frontend TypeScript source from `/opt/immploy/current`.
7. **Canary the balanced web topology.** Verify both Gunicorn instances, Nginx syntax/failover, shared session/MFA behavior, non-replayed mutations, PostgreSQL connection budget and rollback before retiring the legacy listener.
8. **Add application readiness and monitoring.** Keep Nginx liveness separate from Django/PostgreSQL readiness and alert on backend availability, p95 latency, errors, DB connections, sync lag, backup age and disk usage.
9. **Approve and populate the organisational hierarchy.** The local normalized structure follows `Region → Desk → Client → Facility → Ward/department → Candidate membership`; seed only the nine Regions automatically and review every lower-level mapping before import.

Local evidence now includes 10 synthetic end-to-end Booking/Timesheet/Invoice cases plus 10-row payroll and Pastel exports. See [`local-finance-end-to-end-validation-2026-09-01.md`](local-finance-end-to-end-validation-2026-09-01.md). Treat this as functional validation only; production legal configuration, authorization, reconciliation and controlled external upload remain release gates.

Required dashboard metrics:

- median vacancy-to-first-confirmed-booking time;
- open-shift age and count by urgency bucket;
- fill rate by Facility, role, consultant, and lead time;
- candidate search-to-confirmation time;
- cancellation, decline, and replacement time;
- no-show and late-cancellation rate;
- compliance-expiry blocks;
- duplicate/conflict rejection count;
- legacy import lag, unresolved identity count, drift count, and outbound projection outcome;
- manual touches per confirmed booking.

### Phase 1 — Consultant operations and shift-entry speed

1. **Action-driven home page**
   - Today/tomorrow unfilled shifts.
   - Aging open shifts.
   - Offers awaiting response and nearing expiry.
   - Cancellations requiring replacement.
   - Compliance expiries affecting future bookings.
   - Legacy sync conflicts or stale data.

2. **Real filters and saved views**
   - Status, date range, Facility/client, role, province/town, consultant/desk, booking origin, and sync status.
   - Server-side filtering and pagination rather than loading a large directory and filtering only in the browser.
   - Shareable/deep-linkable filter state and saved consultant defaults.

3. **Fast repeated-shift creation**
   - Repeat on selected weekdays between dates.
   - Copy previous day/week/vacancy.
   - Paste rows from a spreadsheet.
   - Shift templates such as day/night/weekend.
   - Default end to start +7 hours, while supporting overnight shifts correctly and preserving user editability.
   - Preview every generated row, duplicate, invalid interval, and rate before atomic creation.
   - “All or nothing” remains the default; explicitly offer a reviewed partial-success mode only if operations asks for it.

4. **Keyboard and accessibility pass**
   - Full keyboard flow through search, filters, dialogs, row selection, and confirmation.
   - Persist clear focus and error summaries.
   - Ensure controls meet WCAG 2.2 target sizing/spacing expectations; WCAG 2.2 defines a 24×24 CSS pixel minimum unless a listed exception applies.[11]

### Phase 2 — Matching and booking lifecycle

1. **Decision-ready candidate results**
   - Keep hard eligibility server-side.
   - Show why each Candidate is ranked: worked here, completed count, last worked date, town/province match, availability, compliance, and any warning.
   - Separate “eligible now” from “search full directory”; never visually blur ineligible and eligible records.
   - Add shortlist, compare, and contact actions without weakening final booking validation.

2. **Availability and preferences**
   - Candidate availability/unavailability intervals.
   - Preferred areas, travel radius, roles, day/night preferences, and minimum acceptable rate where appropriate.
   - Availability improves ranking but does not replace overlap/compliance checks.

3. **Explicit offer state machine**
   - `draft/open → offered → accepted_pending_confirmation → confirmed`.
   - Add `declined`, `expired`, `cancelled`, `conflicted`, and `replacement_required` terminal/exception states where appropriate.
   - Offers must have expiry and must not silently become confirmed.
   - If an offer temporarily reserves capacity, the hold and expiry must be transactional and visible.

4. **Cancellation and replacement workflow**
   - Never delete operational history.
   - Record who cancelled, reason, timestamp, notice period, and replacement requirement.
   - Reopen the shift only through a controlled state transition.
   - Preserve the cancelled booking and link the replacement booking.
   - Provide one-click “Find replacement” using the same authoritative matcher.

5. **Notifications**
   - Email/SMS/WhatsApp adapters behind an outbox, with templates and delivery audit.
   - Confirmation, reminder, change, cancellation, replacement, and expiry messages.
   - Retries must reuse the same notification idempotency key to avoid duplicate messages.

Locumly publicly describes applications plus direct bookings, direct chat, recurring schedules, emergency listings, and a booking lifecycle; LocumFinDR describes verified profiles, direct booking, an offers board, cancellation review, rating impact, and replacement assistance.[1][2][4] These patterns support the lifecycle above, while IMMploy should keep its agency-specific permission and audit model.

### Phase 3 — Compliance, attendance, finance, and self-service

1. Store individual credentials/documents, issuer/reference, issue and expiry dates, verification status, and audit history—not only one aggregate compliance flag.
2. Alert before credential expiry and identify future confirmed bookings at risk.
3. Add check-in/attendance and approved actual time only after the booking lifecycle is stable.
4. Feed approved time to invoicing/payroll through a separate idempotent integration—not by changing booking records silently.
5. Consider a mobile Candidate portal for availability, offers, documents, and confirmations only after the internal consultant workflow and sync are reliable.

### Phase 4 — Nice-to-have experience and insight

These items are deliberately below safety, UAT, monitoring and lifecycle work:

1. Consultant dashboard personalization, pinned Facilities and favourite booking patterns.
2. Candidate shortlist/compare workspace with clear server-derived eligibility explanations.
3. Printable daily Facility roster and shift-handover view.
4. Authorized calendar export (`.ics`) without exposing Candidate or commercial details beyond purpose.
5. Controlled CSV Shift import with preview, duplicate detection and atomic rollback.
6. In-app notification centre with read/acknowledged state and durable delivery audit.
7. Compact/comfortable density, dark mode and keyboard command palette.
8. PWA installation with offline **read-only** last-synced schedules; never queue offline booking writes.
9. Anonymized fill-time, cancellation and consultant-workload trend charts.
10. Permissioned Admin audit export and service-status dashboard for web instances, sync, SMS and backups.

### Capacity and availability evolution

1. **Now:** two loopback Gunicorn instances behind Nginx on one AlmaLinux host; four total request threads; PostgreSQL-backed sessions/throttles; no sticky sessions.
2. **Measure:** authenticated p50/p95/error rate, CPU/RAM, DB connections, lock waits, payload sizes and restart/failover behavior under representative concurrency.
3. **Tune one variable:** only then adjust workers/threads, directory pagination or query shape. Do not apply generic worker or PostgreSQL formulas.
4. **Pool only with evidence:** add PgBouncer only if measured connection demand or churn warrants it.
5. **High availability later:** multi-host web balancing requires agreed RTO/RPO plus shared private storage/object storage, centralized logs, database HA, deployment orchestration, health checks, DNS/TLS and off-host backup/restore evidence.

### Organisational hierarchy and policy rollout

Detailed design: [`organisation-database-hierarchy.md`](organisation-database-hierarchy.md).

1. **Foundation implemented locally:** `Region`, `RegionalDesk`, `RegionalClient`, `RegionalFacility`, `Ward` and `CandidateWardMembership`, with Django Admin and migration `0036`.
2. **Preserve identity:** reuse existing Department, Client, Site and Candidate records; allow legitimate many-to-many regional/Ward membership rather than duplicating records.
3. **Review mappings:** derive proposed Region/Desk/Client mappings from legacy evidence but quarantine ambiguity for business review. Do not infer Candidate eligibility from historical work alone.
4. **Rate/SLA phase:** add effective-dated approved Region/Client rate cards, Profession/pay category, signed-reference metadata, payroll-platform mapping, immutable Booking snapshots and separate commercial permissions.
5. **Compliance phase:** configure effective-dated criteria at approved hierarchy levels with Profession applicability, hard-block/warn semantics, expiry, controlled exceptions and deterministic precedence.
6. **Pilot:** populate a bounded Radiology branch first and reconcile zero hierarchy mismatches/orphans before wider rollout.

## Safe synchronization back to the legacy system

### Current status on 17 August 2026

- The implemented admin synchronization imports only matching/reference data and aggregated completed-work history.
- Legacy MySQL access for that synchronization is read-only.
- Booking records are not imported or exported by that control.
- The old system remains authoritative for bookings.
- The current field map contains anticipated booking mappings; exact legacy booking identity, status, update/version, cancellation, and capacity semantics are not yet verified enough for writes.

This is the correct safe state.

### Target ownership model

During dual running, each booking has one owner:

- `LEGACY`: created in the old system and mirrored read-only into IMMploy.
- `IMMploy_PENDING_LEGACY`: accepted locally but not yet committed by the legacy authority.
- `IMMploy_CONFIRMED_LEGACY`: created through the approved legacy reservation operation and verified by read-back.
- `CONFLICTED`: rejected or changed concurrently and awaiting human resolution.

Do not display a local booking as fully confirmed while its authoritative legacy creation is pending.

### Required integration records

1. **BookingExternalLink**
   - local booking ID;
   - source/owner system;
   - immutable legacy booking ID;
   - immutable IMMploy correlation UUID;
   - last imported legacy version/hash;
   - unique constraints on both external identifiers.

2. **BookingOutbox**
   - correlation UUID and operation;
   - immutable payload or canonical payload hash;
   - expected legacy version for update/cancel;
   - status, attempt count, next retry, lease/claim fields;
   - safe last outcome and timestamps.

3. **LegacyBookingInbox/Projection**
   - legacy ID and canonical payload/hash;
   - observed version or source timestamp where trustworthy;
   - import/reconciliation status;
   - unresolved identity and conflict reason.

4. **BookingEvent**
   - append-only lifecycle/audit entry linked to the local booking and integration operation.

Microsoft's transactional outbox guidance explains the key invariant: write the business object and its event in the same database transaction, then let a separate worker publish/process pending outbox entries, preventing a committed business change from losing its integration event.[6]

### Stage A — Verify the legacy write contract

Before any booking write, confirm from the real legacy schema and VB.NET/ASMX code:

- immutable booking primary key;
- exact candidate, Facility/client, role, start/end, rate, and status fields;
- cancellation/tombstone behavior;
- whether `updated_at`, row version, or another monotonic change marker exists;
- whether one vacancy item equals one bookable capacity unit;
- where overlap and capacity are enforced today;
- transaction boundaries and storage engine;
- timezone interpretation;
- whether a correlation UUID and unique index can be added;
- whether a dedicated stored procedure/service endpoint can be introduced;
- least-privilege grants needed for that operation only.

If these cannot be established, outbound writes stay disabled.

### Stage B — Shadow-import bookings read-only

1. Poll legacy booking changes using a reliable high-water mark where available; otherwise use overlapping windows plus canonical hashes and periodic full reconciliation.
2. Upsert by immutable legacy booking ID, never by Candidate/date/name heuristics.
3. Map Candidate, Facility, and role through verified legacy IDs.
4. Quarantine unresolved or ambiguous identities; do not guess.
5. Preserve legacy ownership and source payload/hash.
6. Import explicit cancellations/status changes; absence from a query is not cancellation.
7. Compare actual start/end intervals for overlap detection.
8. Keep local-only bookings separate and visible.

Run this in shadow mode until reconciliation demonstrates stable identity mapping, status interpretation, timezone handling, and acceptable lag.

### Stage C — Reconciliation and operational control

Add a permissioned sync console showing:

- last successful import and lag;
- counts read, inserted, updated, unchanged, conflicted, and quarantined;
- missing/ambiguous identity mappings;
- local-versus-legacy booking discrepancies;
- stale queued/running work and worker heartbeat;
- per-item safe audit trail;
- retry, quarantine, and dry-run controls with confirmation.

The current reference sync's run-level audit is a useful start, but booking integration needs item-level reconciliation.

### Stage D — Build one atomic legacy reservation operation

The legacy-side operation must perform, in one MySQL transaction:

1. lock a stable Candidate scheduling mutex row (or ordered Candidate-day reservation rows) so that the “no existing overlapping row” case is also serialized;
2. lock the specific vacancy/placement capacity row;
3. check the unique correlation UUID;
4. if the UUID already exists, return the existing result without another insert;
5. recheck Candidate interval overlap against authoritative legacy records;
6. recheck capacity, status, and eligibility fields that legacy owns;
7. create the booking and correlation record;
8. commit and return the immutable legacy booking ID and version/hash.

A locking query over existing bookings alone is insufficient when no overlapping row exists: concurrent transactions can both observe “none.” The design therefore needs a stable mutex/reservation row or an equivalent proven serialization mechanism. MySQL documents that an ordinary `SELECT` is not enough when related data will be changed in the same transaction and provides locking reads such as `SELECT ... FOR UPDATE`.[8]

Conceptual contract:

```text
reserve_booking(correlation_uuid, candidate_legacy_id, vacancy_item_id,
                starts_at, ends_at, expected_payload_hash)

BEGIN
  lock stable candidate scheduling row(s) in deterministic order
  lock vacancy/capacity row
  if correlation_uuid exists:
      return previous outcome
  if authoritative overlap or no capacity:
      record/return conflict
  insert booking
  insert unique correlation mapping
COMMIT
read back booking and return immutable id + version/hash
```

The integration account should receive only the minimum permission needed to execute this operation and read back/reconcile the result—not unrestricted table write access.

### Stage E — Transactional local outbox

When IMMploy accepts a booking intent:

1. lock and validate local Shift/Candidate state;
2. create/update the local booking as `IMMploy_PENDING_LEGACY`;
3. create the immutable outbox row with the same correlation UUID;
4. append the BookingEvent;
5. commit all three in one PostgreSQL transaction.

A database-backed worker then claims outbox rows. PostgreSQL supports `FOR UPDATE ... SKIP LOCKED`, which is suitable for multiple consumers claiming queue-like work without processing the same row concurrently.[9]

### Stage F — Idempotent delivery and unknown outcomes

- Every retry reuses the original correlation UUID.
- A timeout after sending is an **unknown outcome**, not permission to insert again.
- Reconcile by correlation UUID first; if found, verify and confirm locally.
- Only retry the same idempotent operation when reconciliation cannot yet determine an outcome.
- Use bounded exponential backoff with jitter and a dead-letter/conflict queue.
- Never generate idempotency from a payload hash alone; two intentionally identical shifts can be valid. AWS recommends a unique caller-provided request identifier and requires recording that identifier atomically with the mutating work.[7]

### Stage G — Updates and cancellations

1. Require the last-read legacy version/hash on every update or cancellation.
2. Legacy applies the change only if the expected version still matches.
3. A mismatch becomes `CONFLICTED`; re-import before human resolution.
4. Cancellation is an explicit operation and tombstone/status, never delete-and-reinsert.
5. A replacement receives a new correlation UUID and links to the cancelled booking.
6. Rates and times must not be silently overwritten by last-write-wins timestamps.

If legacy has no trustworthy version, add a controlled integration-side version/correlation record or keep updates/cancellations manual until one exists.

### Stage H — Rollout and cutover

1. **Shadow:** read-only import, no outbound writes.
2. **Reconcile:** resolve all identity/status/timezone mappings and measure drift.
3. **Canary:** one Facility, role, and trained consultant; low volume; feature flag and kill switch.
4. **Expand gradually:** monitor every operation, lag, conflict, retry, and duplicate-prevention invariant.
5. **Cut over booking authority:** route all booking creation for migrated scope through one authoritative reservation path.
6. **Retire dual entry:** do not leave two unrestricted booking frontends writing independently forever.

AWS's strangler-fig guidance supports incremental migration to reduce disruption and explicitly notes that cross-store synchronization creates eventual consistency and should be tactical rather than the permanent architecture.[10]

## Go/no-go gates for outbound booking writes

Outbound writes remain **NO-GO** until all are true:

- [ ] exact booking schema and lifecycle semantics verified against live legacy code/schema;
- [ ] immutable correlation UUID stored under a unique legacy constraint;
- [ ] atomic legacy check-and-create operation proven under concurrency tests;
- [ ] stable Candidate/capacity locking serializes the zero-row case;
- [ ] local booking plus outbox are one PostgreSQL transaction;
- [ ] database-backed worker has lease/heartbeat, retries, and stale-work recovery;
- [ ] timeout reconciliation returns the previous result without duplicates;
- [ ] update/cancel optimistic concurrency is proven;
- [ ] item-level audit and conflict quarantine are operational;
- [ ] shadow import and reconciliation meet agreed accuracy/lag gates;
- [ ] backup, rollback, feature flag, kill switch, and canary runbook tested;
- [ ] least-privilege legacy write authority approved;
- [ ] independent concurrency/security review approved.

## Failure scenarios that tests must prove

| Scenario | Required result |
|---|---|
| Two IMMploy workers deliver the same outbox item | One legacy booking; both observe the same correlation result |
| Old system books Candidate after local check but before delivery | Legacy atomic operation rejects conflict; IMMploy marks conflicted |
| Response is lost after legacy commit | Retry/reconcile returns existing legacy booking, never inserts again |
| Two different bookings target overlapping times for one Candidate | Stable Candidate lock serializes them; one wins, one conflicts |
| Capacity is consumed concurrently | Capacity lock permits only valid number of bookings |
| Worker crashes after claim | Lease expires; another worker safely resumes with same UUID |
| Mapping is missing or ambiguous | Item is quarantined without write |
| Legacy row changes before update/cancel | Version mismatch; re-import and human resolution |
| Import sees no row because of query/window failure | No cancellation inferred |
| Partial multi-shift delivery | Each shift has its own immutable operation; UI shows exact per-item outcomes |

## Recommended delivery order

1. Release safety fixes and booking event ledger.
2. Metrics plus action-driven queues and filters.
3. Recurrence/templates/paste plus compact preview.
4. Cancellation/replacement and explicit offer lifecycle.
5. Availability/preferences, credential-expiry visibility, and notifications.
6. Read-only legacy booking shadow import and reconciliation console.
7. Legacy atomic reservation endpoint/procedure and concurrency test harness.
8. Transactional outbox worker, canary, then controlled expansion.
9. Cut over booking authority; only then add attendance/payroll/self-service depth.

## Sources

[1] https://locumly.co.za — Locumly South Africa
[2] https://locumly.co.za/faqs — Locumly FAQs
[3] https://findyourlocum.co.za — Find Your Locum
[4] https://www.locumfindr.com/faqs — LocumFinDR FAQs
[5] https://www.bullhorn.com/healthcare — Bullhorn Healthcare Staffing Software
[6] https://learn.microsoft.com/en-us/azure/architecture/databases/guide/transactional-out-box-cosmos — Microsoft Azure Architecture Center: Transactional Outbox
[7] https://aws.amazon.com/builders-library/making-retries-safe-with-idempotent-APIs — AWS Builders Library: Making retries safe with idempotent APIs
[8] https://dev.mysql.com/doc/refman/8.4/en/innodb-locking-reads.html — MySQL 8.4 Reference Manual: InnoDB Locking Reads
[9] https://www.postgresql.org/docs/current/sql-select.html — PostgreSQL Current Documentation: SELECT locking clauses
[10] https://docs.aws.amazon.com/prescriptive-guidance/latest/cloud-design-patterns/strangler-fig.html — AWS Prescriptive Guidance: Strangler fig pattern
[11] https://www.w3.org/WAI/WCAG22/Understanding/target-size-minimum.html — W3C WCAG 2.2: Target Size Minimum
