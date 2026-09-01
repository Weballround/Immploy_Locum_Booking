# Legacy SMS workflow and booking-system target

## Source-verified legacy behavior

The authoritative implementation is the VB.NET application under `Immploy_TACS/TS/Immploy CRM/Immploy CRM`.

- `Class/clsSMS.vb` sends through MyMobileAPI's legacy ASMX web service. It supports single sends, bulk sends, reply polling, and credit lookup. Credentials come from legacy settings rather than the form.
- `Forms/Vacancies/frm_vacancies_booking_confirm.vb` makes SMS optional but selected by default when a Candidate has a mobile number. The message is editable before sending.
- Booking-confirmation templates come from `tbl_notification_custom_messages`. The active substitutions are `[cand_name]`, `[client_name]`, `[lb]`, and `[bookings]`; each booking line contains start and end date/time.
- A successful send is persisted to `tbl_candidate_sms` by `Service.vb:SetNewCandSMS`, including recipient number, Candidate, sender, message, gateway event ID, desk, and timestamp.
- `Forms/SMS/frm_sms_manage.vb` provides bulk recipient selection, saved groups, predefined messages, credit display, duplicate-number suppression, and chunks sends at 900 recipients.
- `Forms/SMS/frm_sms_log.vb` polls replies, correlates them by gateway event ID, and deduplicates by reply ID. `frm_sms_replies.vb` supports a manual reply.
- The main bulk-SMS click handler opens the form without a visible capability check. The modern system must not inherit that access-control gap.
- The legacy configured endpoint uses plain HTTP and account credentials. The current provider supports an HTTPS REST API with separately managed REST keys, delivery webhooks, and test mode. The modern system must not reuse the old transport or embed credentials.

## First bounded modern release

The first release restores booking-confirmation SMS rather than the full marketing/bulk-message manager.

1. An authorised scheduler explicitly queues an SMS for an existing confirmed Booking.
2. The server snapshots Booking, Candidate, recipient, rendered message, requester, and a unique provider customer ID in a durable outbox record.
3. Recipient numbers are normalized to E.164 and invalid/missing numbers fail before an outbox row is created.
4. The operation is Department-scoped and requires the dedicated `bookings.send_booking_sms` permission in addition to Booking access.
5. One confirmation notification is queued per Booking. Duplicate queue attempts are rejected; failed or interrupted sends require explicit review rather than automatic retry with duplicate-send risk.
6. A separate worker command claims queued records and calls MyMobileAPI over HTTPS. Gateway failure never rolls back or corrupts the Booking.
7. Provider credentials are environment-only. Missing/unsafe configuration fails closed and records no fabricated delivery state.
8. The browser can preview/edit the generated text and queue the message, but never receives provider credentials.

## Explicitly deferred

- Bulk campaigns, saved recipient groups, and arbitrary Candidate searches.
- Inbound replies, delivery-receipt webhooks, opt-out processing, and conversation assignment.
- Automatic reminders, cancellations, replacements, and expiry notifications.
- Client-contact email notifications.

Those require separate consent, POPIA/retention, webhook-signature, ownership, rate-limit, and operational designs. A queued or provider-accepted SMS is not described as handset-delivered until signed delivery receipts are implemented.

## Operations and activation

The integration is disabled by default. Deployment installs a one-minute `immploy-sms.timer`, but its service skips cleanly while either REST credential is empty.

1. Obtain a current MyMobileAPI REST client ID and secret. Do not reuse or copy the legacy SOAP password.
2. Add `SMS_MYMOBILEAPI_CLIENT_ID` and `SMS_MYMOBILEAPI_SECRET` to protected `/etc/immploy/immploy.env`; keep ownership `root:immploy` and mode `0640`.
3. Keep `SMS_MYMOBILEAPI_BASE_URL=https://rest.mymobileapi.com` unless the provider documents a different HTTPS REST base URL. HTTP is rejected.
4. Grant Django permission `bookings.send_booking_sms` only to approved schedulers. `manage_bookings` and legacy `link_conf` do not imply SMS authority.
5. Restart `immploy-web@8001.service` and `immploy-web@8002.service` so session capability payloads reflect permission changes, then start or reload `immploy-sms.timer`.
6. Queue and verify one controlled test booking using an authorised test recipient before enabling ordinary use. Provider acceptance is not represented as handset delivery.

No credentials belong in source control, migration files, Admin records, application logs, or this document.

## Current provider references

- MyMobileAPI REST documentation: <https://mymobileapi.readme.io/docs/rest.md>
- API-key authentication: <https://mymobileapi.readme.io/reference/authentication.md>
- v3 bulk-message endpoint: <https://mymobileapi.readme.io/reference/bulkmessages_postv3.md>
