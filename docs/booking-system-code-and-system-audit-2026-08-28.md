# IMMploy Booking System code and system audit

**Audit date:** 28 August 2026; organisational-hierarchy addendum 31 August 2026
**Repository:** `/Users/pierreb/Work/Immploy_Locum_Booking`
**Reviewed base:** local `main` at `852f17e98f6719e1d46588e1445215b15500ef5a` plus the current mixed, uncommitted working tree
**Production status:** this audit does not claim the current local tree is deployed; production SSH and live Nginx/systemd verification remain unavailable.

## Executive assessment

The Booking System has a strong server-authoritative scheduling core and a credible single-host production design. Booking confirmation revalidates Candidate activity, compliance, profession, Shift state/capacity, Department scope and time conflicts under PostgreSQL transactions and row locks. Rates, permissions, MFA assurance and finance transitions are primarily backend-owned.

The system is **not encoded**. The React production bundle is minified with source maps disabled, while Django remains ordinary Python source protected by filesystem permissions. This is the correct baseline: browser code cannot be secret, and root administrators can inspect a running service regardless of obfuscation.

Commercial-rate authorization is now split locally into independent Candidate-pay visibility, Client-charge/profitability visibility and approved-rate override permissions. API serializers omit unauthorized fields, Admin and workbook surfaces enforce the same separation, and browser-provided overrides fail closed. Migration `0037` and these controls remain undeployed. The highest-priority remaining risks are authorization granularity for other booking actions, deployment of a minimal reviewed release artifact, production observability/capacity evidence, and verification that the local hardening is actually installed on `10.0.0.99`. SMS sending and outbound legacy booking writes remain **NO-GO**.

A safe local load-balancing topology has been prepared: Nginx uses `least_conn` across two independently managed loopback Gunicorn instances on ports 8001 and 8002. Total concurrency remains four threads, matching the prior service, until production CPU, memory, PostgreSQL and latency measurements justify a change. This removes one Gunicorn process-manager failure boundary but does not remove the single-host, Nginx or PostgreSQL failure boundaries.

## Scope and evidence

Reviewed:

- Django settings, permissions, models, serializers, API views, Admin and session/MFA paths;
- React application, tests, Vite production configuration and generated bundle;
- Nginx, Gunicorn/systemd, installer, synchronization, SMS and backup units;
- source-protection configuration and repository hygiene;
- `PERFORMANCE_BASELINE.md`, booking effectiveness roadmap and legacy safety documents;
- current automated test/build/deployment checks.

Not verified:

- live production ownership/modes, listeners, SELinux, firewalld or service state;
- live Nginx syntax and upstream failover on AlmaLinux;
- production CPU/RAM/database connections or concurrent-user capacity;
- GitHub visibility through the currently unavailable authenticated CLI;
- independent exact-tree review of the current mixed working tree;
- disaster recovery from an off-host production backup.

## Architecture reviewed

```text
Staff browser
    |
    | HTTPS
    v
Nginx on booking.immploy.com
    |-- built React files
    |-- collected Django static files
    `-- /api and /admin
           |
           | least_conn, loopback only
           +--> Gunicorn instance 8001 (1 worker x 2 threads)
           `--> Gunicorn instance 8002 (1 worker x 2 threads)
                    |
                    +--> PostgreSQL (runtime authority and Django sessions)
                    +--> protected private-media storage
                    +--> read-only legacy MySQL synchronization
                    `--> durable SMS/finance workers (activation separately governed)
```

## Organisational hierarchy addendum

The supplied scanned hierarchy has been implemented locally as a normalized overlay:

`Region → Regional Desk → Regional Client → Regional Facility → Ward/department → Candidate membership`

It reuses existing `Department`, `Client`, `Site` and `Candidate` identities rather than duplicating records. Migration `0036` seeds the nine approved Regions only; it deliberately does not guess mappings for current data. A cross-client integrity check prevents a Facility from being attached beneath the wrong Client branch, and Candidate membership remains many-to-many.

Detailed contract and rollout gates: [`organisation-database-hierarchy.md`](organisation-database-hierarchy.md).

The hierarchy is structural only at this stage. Existing Booking authorization, rates and compliance behavior are unchanged. Rate/SLA and compliance criteria must be added later as effective-dated, audited rules referencing hierarchy nodes; Ward membership must never be treated automatically as compliance or Booking eligibility.

## Verified strengths

### Scheduling integrity

- `Booking.save()` uses transactions and deterministic row locking around Candidate and Shift state.
- One confirmed booking per Shift has a conditional database uniqueness constraint.
- Candidate active state, compliance, profession compatibility, Shift openness and interval overlap are rechecked on confirmation.
- Configurable minimum rest is backend-enforced.
- Facility/Candidate-origin booking workflows use outer transactions so partial Vacancy/Shift/Booking writes roll back.
- Bulk booking is bounded and transaction-wrapped.
- Department scope is checked on reads and custom-action writes.

Evidence: `backend/bookings/models.py`, `serializers.py`, `views.py`, `department_scope.py`, `permissions.py` and their tests.

### Authentication and data protection

- Production fails closed without stable Django and MFA keys.
- Secure session/CSRF cookies, HSTS and proxy trust controls are configured outside debug mode.
- MFA secrets are encrypted; replay and challenge expiry controls are tested.
- Trusted-browser assurance is server-issued, revocable and restricted to configured trusted LAN/proxy provenance.
- Login throttling is PostgreSQL-backed, so balanced web instances share one authoritative throttle state.
- Sensitive documents are not exposed through public `/media/` routes.

### Source and secret protection

- Vite explicitly disables source maps.
- The production bundle contains no TypeScript/Python source and no `.map` files.
- Nginx rejects hidden files and source/source-map extensions under public roots.
- Runtime secrets are intended to remain in protected `/etc/immploy` files.
- Systemd runs Django as the unprivileged `immploy` account with filesystem/kernel hardening.
- No unignored credential/key file was found during the local scan.

### Performance foundation

- Local measured operational endpoints are fast on the documented development dataset.
- Vacancy child insertion has a constant query bound through validated bulk creation.
- Candidate shortlist query shape was measured and improved rather than tuned speculatively.
- Current sessions and login throttling are database-backed and compatible with multiple web processes.

## Findings and recommendations

| Priority | Finding | Evidence/impact | Required action |
|---|---|---|---|
| P0 | Commercial-rate permission split is local and undeployed | Separate pay-view, Client-charge/profitability-view and approved-rate-override permissions now redact API/Admin/UI surfaces independently; migration `0037` is local only | Review the exact tree, assign least-privilege groups, migrate through a controlled release and verify production responses |
| P0 | Current protection/load-balancing changes are local and uncommitted | Production state cannot be inferred from this working tree | Review, commit, deploy through an immutable release and verify live state |
| P0 | Outbound legacy booking writes are not safe | Atomic legacy reservation/idempotency/read-back contract is not proven | Keep disabled until every documented go/no-go gate passes |
| P0 | SMS is not production-ready | Provider parsing, credentials, cancellation suppression, stale processing recovery and delivery operations remain unresolved | Keep the SMS timer disabled for real sending until controlled pilot approval |
| P1 | Scheduling permission is too broad | Legacy `link_conf` still covers several distinct capabilities | Split schedule view, Vacancy create, confirm, cancel/replace, rate override and sync permissions |
| P1 | Production release contents are not minimal/proven | `/opt/immploy/current` can contain more than runtime-required code | Build an explicit release manifest excluding `.git`, tests, reports, local artifacts and frontend source |
| P1 | Local reconciliation/Hermes artifacts are not all ignored | A broad `git add -A` can stage local operational files | Expand `.gitignore` and stage only reviewed paths |
| P1 | `/healthz` proves only Nginx is alive | It does not verify Django or PostgreSQL readiness | Add separate liveness and authenticated/internal readiness checks; monitor both backends |
| P1 | Load balancing remains single-host | Host, Nginx, PostgreSQL and private-media storage remain single points of failure | Treat current topology as process resilience; design multi-host HA only after RTO/RPO approval |
| P1 | No production capacity baseline | Local data and latency are not production concurrency evidence | Capture p50/p95, errors, CPU/RAM, DB connections, locks and payload sizes under representative load |
| P2 | Candidate directory growth can become expensive | Current full-directory payload measured at 367 records; future growth is unbounded | Add server pagination/search before several thousand active Candidates |
| P2 | Booking lifecycle audit is incomplete | Strong state validation exists, but a unified append-only event ledger is still planned | Add actor/reason/source/correlation events for create, confirm, cancel, replace and reconciliation |
| P2 | Current two-instance topology has no connection pool | Four threads are modest; adding pooling without evidence adds failure modes | Measure PostgreSQL connections first; add PgBouncer only when justified |

## Load-balancing design

### Implemented locally

- Nginx upstream `immploy_app` with `least_conn`.
- Loopback backends `127.0.0.1:8001` and `127.0.0.1:8002`.
- One Gunicorn worker and two threads per instance.
- Passive failure handling (`max_fails=3`, `fail_timeout=10s`).
- Keepalive connections between Nginx and Gunicorn.
- Independently restartable `immploy-web@.service` instances.
- Worker recycling with bounded jitter to reduce long-lived process degradation.
- Installer starts both new instances, validates/reloads Nginx, then retires the legacy port-8000 service.

### Mutation safety

Nginx does not enable retries for non-idempotent requests. Booking `POST`, `PATCH` and `DELETE` operations must never be replayed automatically after an ambiguous upstream failure. Safe read requests may fail over; mutations return their failure and rely on application idempotency/reconciliation where explicitly implemented.

### Deployment gates

Before production activation:

- [ ] inspect CPU, RAM, disk, PostgreSQL `max_connections`, current sessions and ports;
- [ ] run `systemd-analyze verify` on the template unit;
- [ ] run `nginx -t`;
- [ ] start both instances and verify separate process IDs/listeners;
- [ ] verify login/MFA/session continuity while alternating requests;
- [ ] verify safe GET failover by stopping one instance;
- [ ] verify a booking mutation is not replayed when one backend fails ambiguously;
- [ ] run representative authenticated load and compare p50/p95/error rate to baseline;
- [ ] restart one instance at a time and verify uninterrupted reads;
- [ ] verify database connection count remains within the approved budget;
- [ ] verify logs identify upstream/instance and preserve correlation IDs;
- [ ] retain and test rollback to the former listener until the canary passes.

### Scaling policy

Do not increase workers by the generic `(2 x CPU) + 1` formula. Increase one dimension at a time only after measuring saturation. Multi-host balancing requires a separate design for shared private media, TLS/DNS, centralized logs, database availability, deployment coordination and health checks.

## Prioritized product plan

### Release blockers and operational essentials

1. Commercial-rate permission separation and API redaction.
2. Fine-grained booking capabilities.
3. Booking event ledger and cancellation/replacement state machine.
4. Production monitoring, readiness checks, alerting and backup restore drill.
5. UAT and Radiology canary gates.
6. SMS and outbound legacy writes remain independently gated NO-GO workstreams.

### High-value workflow improvements

1. Action queue for urgent, aging, unfilled and replacement-required Shifts.
2. Saved server-side filters and deep links.
3. Recurrence, copy-week, templates and spreadsheet paste with atomic preview.
4. Candidate availability/preferences and Facility exclusions with audited overrides.
5. Structured compliance credentials and future-booking expiry alerts.
6. Offer/accept/decline/expire workflow with durable notifications.
7. Week/list Calendar modes and compact Candidate table mode.
8. Finance lifecycle visibility from Timesheet through payroll and Invoice.

### Nice-to-have features

These are valuable only after safety, observability and UAT gates:

- consultant dashboard personalization and pinned Facilities;
- Candidate compare/shortlist workspace;
- configurable Shift templates and favourite booking patterns;
- printable daily Facility roster and handover view;
- calendar export (`.ics`) for authorized recipients;
- controlled bulk CSV import with preview and rollback;
- in-app notification centre with read/acknowledged state;
- user-selectable compact/comfortable density and dark mode;
- PWA installation and offline read-only last-synced schedule, with no offline writes;
- anonymized operational analytics and fill-time trend charts;
- audit export available only to a dedicated Admin permission;
- keyboard command palette for high-frequency consultant actions;
- optional Candidate self-service portal after identity, consent and privacy design;
- service-status page for sync, SMS, backups and web instances without exposing secrets.

## Verification evidence

Final local verification on 31 August 2026:

- backend: **244 tests passed**;
- frontend: **57 tests passed**;
- frontend lint and production build passed;
- Django production deployment check passed with generated review-only keys;
- Django migration drift check reported no changes;
- local migration `0036` applied successfully, with nine Regions and zero guessed lower-level hierarchy mappings;
- all **7 hierarchy regressions** passed, including ordinary save, bulk insert and direct-update integrity paths;
- source-map/source-file bundle scan passed;
- all **8 deployment regressions** passed after the load-balancing RED/GREEN cycle;
- shell syntax, Python compilation and `git diff --check` passed;
- credential-like added lines were limited to four identified test-fixture password placeholders, with no unclassified value;
- Docker CLI exists but its daemon was not running, so disposable Linux `nginx -t` and `systemd-analyze verify` could not execute; those remain production/canary gates.

On 1 September 2026, a local synthetic end-to-end finance run additionally created and read back 10 Vacancies, confirmed Bookings, completed Shifts, approved/staged/exported Timesheets, Invoice PDFs and Pastel rows. The payroll and accounting files were hash-verified and retained only under the ignored local export directory. See [`local-finance-end-to-end-validation-2026-09-01.md`](local-finance-end-to-end-validation-2026-09-01.md). This is local functional evidence, not production external-system approval.

## Decision

Proceed with the two-instance single-host topology as a measured canary, not as a claim of high availability. Prioritize commercial-rate authorization and minimal immutable deployment packaging over code obfuscation. Do not scale worker counts, add PgBouncer, or design multi-host HA until production workload, recovery objectives and failure-domain requirements are measured and approved.
