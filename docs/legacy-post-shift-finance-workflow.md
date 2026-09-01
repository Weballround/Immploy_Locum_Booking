# Legacy IMMploy post-shift and finance workflow

## Scope and evidence

This document records the active workflow recovered from the legacy VB.NET/ASMX application under `Immploy_TACS/TS`. It describes source-verified behavior; it does not claim that the modern booking system already has these capabilities.

Primary evidence:

- `Forms/Timesheets/frm_timesheet_gen.vb:97-195`
- `Forms/Timesheets/frm_timesheet_approve.vb:115-165`
- `Forms/Timesheets/frm_timesheets_declined.vb:13-111`
- `Forms/Timesheets/frm_timesheet_manage_2.vb:179-198,295-318`
- `Forms/FBS/frm_fbs_gen_payroll.vb:484-728`
- `Forms/Timesheets/frm_timesheet_invoice_2.vb:171-210,339-399`
- `Forms/Timesheets/frm_timesheet_invoice_report.vb:137-149,160-527`
- `Forms/Timesheets/frm_timesheet_invoice_export.vb:56-169,212-327`
- `TS_Data_Layer/App_Code/Service.vb:6797-6818,10127-10208`
- `Forms/Timesheets/frm_timesheets_journal_approve.vb`

The legacy source was inspected read-only. No legacy files or production records were changed.

## End-to-end operational flow

```text
Confirmed booking / vacancy shift
    ↓ work is performed
Eligible completed shift selection
    ↓
Capture worked dates, hours/minutes, lunch and rate categories
    + attach the source timesheet document
    + use supplied timesheet number or generated internal number
    ↓
Create timesheet header + item rows
    + snapshot candidate and client rates
    + mark linked vacancy items complete
    + optionally mark the parent vacancy complete
    + write Candidate interaction/timesheet log
    ↓
Approval queue
    ├─ Decline with mandatory reason
    │    ↓
    │  correction queue → view/re-upload replacement document
    │    → return to approval, or mark unusable
    └─ Approve
         ↓
Approved timesheet staging
    ├─ Client requires confirmation?
    │    └─ attach confirmation/motivation before invoicing
    ├─ Stage as ready for payroll export
    └─ verify Candidate payroll code and Client payroll/job code
         ↓
Payroll batch generation
    + deduct lunch
    + apply candidate rate snapshot
    + apply leave-accrual deduction where applicable
    + distinguish normal pay, leave and reimbursements
    + produce payroll import text, unique employee list,
      control report, pay-point SQL and gross-pay documents
    + mark timesheets `fbs_payroll`
         ↓
Invoice selection (only approved and payroll-exported items)
    + one Client per invoice
    + edit invoice description/hours/rate if authorised
    + apply Pastel account/append code
    + calculate ex-VAT, VAT and inclusive totals
    + allocate IMT invoice number
    + generate DOCX and PDF
    + save invoice header, line snapshots and document locations
    + mark timesheet items invoiced in one DB transaction
         ↓
Pastel sales export
    + produce delimited sales-import file
    + produce a separate credit-note file when applicable
    + use March–February accounting periods
    + mark invoice/credit-note records processed to prevent re-export
         ↓
History, corrections, journals and reconciliation reports
```

## Detailed states and controls

### 1. Shift completion and timesheet capture

The capture screen accepts a physical/electronic source document by drag-and-drop. It refuses to continue without a linked document and a timesheet number (unless the number is auto-generated). The file is renamed, stored under a date folder, and linked to the timesheet.

Each selected worked shift becomes a timesheet item containing date, hours, minutes, pay rate, rate type, client rate, lunch minutes and capturing consultant. Rate categories include normal/day, Saturday, Sunday, overtime, standby, night, public holiday and standby variants.

After the timesheet header and items are created, linked vacancy items are set to complete. The parent vacancy can be marked complete when all of its items are complete. This is a separate operational transition, not merely a calculated label.

### 2. Document storage and version/correction behavior

The legacy system stores the database reference and the document itself in separate boundaries. Users can view the linked document and replace it. A declined-timesheet queue supports replacement upload and resubmission; it can also mark a sheet unusable. The legacy replacement path deletes the old file, so the modern replacement must improve this by retaining immutable document versions and an audit trail.

Supported source documents are operational files such as PDF and scanned images. The modern system should validate extension, content type and file size; use generated server filenames; keep storage private; and serve downloads only after permission and Department checks.

### 3. Approval and correction

Approval and decline are explicit privileged actions. Approval records a timestamp and writes both Candidate-interaction and timesheet logs. Decline requires a note, moves the sheet into a correction queue, and writes a correction log. A corrected document returns the sheet to the approval queue.

Approval must lock the current timesheet and verify that it is submitted, has at least one valid line, and has a current document. An approver should not approve their own capture unless a separately authorised override is introduced and audited.

### 4. Client confirmation / motivation

Some Clients have `requires_conf`. Their approved timesheets cannot enter the invoicing branch until a confirmation or motivation document is linked. This requirement is distinct from internal timesheet approval and must remain a separate state.

### 5. Payroll staging and export

Approved timesheets are first marked ready for payroll. Missing Candidate payroll codes make rows non-selectable. Client/job payroll codes are also part of the legacy preparation path.

The FBS payroll run then:

- calculates payable time as hours plus minutes minus lunch;
- uses the captured pay-rate snapshot;
- applies leave-accrual deductions only to normal vacancy work;
- treats annual/sick/family-responsibility leave and travel/other reimbursements separately;
- aggregates normal earnings to payroll transaction code `4100`;
- creates the payroll import text plus unique employee, control report and pay-point support files;
- generates Candidate gross-pay documents; and
- marks timesheets as payroll-exported and records the process/week code.

A modern export must be immutable, hashable, attributable, idempotent and downloadable again. “Generated” and “uploaded/imported by payroll” are different states; successful external upload must be confirmed separately rather than inferred from download.

### 6. Invoice generation

The active invoice report supports one Client per invoice. It resolves the Client Pastel code and optional role append code, allows authorised line editing, calculates VAT, allocates an `IMT` invoice number, generates DOCX/PDF documents and saves line-level original/invoiced snapshots.

The database finalisation uses a transaction for invoice linkage, invoice-item snapshots and timesheet-item invoice status. File creation happens before final database finalisation, so the modern design must quarantine or clean up failed files and never expose a half-generated invoice as final.

The legacy ordering makes invoice candidates depend on `fbs_payroll IS NOT NULL`. The modern workflow preserves this as the default control while modelling payroll and invoicing as separate branches, so the rule can later be changed deliberately rather than hidden in a query.

### 7. Pastel export and credit notes

Pastel export selects generated invoices not previously processed. It writes a sales-import text file containing accounting period, date, transaction type, Customer/Pastel code, invoice reference, description, total, tax type, VAT component, contra account and control fields. The accounting year uses periods March = 1 through February = 12.

Credit notes are generated to a separate file and have independent processed status. Export timestamps prevent ordinary duplicate exports. The modern system must never mark an invoice exported until the exact downloadable artifact has been generated and persisted successfully.

### 8. Journals, history and reconciliation

The legacy system also has:

- timesheet journal creation and a separate journal-approval queue;
- invoice history and invoice correction/credit-note paths;
- invalid client-rate reporting;
- payroll and gross-salary reports;
- sales/profit reporting; and
- Candidate interaction and timesheet correction logs.

These are part of the operational control environment even though they are not all in the straight-through happy path.

## Items missing from the original requested list

The original sequence was broadly correct, but it omitted:

1. marking the shift and possibly the parent vacancy complete;
2. captured worked-time detail, lunch deductions and rate categories;
3. supplied/internal timesheet-number handling;
4. declined-timesheet reason, correction, replacement upload, resubmission and unusable state;
5. internal approval versus Client confirmation/motivation as separate gates;
6. Candidate payroll and Client job/account code validation;
7. payroll staging before final payroll export;
8. leave accrual, leave payments and reimbursements;
9. gross-pay documents and payroll control/reconciliation outputs;
10. VAT, one-Client-per-invoice grouping and role/account append codes;
11. invoice line snapshots and invoice document retention;
12. Pastel credit-note export;
13. explicit generated/downloaded/upload-confirmed states for external files;
14. journals, invoice history and corrections;
15. role-based permissions, Department scoping and audit logs; and
16. retry/idempotency controls to prevent duplicate payroll or accounting exports.

## Modern-system implementation boundary

The modern system owns this workflow only for bookings created in the modern system.
Legacy timesheets, invoices and payroll records remain legacy-authoritative and are
not written or synchronised in either direction.

The implemented bounded release provides:

- one timesheet per confirmed booking after the shift ends;
- automatic shift completion after successful capture;
- actual start/end and break capture with immutable pay/bill snapshots;
- private, versioned timesheet and Client-confirmation documents;
- PDF/JPG/JPEG/PNG signature, extension and size validation;
- submitted/declined/approved transitions with actor, reason and timestamp events;
- declined duplicate/unusable timesheet voiding with a mandatory retained audit reason;
- ordinary-user segregation between capture and approval;
- corrected document upload and resubmission without deleting prior evidence;
- Client-specific confirmation/motivation gating;
- Candidate payroll-code and Client Pastel-code prerequisites;
- immutable payroll and Pastel export batches with SHA-256 hashes;
- a distinct, audited ready-for-payroll stage before payroll batch generation;
- one-Client invoice headers, line snapshots, VAT totals and retained PDF documents;
- multi-page A4 invoice PDFs carrying snapshotted profession and rate-band descriptions;
- fail-closed tax-invoice generation until an authorised Admin configures the issuer
  legal name, VAT number and address, and the Client has a billing address;
- immutable invoice snapshots of issuer and Client billing/VAT details so later Admin
  edits cannot rewrite historical documents;
- March-to-February Pastel period mapping;
- duplicate-export prevention and explicit external-upload confirmation;
- row-locked, single-use external-upload confirmation with actor and timestamp;
- cleanup of private source, replacement, confirmation and invoice files when the
  matching database transaction fails;
- PostgreSQL and private-document backups with matching retention; and
- Department-scoped **Django Admin only** operations mapped to legacy access rights.

Export generation, listing, download and upload confirmation are not exposed in the
React booking frontend. Django Admin hides unavailable actions and filters payroll
versus Pastel artifacts so only specifically authorised users can access them.

## Comparative review update — 26 August 2026

The following gaps were found by re-tracing the active VB.NET forms into
`Service.vb`, then reading the corresponding modern models, services, Admin views,
templates and tests. Items labelled **corrected** are represented in the current
working tree; they are not production claims until the migrations and exact tree are
deployed and read back.

| Risk | Legacy evidence/need | Modern review result |
|---|---|---|
| Blocking access control | Desk/Department ownership limits operational records | **Corrected:** timesheet line, document and event Admin querysets now inherit the parent Timesheet Department scope. Explicit child-model view permission no longer reveals another Department's metadata. |
| Blocking payroll control | Approval and `payroll` readiness precede final `fbs_payroll` generation | **Corrected:** approved sheets require an audited, locked ready-for-payroll transition before CSV generation. |
| Blocking transaction safety | Files and linked records must remain reconcilable | **Corrected:** private files are removed when their DB insert or a later enclosing transaction fails. |
| Blocking document accuracy | Invoice reports contain role/rate context and may exceed one page | **Corrected:** retained PDFs include snapshotted profession/rate descriptions and paginate validly. |
| Important lifecycle | Duplicate/unusable records are retained but removed from active processing | **Corrected:** only declined sheets can be voided, with approval authority and an immutable reason event. |
| Important accounting integrity | Approval validates worked-time/rate entries | **Corrected:** approval locks and revalidates every line, including positive net worked time. |
| Important operational integrity | External imports must not be confirmed twice or raced | **Corrected:** confirmation locks each batch, permits only `generated → upload_confirmed`, and records the actor/time once. |
| **Release blocker for non-normal shifts** | Legacy supports Day, Saturday, Sunday, Overtime, Standby, Night, Public Holiday, Standby Holiday, Standby Sunday and Standby Week with separate pay/client rates | **Partially corrected:** all ten categories are representable (`0032`), but the modern rate card still has only one pay/bill pair and capture still creates one Normal line. Do not process multi-band/non-normal finance until an effective-dated rate-band matrix and authorised multi-line capture/review workflow are implemented and migrated. |
| Vendor-contract blocker | Pastel and payroll accept exact site-specific import layouts and mappings | Generated files remain code-verified only. Controlled non-production sample imports against the actual vendor profiles are mandatory before live upload. |
| Configuration blocker | Legal issuer, VAT, Client account/billing and Candidate payroll identifiers are authoritative | Generation fails closed, but production values still require protected business-owner confirmation; no values may be inferred from legacy display text. |
| Recovery blocker | Database and private documents form one recoverable financial record | Backup inclusion exists, but a full PostgreSQL + private-media restore drill and encrypted off-server backup validation remain outstanding. |
| Important correction control | Legacy invoice preparation can adjust descriptions/hours/rates before final processing | Modern invoice lines are generated from approved timesheet snapshots with no separately authorised invoice-adjustment event. Add a reasoned, permissioned adjustment/reversal design rather than unrestricted Admin editing. |
| Important reconciliation | Legacy provides payroll journals, processed markers and operational reports | Modern immutable batches and confirmation timestamps exist, but exception/reconciliation reports and payroll-journal approval remain follow-on work. |

### Release boundary

The corrected single-band path is suitable for further controlled verification only:
one completed booking, one validated worked-time line, one snapshotted pay/bill pair,
approval, payroll staging, payroll export, invoice, Pastel export and explicit external
upload confirmation. Non-normal or split-rate work remains fail-operationally-closed by
release procedure until the normalized rate-band work is complete; the current schema
cannot safely infer those rates.

## Deliberate follow-on scope

The following verified legacy capabilities are documented but are not represented as
complete modern-system functionality in this bounded release:

- leave and reimbursement capture/export;
- credit-note creation and Pastel credit export;
- payroll-journal approval and finalisation;
- commission documents and broader gross-salary reporting;
- direct API upload into Pastel or the payroll product (an authorised Admin operator
  downloads the generated file, uploads it externally, and confirms that upload); and
- invoice-email delivery and external rejection/reconciliation imports.

These require separately verified vendor file contracts, account mappings, reversal
rules and reconciliation behavior. They must not be implemented by guessing from
legacy screen names or by reusing the sales/payroll formats for unrelated entries.
