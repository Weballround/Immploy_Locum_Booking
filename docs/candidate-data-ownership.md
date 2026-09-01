# Candidate data ownership and editing

The Candidate editor is a controlled booking-profile workflow. It is not generic CRUD and it does not write to legacy MySQL.

## Field ownership matrix

| Field or data group | Owner | Candidate editor behavior |
| --- | --- | --- |
| Names, booking email/cell and matching location | Local booking profile after an authorized edit | Editable by Candidate managers. The existing Department-scoped directory continues to return these scheduling fields. A qualifying legacy Candidate is marked locally managed so later reference syncs preserve the edit. |
| Home/other contact, physical address and notes | Local booking profile after an authorized edit | Editable only through the restricted Candidate profile endpoint and excluded from bulk directory responses. |
| South African ID, passport and visa fields | Local booking profile after an authorized edit | Available only to Candidate editors. A new or changed South African ID must be 13 digits, contain an unambiguous valid calendar DOB for a Candidate aged 18–100, use an accepted citizenship-status digit and pass the Luhn checksum. Errors never echo the submitted identity value. |
| Date of birth and sex | Legacy source or derived from a validated South African ID | A valid changed South African ID sets DOB, sex and citizenship status server-side. The UI marks DOB and sex as derived. Unchanged malformed historical identifiers do not block unrelated edits. |
| Employment Equity | Candidate self-identification | Server-backed dropdown. It is never inferred from an identity number: the current South African ID format does not encode race. |
| Home language, other languages, countries, nationality, division, consultant, education, source, marital status, driver licence and qualifications | Legacy-authoritative vocabulary; locally selected profile value | Mostly dropdown or multi-select. Django rejects values absent from the active synchronized vocabulary, while an existing historical value remains visible and correctable. Legacy Qualification Types are linked to selected Candidate roles by legacy role ID and incompatible new combinations are rejected. |
| Province/region and suburb/area | Local booking profile after an authorized edit | Linked server-backed dropdowns. The child list resets when the parent changes and Django rejects incompatible pairs. These fields affect matching and ranking. |
| Active/dormant state | Local booking profile within the legacy eligibility boundary | Editable. Deactivating a Candidate preserves Booking and Shift history and removes the Candidate from active matching. A legacy Candidate who falls outside the qualifying source projection is always deactivated regardless of local profile ownership. |
| Candidate roles | Local booking profile after an authorized edit | Multi-select. An active Candidate must retain at least one valid server-known Profession. Role-ID changes are audited. |
| Compliance, fingerprint and criminal-check status | Protected compliance workflow / qualifying legacy source | Visible in the Candidate editor. Fingerprint and criminal-check dropdowns are editable only with compliance authority; crafted requests fail closed. The primary compliance status remains protected. |
| Legacy Candidate ID | Legacy integration | Immutable and never shown as an editable field. A PATCH containing it is rejected. |
| PostgreSQL Candidate ID and profile-ownership marker | Booking system | Server-managed and immutable through the Candidate API. |
| Candidate inclusion and approved department scope | Read-only legacy synchronization | Candidate inclusion uses each Candidate's latest timesheet from `2025-08-01` through the current date. Department visibility remains separately derived from approved-desk activity. Payroll, payslips, documents, leave and reimbursements remain outside this editor. |

## Authorization and validation

- Bulk directory reads remain available to Department-scoped scheduling users. Expanded identity/contact profile reads require Candidate-management authority.
- Creating or updating Candidates requires server-side Candidate-management authorization. A booking-only legacy profile cannot update a Candidate.
- The API supports `PATCH` but not Candidate deletion or unrestricted `PUT`.
- Active Candidates require at least one valid Profession.
- Compliance fields require compliance authority in both the profile API and Django Admin; material Candidate Admin changes create redacted Candidate audit events. Integration identifiers always fail closed.
- Date, option, multi-select, visa-range and province/suburb validation is repeated in Django; React visibility and disabled state are not security controls.
- Existing Bookings, Shifts, and facility-experience history are not modified when profile fields, roles, or active status change.

## Audit and synchronization behavior

Each successful profile change creates an immutable, read-only `CandidateChangeAudit` row containing the Candidate, staff user, timestamp and changed field names. Matching-sensitive values (area, region, active state and role IDs) record before/after values. Identity, DOB, sex, citizenship, passport, visa, contact, address, demographic and note values are deliberately excluded from audit before/after payloads.

Authorized edits to qualifying legacy Candidates set `profile_locally_managed`. Subsequent read-only reference syncs preserve their locally managed profile and roles while protected compliance values remain legacy-controlled. Lookup vocabularies are synchronized into `CandidateProfileOption`. Malformed historical source dates become blank rather than aborting the full transaction. If a legacy Candidate later falls outside the qualifying source dataset, synchronization deactivates the Candidate and clears email, phone and postal code while retaining historical records. No Candidate update is written to legacy MySQL.
