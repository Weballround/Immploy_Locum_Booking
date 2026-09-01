# IMMploy organisational database hierarchy

**Source:** scanned A3 hierarchy supplied on 31 August 2026
**Duplicate uploads:** `0640_001.pdf` and `0640_001-2.pdf` are byte-for-byte identical
**Implementation status:** structural Django models and Admin are local, uncommitted and undeployed

## Approved hierarchy transcribed from the diagram

```text
IMMploy hierarchy
└── Region
    └── Desk
        └── Client
            └── Facility
                └── Ward / department
                    └── Candidate membership
```

Regions shown in the scan:

- WC — Western Cape
- NC — Northern Cape
- NW — North West
- FS — Free State
- GAU — Gauteng
- EC — Eastern Cape
- KZN — KwaZulu-Natal
- MPUM — Mpumalanga
- LIMPOPO — Limpopo

The Desk branch is marked “replicate across all the regions.” The handwritten examples map to the existing canonical Booking Departments: Nursing, Doctors, Allied, Permanent and Assisted Care. Department identity remains the existing legacy-linked `Department` record; it is not duplicated per province.

Examples written in the hierarchy are:

- Client: Mediclinic
- Facility: George
- Ward/department: ICU
- Candidate: `RN...` as an illustrative Candidate box, not a literal record to create

Handwritten business notes:

1. “Pay and bill rates are loaded per region, per client as per latest signed rates / SLA.”
2. “We need to configure the Compliance criteria on the same structure.”
3. “Pay criteria must also be configured to accommodate the payroll platform.”

## Implemented relational model

The hierarchy is an overlay on existing normalized identities:

| Hierarchy level | Model | Purpose |
|---|---|---|
| Region | `Region` | Stable province/region identity; nine rows seeded |
| Desk in a Region | `RegionalDesk` | Joins one existing `Department` to one Region |
| Client in a Regional Desk | `RegionalClient` | Joins one existing `Client` to one Regional Desk |
| Facility in that branch | `RegionalFacility` | Joins one existing `Site` to one Regional Client |
| Ward/department | `Ward` | Named operational unit beneath a Regional Facility |
| Candidate membership | `CandidateWardMembership` | Many-to-many Candidate association without duplicating Candidate identity |

This design deliberately does **not** add a generic free-form tree. Explicit foreign keys preserve the approved level order and make authorization, rates, compliance and reporting easier to validate.

## Integrity rules

- A Desk may appear once per Region.
- A Client may appear once per Regional Desk.
- A Facility may appear once per Regional Client.
- A Ward name may appear once per Regional Facility.
- A Candidate may appear once per Ward, but the same Candidate may legitimately belong to several Wards/Facilities/Regions.
- A `RegionalFacility` rejects a `Site` whose existing Client differs from the hierarchy’s Client.
- Ordinary saves and bulk/import paths enforce that same Client invariant; direct queryset scope rewrites are rejected and must use validated `save()`.
- Existing Candidate, Client, Site and Department identities are reused and are not copied.
- `PROTECT` is used for hierarchy parents where deletion would damage the approved structure.
- Active flags permit controlled retirement without deleting historical structure.

## Django Admin workflow

Secured Admin models are provided for:

1. Regions
2. Regional Desks
3. Regional Clients
4. Regional Facilities
5. Wards/departments
6. Candidate Ward memberships

Admin list filters and search support Region and Desk navigation. Changes use Django’s model permissions; access must be assigned only to approved administrators. Ordinary booking users do not receive hierarchy-maintenance authority by implication.

## Migration behavior

Migration `0036_region_regionaldesk_regionalclient_regionalfacility_and_more.py`:

- creates the six structural models and uniqueness constraints;
- adds Candidate-to-Ward membership through an explicit join model;
- seeds only the nine approved Regions;
- does not guess or bulk-assign existing Desks, Clients, Facilities, Wards or Candidates;
- does not alter existing Bookings, rates, Department scope or Candidate compliance.

## Rate/SLA design still required

Do not add region/client rates as unversioned decimal fields. The next rate phase should introduce an effective-dated, approved agreement/rate-card model with at least:

- Region and Client scope as required by the scan;
- Desk and Profession/pay category where the signed SLA differentiates them;
- effective start/end dates;
- signed SLA/reference and approval state;
- pay and bill values with currency and rate unit;
- payroll-platform mapping code;
- immutable booking snapshots;
- maker/checker approval and append-only audit;
- explicit, deterministic precedence for any Facility/Ward override;
- separate permissions for pay, client charge/profitability and override authority.

No browser field may become authoritative for pay or bill rates.

## Compliance design still required

Compliance must be configurable against the same hierarchy without changing a Candidate’s global identity. The next compliance phase should define:

- criterion/document type;
- scope at Region, Regional Desk, Regional Client, Regional Facility or Ward;
- Profession applicability;
- mandatory versus warning behavior;
- issue/verification/expiry requirements;
- effective dates and controlled exceptions;
- precedence when several hierarchy levels apply;
- audit history and future-Booking impact;
- server-side eligibility enforcement.

A Ward membership must not itself mean “compliant” or “eligible.” Final Booking validation must resolve all applicable active criteria server-side.

## Safe population plan

1. Approve canonical Region codes and payroll mappings.
2. Create the five active Desk branches under each applicable Region; do not assume every Desk is operational everywhere.
3. Generate a read-only proposed Client/Region/Desk mapping from legacy evidence.
4. Quarantine ambiguous or multi-region Client mappings for business review.
5. Link existing Sites to reviewed Regional Clients.
6. Import Ward/department reference data only from an authoritative source or reviewed Admin workbook.
7. Add Candidate memberships from approved evidence; do not infer permanent eligibility solely from historical work.
8. Reconcile counts and zero-orphan integrity without printing Candidate identities.
9. Pilot with Radiology and a bounded Facility set.
10. Enable hierarchy-based rates/compliance only after effective-date, precedence and rollback tests pass.

## Release gates

- [ ] Business owner confirms the nine Region codes and five Desk labels.
- [ ] Client versus Facility meanings are confirmed for legacy data.
- [ ] Ward/department source ownership is approved.
- [ ] Model/Admin permissions are assigned to a dedicated group.
- [ ] Proposed mappings are reviewed before import.
- [ ] Zero Facility/Client hierarchy mismatches.
- [ ] Multi-region and multi-Desk Clients are represented without duplicate Client records.
- [ ] Candidate membership does not broaden Department visibility or Booking authority.
- [ ] Rate/SLA precedence and payroll mapping are signed off.
- [ ] Compliance precedence, hard blocks, warnings and exceptions are signed off.
- [ ] Full tests, migration rehearsal, backup and rollback pass.
- [ ] Production deployment is separately authorized and verified.
