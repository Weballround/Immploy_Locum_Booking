# Local finance end-to-end validation — 2026-09-01

## Scope

This validation exercised the real local Django Booking and post-shift finance services with synthetic records only. It did not modify the production Booking System, the legacy TS database, payroll, Pastel, the SMS provider, or any external financial system.

Run identifier: `QA-20260901-FIN`

## Verified workflow

Ten independent cases completed this lifecycle:

1. Create a synthetic Vacancy and past seven-hour Shift.
2. Create a compliance-cleared synthetic Candidate with the required Profession and payroll code.
3. Confirm the Candidate Booking through the authoritative Booking model path.
4. Capture a signed synthetic Timesheet document and worked-time line.
5. Mark the Shift completed through Timesheet capture.
6. Approve and stage the Timesheet for payroll.
7. Generate the payroll export from immutable Timesheet rate snapshots.
8. Attach synthetic Client confirmation.
9. Generate one Invoice PDF per Timesheet.
10. Generate one Pastel sales export containing all ten Invoices.

## Read-back result

| Record/artifact | Verified count |
|---|---:|
| Vacancies | 10 |
| Confirmed Bookings | 10 |
| Completed Shifts | 10 |
| Approved, staged, payroll-exported and invoiced Timesheets | 10 |
| Invoices | 10 |
| Non-empty Invoice PDFs | 10 |
| Payroll export batches/files | 1 |
| Pastel sales export batches/files | 1 |

The payroll file contains 10 rows. The Pastel sales file contains 10 rows. The combined synthetic Invoice total is **R26,573.65**.

## Local artifacts

Artifacts are deliberately excluded from Git:

`local-finance-exports/QA-20260901-FIN/`

The folder contains:

- `IMMploy-payroll-QA-20260901-FIN.txt`
- `IMMploy-Pastel-sales-1-2-3-4-5-6-7-8-9-10.csv`
- `invoices/IMT1.pdf` through `invoices/IMT10.pdf`
- `manifest.json`

SHA-256:

- Payroll: `048551785afe042adcdb81cd4dc8d582bab01b6ca1d3c365788108b0857c1308`
- Pastel sales: `c792ae8f50eae8f7fd4150f8dd260865283625fa8ab59980f9bde1cd9add4e46`

## Safety boundary

These files are test evidence only and must never be uploaded to live payroll or Pastel. Production still requires reviewed legal Invoice issuer configuration, least-privilege finance permissions, authorized deployment, backups, reconciliation, operator approval and controlled external-system testing.
