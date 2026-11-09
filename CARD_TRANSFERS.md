# Card-to-card checkout

Shared pickup and delivery links open the menu before login.
Visitors select products, then log in when they continue to checkout.
The app preserves their selected products during phone verification and name entry.
Anonymous browsing creates no order records and exposes no customer orders or balances.

Customers can pay a pickup or delivery order through their banking app.
They choose **کارت‌به‌کارت**, copy the destination card and amount, then transfer the money.
They select a receipt image after the transfer.
The app uploads the image immediately.
A successful upload accepts the order for preparation.
Staff check the payment separately.

The confirmation page links to order tracking.
Opening that page again restores the saved state.
A receipt image does not prove that money arrived.
The app does not check bank accounts or read amounts from receipt images.

## Enable the method

Open **کارت‌به‌کارت و رسیدها** in the staff app.
Enter the destination card number and account holder, then enable the method.
The method starts disabled.
Only verified staff with `cafepay.can_manage_cafe` can change these settings.

The app stores and shows amounts in tomans.
It also provides the equivalent rial amount for copying into banking apps.
This payment method adds no gateway fee and takes no money from the customer's app wallet.

## Order and payment states

| State | Customer view | Payment record |
| --- | --- | --- |
| `draft` | Card details, quoted amount, and receipt selection | None |
| `submitted` | Accepted order with tracking | Receipt claim; no payment credit |
| `confirmed` | Staff confirmed the transfer | One manual payment credited to the cafe |
| `rejected` | Staff explanation and replacement receipt option | No payment credit |
| `expired` | A new quote is needed after basket changes | None |

Submitted orders appear in the staff pickup and delivery order list.
They use the existing new-order notifications.
Preparation does not wait for payment approval.
Staff can check the payment after they close the order.
Repeated confirmation does not add another payment.

Staff must give a reason when they reject a receipt.
The customer can then upload a replacement receipt.
Rejection does not cancel food preparation.
Staff must compare the transfer with their bank records before confirmation.

## Order checks

The server calculates the amount and checks who owns the order.
It saves the destination card, account holder, amount, and delivery charge with the quote.
Later delivery price changes do not change that quote.
Database locks protect simultaneous submissions and payment confirmation.

After submission, the customer cannot change the basket, address, or delivery charge.
Submitted orders cannot use the normal payment checkout again.
Orders with active transfer records cannot move between tables or merge with other orders.
Repeated uploads return the saved result after a lost response.

Changed orders and conflicting payments need staff investigation.
The server rejects a second payment when these checks fail.
Duplicate image checks reduce accidental reuse.
They do not prove that a receipt is real.

## Receipt privacy

The server accepts JPEG, PNG, and WebP images up to 8 MiB and 16 megapixels.
It removes image metadata and limits each image to 2000 × 2000 pixels.
It saves the result with private file permissions.

Only the customer who owns the order and verified cafe staff can read its receipt.
Receipt images have no public media URL.
The response uses `Cache-Control: private, no-store`.

`CAFEPAY_PRIVATE_MEDIA_ROOT` selects the private receipt directory.
Its default location in Docker is `/app/private-media`.
Both Compose files mount that directory only into the backend.
The proxy receives no private receipt volume.

Keep receipts separate from public images and include them in protected backups.
Set the proxy request limit above 8 MiB to leave space for upload headers.
The supplied production proxy permits 10 MiB.
Apply migration `0216_card_transfer` and rebuild both web apps before enabling this method.

## Tests

Run from `cafepal`:

```sh
./local test
```

This command includes tests for card transfers, local accounts, and test payments.
The tests use a separate PostgreSQL database and temporary receipt storage.
The card-transfer tests cover these cases:

- Product creation, receipt submission, preparation, and payment confirmation.
- Customer ownership and staff access.
- Duplicate uploads and simultaneous requests.
- Delivery charges and changed baskets.
- Invalid images and receipt replacement.
- Payment checks after delivery.
- Table movement and merged table protection.

Run the web app checks with:

```sh
cd ../cafepay-webapp
npm test
cd ../cafepay-admin
node --test tests/*.cjs
```

On 2026-11-09, the local backend passed 52 tests.
This included 23 card-transfer tests and five public menu entry tests.
The recovery helpers passed another 14 tests.
These results do not confirm the complete process in the browser.

## Browser check

Create a sample product named `E2E Espresso` at 25000 toman in your demo cafe.
Open that cafe from the customer app and copy its menu link.
Open the link in a private browser window.
The address has this form: `http://localhost:3000/user/home/?token=<menu-token>`.
Use the menu token from your installation.
The link must include `token`; `/user/home` alone opens the table scanner.
The menu appears without login.
Add one `E2E Espresso`, then select **رفتن به مرحله‌ی بعد**.
Use a new local test phone, such as `09000000910`, and enter a test name.
Local test mode fills the verification code and sends no SMS.
After login, check that the basket contains the same product at 25000 toman.
Choose **ادامه و پرداخت**, **کارت‌به‌کارت**, then **نمایش کارت و ارسال رسید**.
Use a sample receipt and send no real money.
`localhost` links work on this computer; public sharing requires deployment.

Saved browser screenshots show the menu before login and a customer basket totaling 25000 toman.
They do not show every login step or the final card-transfer instructions.
Follow these steps to check the complete process:

1. Configure a test destination card in a local cafe.
2. Create a product and order it as a customer.
3. Choose card-to-card payment and upload a sample receipt.
4. Reload the confirmation page and check the saved order.
5. Send the order to the kitchen before payment confirmation.
6. Confirm the transfer in the staff app.
7. Repeat confirmation and check that each amount appears only once.

Do not send real money during this check.
