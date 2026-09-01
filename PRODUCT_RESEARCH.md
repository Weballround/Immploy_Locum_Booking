# Locum Product Research and Feature Priorities

## Sources recovered from the open Chrome session

Hermes could not capture the native Chrome window, so the current Chrome session files were inspected directly. They contained locum-product tabs for Find Your Locum, Locumly, LocumFindr, SA Locums, Click-a-Shift, The Locum App, Locate a Locum, Locum Organiser, Clarity Locums, My Locum Manager, Workflare and LocumBooking.

Public product pages were then reviewed for Locumly, Find Your Locum, Locate a Locum, Locum Organiser and LocumBooking. Clarity Locums was protected by a Cloudflare verification page, and the saved Click-a-Shift page now returns 404.

## Strong patterns across the products

### 1. Two-sided, mobile-first marketplace

Locumly and Find Your Locum separate the locum and practice journeys. Locums discover suitable shifts and practices post or manage them. Both make mobile access a central part of the proposition.

**Recommendation:** build distinct consultant, client and locum experiences on the same booking engine. The operational React board comes first, followed by a mobile-friendly locum portal rather than a native app immediately.

### 2. Compliance is part of matching, not an afterthought

Locumly prominently markets HPCSA verification. Locate a Locum markets a fully compliant pool, and LocumBooking highlights registration and background checks.

**Recommendation:** every candidate match should show a compliance decision with reasons. Expired or missing mandatory documents must prevent confirmation unless an authorised person records an override and reason.

### 3. Availability and clash-free matching

LocumBooking makes availability an explicit setup step, while Find Your Locum markets smart matching. The practical value is not merely search: it is a ranked shortlist that excludes unavailable and already-booked candidates.

**Recommendation:** support recurring availability, leave, travel radius, preferred clients/areas and booking-clash detection. The MVP already excludes confirmed clashes and candidates without the required profession or cleared compliance.

### 4. Fast offer, application and confirmation loops

Locumly advertises instant applications and practice-side application management. LocumBooking summarises the workflow as book, confirm and track. Locate a Locum emphasises simple communication around shifts.

**Recommendation:** add offer/application states, expiry times and bulk offers. A consultant should see who was contacted, opened the offer, accepted, declined or did not respond, with one-click final confirmation.

### 5. In-product messaging and notifications

Locumly calls out instant doctor chat; Find Your Locum includes messaging; Locate a Locum uses a mobile app to communicate around shifts.

**Recommendation:** centralise email, SMS and WhatsApp notifications around booking events. Keep a delivery log and template version for each message. Add in-product chat only after the booking-event notification flow is reliable.

### 6. Rota visibility and repeated scheduling

Locate a Locum highlights branch-wide rota visibility and planning months ahead. Locum Organiser focuses on fast session entry, a diary available on any device and calendar synchronisation. LocumBooking advertises real-time rota visibility.

**Recommendation:** week/month calendar views, multi-shift creation, repeating patterns, copied weeks, overnight shifts and branch/client filters are high priority.

### 7. Payments, timesheets and invoices from booking data

Locate a Locum combines attraction, management and payment and promotes payment accuracy. Locum Organiser generates invoices from diary data, tracks paid/unpaid invoices, hours and expenses.

**Recommendation:** preserve immutable booked rates, then generate timesheet, pay and invoice lines from those rates. Add approval and dispute workflows before automating payroll.

### 8. Trust signals and service quality

Locumly exposes ratings and verified status. Marketplace products use reviews, completed-shift counts and visible verification to reduce uncertainty.

**Recommendation:** after the first booking release, add private internal ratings and structured incident/reliability notes. Public star ratings should wait until moderation, appeals and data-protection rules are designed.

## Prioritised roadmap

### MVP — operational booking core

1. Client/site/profession/candidate/shift/booking model
2. List and calendar booking board
3. Repeating and multi-shift creation
4. Compliance and profession gates
5. Availability and overlap checks
6. Candidate shortlist with match reasons
7. Offer, accept/decline and confirm lifecycle
8. Audit trail and role-based permissions
9. Email/SMS/WhatsApp notifications and delivery history

### Next — self-service and operations

1. Locum mobile web portal
2. Practice request portal
3. Document upload and expiry reminders
4. Timesheet submission and client approval
5. Cancellation/replacement workflow
6. Rate cards, overtime/weekend rules and margin view
7. Calendar sync and reminders

### Later differentiators

1. Explainable candidate ranking using work history, preferences and distance
2. Forecasting likely unfilled shifts
3. Auto-release offers in controlled waves
4. Secure payments and automated reconciliation
5. Telehealth/virtual consults only if it becomes a separate strategic product line

## Design conclusion

The best opportunity is not another generic shift marketplace. IMMploy already has operational knowledge, client relationships, rates, compliance data and downstream timesheet/invoice workflows. The stronger product is an agency-grade booking operating system with fast matching, reliable compliance gates, complete communication history and a simple self-service experience for locums and clients.
