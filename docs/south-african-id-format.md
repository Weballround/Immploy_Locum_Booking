# South African identity-number format

This document records the format used by IMMploy's server-side identity decoder. South African identity numbers are highly sensitive personal data: never copy real values into tests, fixtures, logs, documentation, URLs, audit payloads, or support messages.

## Structure

A South African identity number contains 13 digits in the form `YYMMDD SSSS CAZ`.[1]

| Positions | Symbol | Meaning | IMMploy use |
| --- | --- | --- | --- |
| 1–6 | `YYMMDD` | Encoded date of birth | Derive date of birth after resolving the century and validating the date. |
| 7–10 | `SSSS` | Sequence: `0000–4999` female and `5000–9999` male | Derive sex. |
| 11 | `C` | Status: `0` citizen, `1` permanent resident, `2` refugee | Derive citizenship/status. Government guidance separately confirms that South African IDs are issued to citizens and permanent residents.[2] |
| 12 | `A` | Administrative digit, currently `8` or `9` | Validate only. This digit is not a current race field and must never populate Employment Equity. |
| 13 | `Z` | Luhn check digit | Validate integrity before deriving any fields. |

The historical administrative digit is now random rather than a racial identifier.[1] IMMploy therefore never derives race or Employment Equity from an identity number.

## Automatic population policy

After full server-side validation, IMMploy may automatically populate only:

- **Date of birth** from `YYMMDD`;
- **Sex** from `SSSS`;
- **Citizenship/status** from `C`.

The identity number does not defensibly provide a Candidate's name, contact details, address, language, nationality, country of origin, disability status, Employment Equity, qualifications, profession, Region, or Area. Those fields remain authoritative user selections or synchronized profile data.

## IMMploy validation rules

`backend/bookings/sa_id.py` performs all decoding server-side. It requires:

1. exactly 13 decimal digits;
2. a valid Luhn checksum;
3. a valid calendar date;
4. exactly one plausible century producing a Candidate aged 18–100 inclusive;
5. a valid status digit (`0`, `1`, or `2`);
6. a valid administrative digit (`8` or `9`).

Validation errors never echo the submitted identity value. Frontend decoding is convenience behavior only; backend validation remains authoritative. Tests use generated checksum-valid synthetic values rather than real identity numbers.

## Implementation locations

- Decoder: `backend/bookings/sa_id.py`
- Decoder tests: `backend/bookings/tests/test_sa_id.py`
- Protected decode endpoint: `backend/bookings/views.py`
- Candidate data ownership policy: `docs/candidate-data-ownership.md`

## Sources

[1] https://en.wikipedia.org/wiki/South_African_identity_card — South African identity card
[2] https://www.westerncape.gov.za/service/applying-identity-document — Applying for an Identity Document