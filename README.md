# IMMploy Locum Booking

A web-first locum shift and booking MVP built alongside the existing TS desktop system.

## Stack

- Django + Django REST Framework
- PostgreSQL 16
- React + TypeScript + Vite
- pytest / pytest-django and Vitest / Testing Library

## Implemented first slice

- Clients, sites, professions, candidates, parent vacancies, shifts and bookings
- Compliance status on candidates
- Open/booked/completed/cancelled shift states
- Candidate matching by profession and cleared compliance
- Explainable ranking by prior work at the same legacy facility and coarse location match
- Read-only MySQL synchronization for active locums, job roles, facilities and aggregated completed-work history
- Candidate matching excludes only confirmed time clashes
- Atomic multi-shift vacancy creation API and responsive **Add vacancy** form
- Facility **Book now** beside **Calendar**, with the Facility locked, a Facility-linked role, an editable Start/End interval whose End initially defaults to Start +7 hours (including date rollover), and one atomic Vacancy → Shift → confirmed Booking operation
- Searchable facility selection and facility-linked role filtering synchronized from `tbl_job_functions_client_vals`; Candidate pay and Client charge fields are independently omitted unless the authenticated user has the corresponding backend permission
- Approved rate overrides require a separate backend permission; ordinary vacancy creation resolves approved rates server-side, and a permitted one-off Shift override does not rewrite the Facility rate card
- Facility **Book now** accepts no pay or bill fields, resolves both values from secured Site/Client profession configuration, and never updates rate defaults; missing configuration fails before any Vacancy, Shift, or Booking persists
- Book-now Candidate discovery is active-, compliance-, profession-, and interval-scoped, then ranked by prior Facility experience, same town, same province, and other matches; final Booking validation remains authoritative
- **Add candidate** creates a candidate record with pending compliance; authorized Candidate editors use linked **General** and **General 2** sections for profile, contact, identity/visa, matching, demographic self-identification, qualification and language fields. Constrained values come from synchronized server vocabularies, Region/Area is dependent, and fingerprint/criminal fields require compliance authority. A new or changed valid South African ID derives DOB, sex and citizenship status after calendar/century/citizenship/Luhn validation; Employment Equity is always self-identified and never inferred from an ID. **Add to booking** confirms an existing eligible candidate from the authoritative shortlist.
- When the eligible shortlist is empty or omits a known candidate, booking users can search active candidates in the selected Shift/Vacancy profession and attempt **Add to booking**; unrelated professions are never returned, results are marked as not prevalidated, and the backend still rejects inactive, noncompliant, profession-incompatible, conflicting, or otherwise ineligible assignments
- Per-Facility monthly calendar with stable Facility-ID and month-overlap API scoping, Johannesburg timezone handling, overnight-shift times, Facility switching, month navigation, visible shift status, keyboard grid navigation, and direct access to booking actions
- Atomic multiple booking from either direction: a cleared Candidate can be assigned to several compatible non-conflicting open Shifts, or a Facility calendar can assign profession-filtered eligible Candidates across several open Shifts; any invalid assignment rolls back the complete batch
- When a Candidate has no compatible open Shifts, **Book shifts** can create new work from the same dialog: select a Facility and one of that Candidate's configured Facility roles, add one or multiple Start/End rows, and submit one atomic Vacancy → Shifts → confirmed Bookings transaction. Pay and bill rates remain server-authoritative, 1–100 Shifts are accepted, and any ineligible or conflicting assignment rolls back the whole operation.
- Candidate overlap protection for confirmed bookings
- Row locking and a database constraint prevent two confirmed locums on one shift
- Booking cancellation/deletion safely reopens the shift
- Invalid shift intervals and negative rates are rejected
- Staff-only, session-authenticated API with CSRF protection
- Responsive booking board with functional booking, candidate, facility and coverage navigation
- Candidate finder drawer and one-click confirmation
- Local candidate creation with pending-compliance safety defaults
- Privacy-limited confirmed-candidate details for viewing already filled bookings
- Django admin screens
- Evidence-led local performance baseline in `PERFORMANCE_BASELINE.md`
- Local demo-data command

The product and process findings behind the vacancy workflow are documented in
[`BOOKING_FLOW_RESEARCH.md`](BOOKING_FLOW_RESEARCH.md).

## Local setup

PostgreSQL is installed as a Homebrew service. The local development database is `immploy_locum` and uses the local macOS user through the PostgreSQL Unix socket.

```bash
cd /Users/pierreb/Work/Immploy_Locum_Booking
brew services start postgresql@16

cd backend
export DJANGO_DEBUG=true
../.venv/bin/python manage.py migrate
../.venv/bin/python manage.py seed_demo
../.venv/bin/python manage.py createsuperuser
../.venv/bin/python manage.py runserver
```

In a second terminal:

```bash
cd /Users/pierreb/Work/Immploy_Locum_Booking/frontend
npm install
npm run dev
```

Open <http://127.0.0.1:5173>. The booking board now has an integrated staff sign-in form. API access remains restricted to active staff users.

### Access from the local network

For temporary internal testing, start both services from the repository root with:

```bash
./start_booking.py
```

The launcher auto-detects the private LAN IPv4 address. Use `./start_booking.py --lan-ip 10.0.1.15` to select it explicitly. It requires the matching ignored `.lan-certs/<IP>-cert.pem` and owner-only private key, keeps Django loopback-only, exposes Vite HTTPS on the LAN, configures exact Django hosts/CSRF origins, and verifies `127.0.0.1`, `localhost`, the LAN IP, and the proxied session API before reporting readiness. Press Ctrl+C once to stop both servers cleanly. If either port is occupied, a prerequisite is missing, the certificate SANs do not cover all promised addresses, or any health check fails, the launcher exits without claiming the system is ready.

Every tester device must trust only the public certificate before entering credentials; never distribute `.lan-certs/<IP>-key.pem`. Do not use plain non-loopback HTTP for staff credentials, passwords, sessions, candidate data, or MFA codes. This launcher is for temporary trusted-LAN testing only; use production-grade serving and certificate management for a persistent or externally reachable environment.

Authorized administrators can navigate directly to `/admin/`. Candidate active/compliance status, assigned roles, area and region are editable under **Candidates**; facility city and region are editable under **Clients**. Authorized Candidate editors can also use **Edit candidate** in the Candidate directory; its expanded sensitive profile is loaded only through the restricted profile endpoint rather than bulk directory responses. The ownership, validation, privacy, audit and synchronization boundary is documented in [`docs/candidate-data-ownership.md`](docs/candidate-data-ownership.md). Shift overlap, capacity, eligibility and confirmed-booking integrity remain server-authoritative and are not bypassed by profile changes or admin display settings.

`DEBUG` is false by default. A deployed environment must provide `DJANGO_SECRET_KEY` and should set `DJANGO_ALLOWED_HOSTS`; secure session/CSRF cookies and HSTS are enabled whenever debug mode is off. Set `DJANGO_TRUST_PROXY_HEADERS=true` only behind a trusted reverse proxy that strips client-supplied forwarding headers.

### Production source protection

The production frontend build explicitly disables source maps. Nginx serves only
`frontend/dist` and the collected Django static directory; requests for hidden
files, source maps, Python source/bytecode, and TypeScript source return `404`
even if a bad release accidentally copies one into a public directory. The
installer owns backend source as `root:immploy`, removes access for all other
server users, runs Django as the unprivileged `immploy` account, and keeps
credentials in `/etc/immploy` rather than the repository.

These controls reduce accidental disclosure without relying on fragile code
obfuscation. Browser JavaScript cannot be made secret because the browser must
download it, so credentials and authoritative booking, permission, rate,
compliance, finance, and matching rules remain server-side. A trusted server
administrator with root access can inspect running backend code; restrict and
audit root/SSH access rather than treating encoding as a security boundary.

### Microsoft Authenticator MFA

Staff can open **Sign-in security**, confirm their current password, and select **Set up Microsoft Authenticator**. Scan the displayed QR code in Microsoft Authenticator using **Other account**, then enter the six-digit code to confirm enrollment. MFA remains optional per account during rollout; once enabled, password authentication creates only a five-minute challenge and no authenticated session exists until a valid TOTP code is submitted.

Authenticator secrets are encrypted at rest. Production must provide a stable, separately managed `DJANGO_MFA_ENCRYPTION_KEY`. Rotating the effective key without a migration makes existing authenticator devices unreadable, so key rotation must include a controlled MFA re-enrollment or secret re-encryption procedure.

When `DJANGO_MFA_ENCRYPTION_KEY` is omitted in debug mode, Django creates an ignored `backend/.mfa-dev-key` file with owner-only permissions so local enrollments survive Django secret rotation and server restarts. This development fallback is never used in production.

TOTP values are accepted only once, adjacent time-step tolerance is limited to account for clock drift, and failed setup, confirmation, disable and sign-in attempts use the identity/IP login throttle. Enrollment expires after five minutes; the setup response contains only an uncached QR image and is marked private/no-store/no-referrer. Enabling MFA invalidates the user's other authenticated sessions. Disabling or administratively resetting MFA revokes every existing session, including the current one, so the user must sign in again. Account-level MFA generations also prevent an in-flight challenge from establishing a session after reset. Protected API/admin requests require the current MFA generation and, whenever a device is enabled, device assurance. An MFA-enabled administrator cannot bypass MFA through `/admin/login/`: sign in through the application first and then navigate to `/admin/`.

For administrator-assisted recovery, open the affected account under Django Admin **Users**, select **Delete** on its Microsoft Authenticator enrollment, and save. The affected user then signs in with their password and performs fresh enrollment under **Sign-in security**. Administrators cannot create, view, export, or email a user's MFA secret or QR code, and no email-based MFA recovery flow is used.

## Tests

```bash
cd backend
DJANGO_DEBUG=true ../.venv/bin/pytest

cd ../frontend
npm test
npm run build
```

## Staff-only API

- `GET /api/shifts/` — booking-board shift list
- `GET /api/shifts/{id}/candidates/` — cleared candidates matching the shift profession
- `GET /api/vacancies/site-role-options/?site={id}` — roles linked to a facility, with pay and bill defaults independently omitted unless permitted
- `GET /api/candidates/?profession={id}&site={id}&starts_at={value}&ends_at={value}` — conflict-aware ranked Facility shortlist; Start/End must be supplied together
- `POST /api/vacancies/book-now/` — atomically create one Vacancy, one Shift, and one confirmed Booking from trusted configured rates
- `GET|POST /api/candidates/` — staff directory and pending-compliance candidate creation
- `PATCH /api/candidates/{id}/` — authorized booking-profile update with protected compliance/integration fields and an immutable audit record
- `POST /api/bookings/` — create and confirm a candidate booking

Example booking payload:

```json
{
  "shift": 1,
  "candidate": 1,
  "status": "confirmed"
}
```

Example Facility Book-now payload:

```json
{
  "reference": "Weekend cover",
  "site": 7,
  "profession": 9,
  "candidate": 71,
  "starts_at": "2026-09-12T20:00:00+02:00",
  "ends_at": "2026-09-13T04:00:00+02:00",
  "notes": "Optional operational note"
}
```

The root must be a JSON object. Unknown fields—including `pay_rate`, `bill_rate`,
and `shift_items`—are rejected. Candidate, Facility, profession, compliance,
conflict, capacity, rate, and scheduling permissions are validated server-side.
Any failure rolls back the complete operation. The frontend distinguishes a
failed shortlist request from an empty shortlist and offers Retry without
clearing the selected Facility, role, or interval.

## Existing TS integration

The legacy MySQL database is always opened in a read-only transaction. The Candidate population is the distinct set of legacy `cand_no` values whose latest qualifying timesheet falls between `2025-08-01` and the current date, regardless of legacy Locum or dormant flags; an import still requires a corresponding `tbl_candidates` master record, so orphaned timesheet references are excluded rather than turned into fabricated Candidates. Client inclusion remains limited to non-dormant clients with qualifying activity in the rolling previous 12 months and one of the five active booking departments—Doctors (`1`), Allied (`2`), Nursing (`3`), Assisted Care (`5`) and Radiology (`9`). Future-dated timesheets are excluded. Required live roles, selected-client job-function links and normal pay/bill rates, coarse area/region data and aggregated completed-shift history support that bounded projection. The sync also imports Candidate/Client membership in the five approved desks. Ordinary legacy users are scoped to their active `assigned_desk` across Candidate, Facility, Shift, Vacancy and Booking reads and writes; guessed cross-desk object IDs are denied. Multi-desk Candidates and Clients remain visible to each owning desk. Candidates without an approved-desk membership remain visible only to all-desk administrators. Django superusers, legacy `man_users` administrators and locally permissioned Django administration identities retain all-desk visibility. Unknown, inactive and desk-`0` legacy assignments fail closed. Historical legacy Candidate, client and department rows outside the current source projection are retained inactive rather than deleted. The sync does not write to MySQL or expose residential addresses through the API. Vacancy-form requests use only the synchronized PostgreSQL projection, and Candidates without a synchronized active role remain unbookable until an authorized role is assigned.

Outbound booking projection is intentionally not enabled yet. The verified legacy header/item schema, field-level mapping, missing compatibility fields and recommended PostgreSQL transactional-outbox design are documented in [`docs/integrations/legacy-booking-field-map.md`](docs/integrations/legacy-booking-field-map.md). The exporter must reproduce `tbl_vacancies` and `tbl_vacancy_items` semantics rather than mirroring the new web layout.

Django Administration exposes **Legacy synchronisation runs → Run legacy synchronisation** to users with the dedicated `bookings.run_legacy_sync` permission. The confirmation page supports a source-count **Dry run** and a read-only-source **Synchronise now** import, records an immutable operator-visible run outcome, and prevents overlapping runs. Candidate and Client administration shows department ownership, while the legacy-user list shows each account's assigned desk. Site/client profession rates and site-specific rates remain editable through their existing secured Django Administration screens. This control still writes only the PostgreSQL matching projection; it does not write bookings to legacy MySQL. The required authority, idempotency, conflict-quarantine and duplicate-prevention protocol for that later phase is documented in [`docs/legacy-booking-sync-safety.md`](docs/legacy-booking-sync-safety.md).

The current product/UX research, prioritized effectiveness plan, measurable operating outcomes, and staged booking-sync rollout are documented in [`docs/booking-effectiveness-roadmap.md`](docs/booking-effectiveness-roadmap.md). The next booking-integration stage is read-only shadow import plus reconciliation; outbound writes remain disabled until the atomic legacy reservation and every listed go/no-go gate are proven.

The local synthetic post-shift validation created and read back 10 complete Vacancy → Booking → approved Timesheet → payroll export → Invoice PDF → Pastel sales export cases. Counts, hashes, artifact locations and the production safety boundary are documented in [`docs/local-finance-end-to-end-validation-2026-09-01.md`](docs/local-finance-end-to-end-validation-2026-09-01.md). Generated finance files are ignored by Git and must never be uploaded to live external systems.

Preview the source counts without writing to PostgreSQL:

```bash
DJANGO_DEBUG=true ../.venv/bin/python manage.py sync_legacy_mysql \
  --config /path/to/local/read-only-config.json \
  --dry-run
```

Run the idempotent synchronization:

```bash
DJANGO_DEBUG=true ../.venv/bin/python manage.py sync_legacy_mysql \
  --config /path/to/local/read-only-config.json
```

The local config file contains credentials and must stay outside this repository. Matching remains authoritative in Django/PostgreSQL: candidates must be cleared, have the required role and have no confirmed overlap before imported facility history or location can improve their rank.

### Legacy staff login and access rules

`sync_legacy_users` imports `tbl_users` and `tbl_user_access_presets` into Django/PostgreSQL. The legacy database stores passwords as plain text; the sync reads them only inside the protected import process and immediately converts them to Django password hashes. Plain-text passwords are never stored in PostgreSQL, printed, or written to this repository. Dormant or removed legacy users are disabled and given unusable passwords.

```bash
# Preview counts only
DJANGO_DEBUG=true ../.venv/bin/python manage.py sync_legacy_users \
  --config /path/to/local/read-only-config.json \
  --dry-run

# Import users, securely rehash passwords and copy access rules
DJANGO_DEBUG=true ../.venv/bin/python manage.py sync_legacy_users \
  --config /path/to/local/read-only-config.json
```

Imported users sign in with their existing legacy username and password. Usernames are matched case-insensitively. Individual access flags are authoritative: `link_conf` controls scheduling reads and booking/vacancy/shift mutations, while `edit_cand` controls candidate creation and permits candidate-directory reads. A legacy user with neither rule cannot enumerate the booking or candidate directories.
