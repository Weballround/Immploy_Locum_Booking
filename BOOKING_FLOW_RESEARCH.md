# Fast Vacancy-to-Booking Workflow Research

Research date: 31 July 2026

## Scope and evidence limits

This review used official public product pages and the existing IMMploy/TS source workflow. No vendor account was created and no authenticated competitor workflow was tested. Vendor speed, scale, and performance statements are self-reported claims.

## Public workflow evidence

### Find Your Locum

- **Observed:** candidate flow is profile and HPCSA documents → browse/filter shifts → apply → attendance/communication → payout.
- **Claimed:** matching considers skill, specialty, location, and availability; practices can post and manage shifts quickly.
- **Useful pattern:** compliance and availability are part of matching, while attendance, invoicing, and analytics remain downstream.
- Source: https://findyourlocum.co.za/

### Locumly South Africa

- **Observed:** practice flow is post shift → receive/review verified applicants → select and confirm → work/rate/pay.
- **Claimed:** a practice can create a shift in under 60 seconds.
- **Documented:** candidates may apply for multiple non-conflicting shifts.
- **Observed:** pricing distinguishes shift publication from direct candidate invitations.
- **Useful pattern:** preserve two paths—open applications and targeted invitation/direct booking.
- Sources: https://locumly.co.za/ · https://locumly.co.za/faqs · https://locumly.co.za/pricing

### LocumFinDR

- **Documented:** approved practices can inspect summarized candidate specialization, qualifications, rate, location, and availability, then either directly book a favourite candidate or publish an opportunity for applications.
- **Documented:** profiles are approved using professional council, qualification, and identity checks.
- **Documented:** cancellations are controlled requests and can lead to replacement assistance rather than destructive deletion.
- **Useful pattern:** ranked candidate summaries plus one-click direct booking are the fastest path; offers/applications remain the fallback.
- Sources: https://www.locumfindr.com/faqs · https://www.locumfindr.com/pricing

### Bullhorn Healthcare / staffing ATS pattern

- **Claimed:** open shifts are matched against available, credentialed providers, with calendar and shift-list coverage views.
- **Observed product model:** clients, candidates, jobs, shifts, and placements are separate operational records in one system.
- **Useful pattern:** a `Vacancy` is the commercial staffing request; its generated `Shift` records are independently fillable; candidate progress belongs on the candidate–shift relationship.
- Sources: https://www.bullhorn.com/healthcare/ · https://www.bullhorn.com/products/applicant-tracking-crm/

## Legacy IMMploy/TS process

The existing `frm_vacancies_create.vb` workflow uses this structure:

1. Select the client and job function.
2. Capture vacancy-level information such as primary contact, desk/division, recipient, vacancy type, work level, and assigned consultant.
3. Build one or more dated shift rows with start/end times and rates.
4. Validate that required header fields and at least one time item exist.
5. Create one `tbl_vacancies` parent and multiple `tbl_vacancy_items` children in one operation.
6. Open the resulting vacancy for candidate management.

The strongest part of the legacy process is its parent vacancy plus staged shift rows. Its weakness is the number of required header decisions before a consultant can begin matching.

## Recommended fast process

```text
Add vacancy
  → minimal header: reference, facility/site, role
  → add one or more dated shifts
  → shared candidate pay rate and notes; resolve client charge server-side
  → create vacancy and shifts atomically
  → immediately show generated open shifts
  → find eligible candidates
  → one-click Add to booking
  → revalidate and persist booking atomically
```

### Hard candidate gates

Every direct booking must continue to enforce these rules server-side:

1. Candidate is active.
2. Compliance is cleared.
3. Profession matches.
4. Candidate has no confirmed overlap.
5. Shift is open and unfilled.
6. The user has authoritative booking permission.
7. The database uniqueness rule prevents a concurrent double booking.

### Ranking after eligibility

1. Completed work at the same facility.
2. Coarse location/region match.
3. Future additions: availability, rate fit, reliability, preferences, and distance.

## Implemented first slice

The web application now follows the minimum fast path:

1. **+ Add vacancy** opens a vacancy form.
2. The consultant selects a facility and role once.
3. The consultant can add multiple independent start/end rows.
4. Shared candidate pay rate, reference, and notes are entered once; the client charge rate is resolved server-side from the selected facility and role.
5. `POST /api/vacancies/` creates one PostgreSQL `Vacancy` and all child `Shift` records inside one transaction.
6. Any invalid shift rejects the full vacancy, so partial schedules are not left behind.
7. Generated shifts immediately appear on the booking board.
8. **Add candidate** on an open shift opens the ranked eligible-candidate drawer; this is distinct from creating a new candidate record in the Candidates directory.
9. **Add to booking** creates the authoritative booking and marks that shift booked after server-side eligibility checks.

The existing single-shift API remains available for compatibility, but the main UI now uses the parent vacancy workflow.

## Highest-value next improvements

### 1. Create and match in one action

Add a **Create & find candidates** primary action. After creation, open a split view with generated shifts on the left and ranked candidates on the right. This removes a navigation step.

### 2. Faster shift generation

Add:

- Duplicate row and copy-down.
- Date-range plus weekday recurrence.
- Quantity/number-of-locums generation.
- Paste rows from a spreadsheet.
- Overnight-shift warnings and a generated-shift preview.

### 3. Bulk but safe booking

Allow a consultant to select several generated shifts and book one candidate only for dates where the candidate remains eligible. Return a per-shift result rather than failing an entire series.

### 4. Offer/application lifecycle

Add a candidate–shift workflow:

```text
Suggested → Invited/Applied → Shortlisted → Offered → Confirmed
                           ↘ Declined / Expired / Rejected
```

Direct booking can jump from Suggested to Confirmed, but must use the same server-side validation and audit path.

### 5. Explicit recovery processes

- Candidate cancellation/no-show → preserve history, record reason, mark replacement required, rerun matching.
- Client cancellation → preserve the shift and booking history rather than deleting it.
- Material edits after confirmation → require candidate reconfirmation.
- No eligible candidates → leave the shift open; adjust radius/rate or send wider offers without weakening compliance.

### 6. Vacancy-level state and ownership

Add states such as Draft, Open, Partially filled, Filled, Closed, and Cancelled, plus assigned consultant, client contact, division/desk, and audit history. Keep these out of the first fast-entry form unless facility defaults cannot supply them.

## Design conclusion

The best near-term IMMploy flow is:

**legacy-style vacancy header + bulk shift builder → immediate ranked candidates → shortlist, offer, or atomic one-click booking.**

This preserves the operational strengths of TS while reducing the number of decisions required before a consultant can start filling shifts.
