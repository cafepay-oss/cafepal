# CafePay defect audit

This record covers repairs across the seven CafePay repositories.
The tables describe defects found during the 2026-11-08 repair work.
They record the repair commits and checks from that work.
The commit IDs refer to the original Git history.
The public repository starts from the cleaned code.
See [LOCAL_SETUP.md](LOCAL_SETUP.md) for current setup and test commands.
See [CARD_TRANSFERS.md](CARD_TRANSFERS.md) for the newer receipt upload feature.

## Priority

P1 defects affect authorization, payments, inventory, or operating-system access.
P2 defects break workflows, request handling, or usable layouts.
P3 defects cause avoidable work or minor presentation failures.

## Backend defects

Paths in this table start at `cafepay/`.

| ID | Priority | Category | Confirmed defect | Validation | Status |
| --- | --- | --- | --- | --- | --- |
| B01 | P1 | Authorization | Join and bill reads lack access checks. Kitchen writes also lack access checks. | Anonymous, participant, unrelated, and cross-cafe requests. | Fixed: `ef2b86e` |
| B02 | P1 | Authorization | `TableViews.PBRUpdate` omits object permission checks. | Rejected mutations preserve orders and inventory. | Fixed: `2f9e267` |
| B03 | P1 | Authorization and validation | Payment-method batches accept unrelated orders. A misspelled validator permits invalid and empty batches. | Empty, mixed-cafe, unrelated, and valid batches. | Fixed: `2f82487` |
| B04 | P1 | Authorization | Bulk delivery pricing lacks the single-item endpoint's staff restriction. | Anonymous and cross-cafe writes fail. | Fixed: `6ffae09` |
| B05 | P1 | Payment records | Manual payments validate before locking and accept duplicate payment entries. | Duplicate and concurrent full payments cannot overpay. | Fixed: `4b65d64` |
| B06 | P1 | Checkout integrity | Checkout accepts mixed tables and uses conflicting first-item and last-item configuration. | Mixed joins, cafes, stale bills, transferred bills, and valid split payments. | Fixed: `1cfa37f / d0e3680` |
| B07 | P1 | Inventory integrity | Order writes use stale product instances and omit consistent table/product locks. | Concurrent final-unit orders, first bills, and add/remove requests. | Fixed: `84621b7` |
| B08 | P2 | Validation and runtime | Bulk order input bypasses its serializer. Individual ordering and table separation use incorrect arguments. | Malformed input, pickup times, and individual order/separation flows. | Fixed: `89876f9` |
| B09 | P1 | Authentication | Verification codes never expire and resend throttling uses zero seconds. | Expired, reused, concurrent, and repeatedly requested codes. | Fixed: `2842a15` |
| B10 | P2 | Query cost | Cafe listing sorts in Python and executes 101 queries for 50 cafes before serialization. | Equivalent ordering with bounded database queries. | Fixed: `12e6dad` |
| B11 | P1 | Grouped changes | Mixed order edits use separate add/delete requests and can partially commit. | Atomic mixed edits and safe retries after failures. | Fixed: `89876f9` |

At `e23a719`, all 87 backend tests pass in 16.187 seconds.
The suite uses a disposable PostgreSQL test database.
Gateway and notification tests use mocks.
Tests do not change the restored application database.
The tests do not exercise real gateway settlement.
The test log is `local-data/verify-backend-final-tests.log`.

## Customer application defects

Paths in this section refer to `cafepay-webapp`.

| ID | Priority | Category | Confirmed defect | Validation | Status |
| --- | --- | --- | --- | --- | --- |
| C01 | P1 | Payment display | Partial cashier payments become fully paid units and mutate response totals. | Zero, partial, exact-unit, full, and refunded payments. | Fixed: `1f6d26d` |
| C02 | P1 | Order submission | Concurrent add/delete requests preserve successful changes for accidental replay. | Failed mixed edit followed by retry. | Fixed: `a722716` |
| C03 | P2 | Error handling | Bitwise conditions suppress stock errors. Missing error details cause exceptions. | Even product IDs, HTTP 410, and malformed errors. | Fixed: `a722716` |
| C04 | P2 | Async workflows | Failed payment-method and order requests leave promises unsettled. | Failure and empty-change requests always settle. | Fixed: `a722716` |
| C05 | P2 | Responsive receipt | The success animation displaces payment text and controls below the viewport. | Mobile, tablet, desktop, and short landscape layouts. | Fixed: `920a819` |
| C06 | P2 | Navigation | Payment return loses the table token after a full-page gateway redirect. | Receipt reload followed by return to the same table. | Fixed: `920a819` |
| C07 | P2 | Component lifecycle | Menu listeners survive destruction. Category polling can continue without matching elements. | Repeated mounting produces one submission and no retained timers. | Fixed: `fc3951f` |
| C08 | P2 | Pagination | History pagination assumes the `cafepay.app` hostname. | Localhost, custom hosts, and the final page. | Fixed: `6c556b2` |
| C09 | P2 | Scanner parsing | QR parsing depends on query order and accepts loose hostname matches. | Reordered query parameters and unsupported hosts. | Fixed: `6c556b2` |
| C10 | P2 | Request lifecycle | Network errors call a missing translation method. Concurrent requests clear loading too early. | Network rejection and concurrent request completion. | Fixed: `d4727fc` |
| C11 | P2 | Wallet accuracy | Wallet history contains fabricated transactions and its charge button does nothing. | Real wallet data and local mock charging. | Fixed: `1aafc6c` |
| C12 | P2 | Responsive controls | Fixed navigation and payment controls exceed the centered application width. | Shared control alignment at several widths. | Fixed: `ae94eda` |
| C13 | P2 | Socket handling | Malformed messages and missing source fields crash socket handlers. | Invalid JSON, error envelopes, and unrelated messages. | Fixed: `d4727fc` |

## Administration and waiter defects

| ID | Priority | Category | Confirmed defect | Validation | Status |
| --- | --- | --- | --- | --- | --- |
| A01 | P1 | Payment ordering | Administration closes bills before asynchronous payment finishes. Two close flows contain this race. | Deferred and rejected payments never close bills early. | Fixed: `6bd65b8` |
| A02 | P1 | Order retention | Waiter submission discards edits after failed requests and hides failures. | Failed submissions retain edits for retry. | Fixed: `5f9d708` |
| A03 | P2 | Error handling | Request helpers reference missing router and notification objects on HTTP 401 and 503. | Authentication, server, and network failures. | Fixed: `b238dd7 / b161d9d` |
| A04 | P2 | Cafe selection | Empty memberships and stale saved cafe IDs crash initialization. | Zero cafes and removed cafe membership. | Fixed: `2a2cafe / 5d83c1e` |
| A05 | P2 | Retry control | Failed loaders retry immediately or indefinitely. | Bounded retries with explicit failure states. | Fixed: `b238dd7 / b161d9d` |
| A06 | P2 | Product availability | A rejected waiter update still changes local availability and invokes a missing notification object. | Rejected updates preserve displayed state. | Fixed: `d639729` |
| A07 | P2 | Route state | Waiter table routes depend on transient object parameters and fail after reload. | Direct navigation, reload, and empty menus. | Fixed: `3715644` |
| A08 | P2 | Kitchen controls | Waiter kitchen actions reference undeclared printer data. The print button lacks a handler. | Kitchen updates without printers and explicit print behavior. | Fixed: `e87ec3d` |
| A09 | P2 | Responsive administration | Sidebar and fixed modal offsets clip controls at narrow widths. | 390, 768, 900, and 1280 pixel layouts. | Fixed: `3b0eaec` |
| A10 | P3 | Shared state | Waiter initialization mutates shared navigation data and duplicates store links. | Repeated mounts produce one store link. | Fixed: `5d83c1e` |

## Supporting services and clients

| ID | Priority | Category | Confirmed defect | Validation | Status |
| --- | --- | --- | --- | --- | --- |
| S01 | P1 | Native isolation | Printer windows expose Node.js and Electron remote APIs to remotely supplied content. | Restricted native bridge and blocked unexpected navigation. | Fixed: `e78d5d3 / 1ba0bb9` |
| S02 | P2 | Desktop startup | Printer configuration uses developer-specific absolute icon paths. Autostart toggling reverses checkbox behavior. | Portable paths and correct enable/disable calls. | Fixed: `e78d5d3` |
| S03 | P1 | Push service | Push requests log private keys, lack service authentication, and report success before delivery settles. | Rejected authentication, malformed input, and asynchronous delivery failures. | Fixed: `d18fdb1 / c7f06aa` |
| S04 | P2 | Push model | The dormant VAPID schema references undefined `string` instead of `String`. | Loading the model succeeds. | Fixed: `17c359c` |

## Platform limits

Further review checks database queries, record ownership, payment rules, and grouped database changes.
Database structure changes need tests with restored data and a recovery plan.
The application database stays separate from regression-test databases.

The Flutter checkout contains unfinished authentication, registration, and hardcoded data flows.
The repair environment had no Flutter or Dart toolchain.
Commit `148af22` removes its forced debugging proxy and invalid-certificate acceptance.
No mobile build check occurred during that repair work.
These are explicit mobile implementation gaps, not verified mobile functionality.

The backend uses Python 3.7 and Django 2.2.
The web clients use Node 14-era tooling and Vue 2.
Modernization requires compatibility work beyond individual defect repairs.
The web/backend repair commits retain the working local environment.
The printer client now uses Electron 45.2.3 and Forge 8.
The push service now uses Node 22+, Express 5, Mongoose 9, and Web Push 4.
At that check, `npm audit --omit=dev` reported no production dependency vulnerabilities for either supporting service.
Python/Django and Vue/Nuxt platform migrations remain separate unfinished compatibility work.

Official support and isolation references:

- [Django support versions](https://www.djangoproject.com/download/)
- [Node.js end-of-life versions](https://nodejs.org/en/about/eol)
- [Vue 2 support status](https://v2.vuejs.org/lts/)
- [Electron security guidance](https://www.electronjs.org/docs/latest/tutorial/security/)

## Existing recovery baseline

The previous recovery passed 24 application tests and 14 recovery helper tests.
Browser checks verified local login, products, orders, mock payment, receipts, and WebSocket notifications.
Those checks establish a baseline; they do not cover every defect listed above.
Demo table codes depend on the installation.
Use `./local demo` to print the code for your installation.

## Additional defects found during repair

| ID | Category | Confirmed defect and repair | Status |
| --- | --- | --- | --- |
| B12 | Relation ownership | Table permissions used the wrong method name. Nested catalog relations accepted foreign cafes. | Fixed: `8324a41` |
| B13 | Simultaneous changes | Concurrent cafe reads created duplicate menu tables and tokens. Cafe locks now serialize legacy provisioning. | Fixed: `bd2eaba` |
| B14 | Refund integrity | Refund queries repeated shared invoices and dereferenced missing manual-session invoices. Refund validation lacked locked rechecks. | Fixed: `37cf5bc` |
| B15 | Historical integrity | Imported data contains conflicting ownership and financial records. A read-only command reports affected IDs and review steps. | Reported; preserve records by user instruction |
| B16 | Transferred bill ownership | Transfers and separation hid orders from checkout and refunds. Symmetric bill links also caused recursive cycles. The `current_owner` traversal now handles cycles and rejects foreign or closed destinations. | Fixed: `d0e3680` |
| B17 | Payment concurrency | Payment batches and opposing wallet transfers locked rows in conflicting orders. Concurrent cafe-wallet creation also created duplicates. Consistent row locks now protect these operations. | Fixed: `07b3098` |
| B18 | Price precision | Floating arithmetic returned 28 for a price of 100 with a 71% discount. Integer arithmetic now returns 29. | Fixed: `1882cda` |
| B19 | Cancellation integrity | Repeated cancellations returned stock twice. Concurrent updates lost stock changes. Cancellation also skipped transferred orders. Locked cancellation now returns each canceled order's stock once. | Fixed: `9fd5cb3` |
| B20 | Wallet funding | Wallet funding checks omitted delivery charges. Fake receipts created wallet credit. Partial wallet funding also rejected valid settlement. Funding now covers goods and delivery without fake credit. | Fixed: `f7643f6` |
| B21 | Callback settlement | Callbacks could settle invoices more than once. Boolean provider results also broke callback handling. Invoice locks now serialize settlement. Failed allocation preserves verified wallet credit. | Fixed: `fcf87df` |
| B22 | Gateway consistency | PEP mixed delivery units. Vandar omitted delivery charges. Callback normalization broke HTTPS URLs. Gateway requests lacked timeouts. Shared helpers now enforce exact amounts, valid callbacks, and request timeouts. | Fixed: `e23a719` |
| C14 | Payment selection | Selecting one cashier changed other cashiers at the same array index. | Fixed: `1f6d26d` |
| C15 | Session isolation | Logout retained private state and socket subscriptions. Late responses restored previous user data. | Fixed: `263eb9e` |
| C16 | Refresh integrity | Empty menus referenced missing variables. Socket refreshes erased visible pending edits without clearing their submission. | Fixed: `910269e` |
| C17 | Table restoration | Active preorders restored through the wrong QR token path. | Fixed: `b10995a` |
| C18 | Component lifecycle | Login countdown timers survived destroyed components. | Fixed: `ff9ee55` |
| C19 | Historical payment display | Overpaid rows obscured outstanding debt on other rows. Historical totals now remain intact. | Fixed: `cd0e2ac` / `2c75155` |
| C20 | Camera fallback | Manual table entry required camera initialization. Camera failure now leaves direct entry available. | Fixed: `d59935f` |
| C21 | Catalog ordering | Product deduplication changed category order. Separate lookup data now preserves menu order. | Fixed: `94bb93e` |
| A11 | Catalog integrity | Categories used cafe1. Failed creates removed existing records. Several rollback paths crashed or restored wrong state. | Fixed: `439acb9` |
| A12 | Table state | Polling timers leaked. Nested comparisons and late socket events crashed. Deleted products broke historical invoices. | Fixed: `4acdef6` / `016c6c4` |
| A13 | Print delivery | Printing ran concurrently and acknowledged jobs before delivery. Failed acknowledgements could print duplicate receipts. | Fixed: `3c61eed` |
| A14 | Browser storage | Two root-scope workers replaced each other. Local builds could serve stale files. Notification clicks lacked lifetime handling. | Fixed: `e8a8c01` |
| A15 | Secret handling | Debug logs exposed VAPID keys, request headers, and full application state. | Fixed: `fe37685` / `44801fb` |
| A16 | Failure recovery | Exhausted bootstrap requests left blocking loaders active. | Fixed: `a3eaa47` / `54d421b` |
| A17 | Control layout | Zero-height wrappers and absolute offsets made icons overlap. Responsive flow now separates product and image controls. | Fixed: `aecb188` / `39f48cc` |
| A18 | Control meaning | Repeated generic icons and inconsistent buttons obscured actions. Persian labels and distinct icons now identify actions. | Fixed: `aeca3d8` / `03ac64f` / `a9d6a36` |
| A19 | Workspace layout | Nested cards and large selectors wasted space. Compact menu controls and aligned invoice actions replace them. | Fixed: `3bf93d0` / `9a61c35` |
| A20 | Order controls | Order editing and payment actions lacked separation. Labeled groups now show their purpose. | Fixed: `f5bf947` |
| A21 | Product loading | Product details read missing images before requests finished. Loading, retry, and stale-response guards now protect rendering. | Fixed: `02328d0` |
| A22 | Optional printer state | Browser startup displayed errors without a printer service. Printing settings now show status and provide retry. | Fixed: `a284012` |
| A23 | Waiter table display | Table type depended on delayed derived data. Headers and account controls also clipped on small screens. | Fixed: `47c8fb9` |
| A24 | Loading behavior | Every socket connection blocked screens for five seconds. Snapshot completion now releases loading immediately. | Fixed: `8b31c50` |
| A25 | Repeated requests | Equivalent cafe updates repeated bootstrap. Unchanged table IDs repeated token requests. Route-specific delivery data loaded everywhere. | Fixed: `c6c0222` |
| A26 | Menu selection | Menu sorting changed shared arrays. Refreshes preserved stale selection. Menu edits used the cafe ID. | Fixed: `2d8d077` |
| A27 | Retry control | Region and printer-group reads retried forever. Late replies replaced data after cafe changes. | Fixed: `8c81f1c` |
| A28 | Narrow invoice rows | Action widths pushed invoice values outside 320-pixel screens. Mobile action rows now fit their cards. | Fixed: `63936e8` |
| A29 | Catalog ergonomics | Product search used 30vw. Category headers crowded controls. Search and headers now use available space. | Fixed: `d7e5192` |
| A30 | Collapsed controls | Table and delivery controls used 17-pixel wrappers. Product image actions depended on hover. | Fixed: `5bb28f4` / `f8314fb` |
| A31 | Contrast | Legacy colors weakened text, controls, focus indicators, and payment amounts. Shared palette and framework tokens now use tested contrast. | Fixed: `ef40ca5` / `da5b771`; checks `dfc04ad` |
| A32 | Color dependence | Invoice and table status depended on color. Persian status labels and distinct symbols now identify each state. | Fixed: `f364f31` |
| A33 | Table operations | Transfer controls called a missing handler. Current and merged tables relied on color alone. | Fixed: `aa2f8c3` / `ec1ae06`; operations remain disabled in the current UI |
| A34 | Analytics access | Unlabeled solid chart lines relied on color. Empty chart data caused rendering errors. | Fixed: `d81d6c3` |
| A35 | Date serialization | Analytics dates depended on global digit settings. Requests now explicitly use ASCII dates while display remains Persian. | Fixed: `d33e8eb` |
| A36 | Fabricated report | Customer satisfaction displayed a fixed 4.5 rating and an unrelated customer-count chart. The unsupported card is removed. | Fixed: `749a633` |
| A37 | Narrow analytics | Fixed 500-pixel chart containers clipped controls and totals. Responsive grids now fit narrow screens. | Fixed: `17723c1` |
| A38 | Table overview | Centered wrappers wasted space and used missing row keys. Responsive grids now use stable IDs and handle unloaded data. | Fixed: `9d3271d` |
| S05 | Mobile transport | The dormant mobile helper forced a proxy and accepted invalid Android certificates. | Fixed: `148af22`; mobile build unavailable |
| S06 | Dependency maintenance | Push dependencies included unused middleware and obsolete tooling. | Fixed: `1f1e480` |

## Review imported records

Repair work preserves imported historical records.
It does not change old balances, invoice rows, product ownership, or printed table codes.
Run `python manage.py audit_integrity` for a read-only inspection.
Keep the resulting report private with the installation's backups.

Imported data can contain duplicate table codes, conflicting cafe ownership, repeated payments, and overpaid orders.
Some repeated entries represent intended use or unsuccessful payment attempts.
Check source receipts and ownership before correcting any records.
Preserve original invoices and record each correction separately.

## Verification limits

Native bridge tests use mocked printers and operating-system callbacks.
The macOS ARM64 printer package builds successfully.
The native UI automation timed out during inspection.
Physical printer delivery and Windows/Linux packages remain unverified.
The legacy Flutter application still contains unfinished authentication, registration, and placeholder data flows.
These limitations prevent a claim that every legacy client is fully functional.

## Verification recorded on 2026-11-08

The backend suite passes 87 tests against a disposable database.
The admin runner reports 70 passing files and checks, including its source-loader helper.
Customer checks pass 37 cases. Waiter checks pass 25 cases.
Push and printer bridge suites each pass nine tests.
Recovery helpers pass 14 tests.
The final backend image passes Django checks and reports no pending migrations.
Local HTTP checks pass for the API, Django admin, customer app, receipt route, and admin app.
Gateway tests use mocks. No verification sends real payments, messages, or print jobs.

Customer browser checks cover narrow receipts, short landscape layouts, real wallet records, and manual table entry.
Waiter browser checks cover narrow table headers, direct table reloads, and menu-only table filtering.

Shared palette checks require 4.5:1 text contrast and 3:1 control-boundary contrast on the tested surfaces.
The checks also protect framework colors, payment overrides, and the active navigation marker.
Invoice and table badges use Persian words and distinct symbols.
Analytics charts use Persian period labels, visible legends, distinct point shapes, and different line patterns.
These checks cover the repaired controls. They do not constitute a complete accessibility certification.

Reference criteria:

- [W3C text contrast](https://www.w3.org/WAI/WCAG21/Understanding/contrast-minimum)
- [W3C use of color](https://www.w3.org/WAI/WCAG22/Understanding/use-of-color.html)
- [W3C control contrast](https://www.w3.org/WAI/WCAG22/Understanding/non-text-contrast.html)

Admin browser checks cover menus, products, product editing, invoices, table details, delivery controls, table settings, and printing feedback.
Menu, invoice, and analytics layouts pass checks at 320, 390, 768, 900, and 1280 CSS pixels.
Menu edit and delete controls have no overlapping bounds at those widths.
Invoice actions and status badges remain inside their scroll containers.
Rendered invoice action text measures between 7.42:1 and 12.65:1 contrast.
Status badge text measures 12.67:1 against its background.
The product editor keeps its footer visible at 320 pixels.
Printing settings show optional service failure and retry without startup error alerts.
The analytics period selector reveals its labeled update button and refreshes charts successfully.

Local screenshots:

- `local-data/admin-menu-mobile-final.jpg`
- `local-data/admin-menu-desktop-final.jpg`
- `local-data/admin-invoices-mobile-final.jpg`
- `local-data/admin-invoices-desktop-final.jpg`
- `local-data/admin-analytics-desktop-final.jpg`

The table overview passes initial loading and both mobile view checks.
Its regression test rejects the former null-data failure and verifies virtual-table filtering.

## Verification recorded on 2026-11-09

After publication cleanup, a rebuilt backend image passed 110 tests against a separate PostgreSQL test database.
The local account, mock payment, and card-transfer subset passed 47 tests.
That subset includes 23 card-transfer tests.
The recovery helpers passed another 14 tests.
Django checks, Compose validation, migration checks, and local HTTP checks passed.
The new GitHub Actions workflow uses the same full-suite commands.
Its local trial also passed both recovery helper suites.
These checks do not send money or verify the complete browser flow.

The public receipt stylesheet now uses Vazirmatn under the SIL Open Font License.
The repository includes the font's license and source information.
