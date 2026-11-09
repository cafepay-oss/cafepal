# CafePay backend

CafePay helps cafes take orders, manage menus, and record payments.
Customers order through a Persian web app.
Staff use a separate app for tables, kitchen orders, delivery orders, and reports.

This repository contains the shared Python API and database models.
It also provides the local setup tools for the web apps.
The code uses Django 2.2, PostgreSQL, and Redis.

## Start locally

Install Docker with Compose v2, Git, and Python 3.8 or newer on your computer.
The containers include the older Python and Node versions that the apps need.

Clone these repositories into the same directory:

```sh
mkdir cafepay
cd cafepay
git clone https://github.com/cafepay-oss/cafepal.git
git clone https://github.com/cafepay-oss/cafepay-webapp.git
git clone https://github.com/cafepay-oss/cafepay-admin.git
cd cafepal
./local init
./local up
./local admin
./local demo
./local check
```

These steps create a new, empty installation with a separate demo cafe.
They do not require an old database backup.
The demo cafe starts without products.
Add products through the staff app, then publish the menu.

| Application | Address |
| --- | --- |
| Customer app | [localhost:3000](http://localhost:3000) |
| Staff app | [localhost:3001](http://localhost:3001) |
| Django admin | [localhost:8000/admin/](http://localhost:8000/admin/) |
| API | [localhost:8000/api/v1/](http://localhost:8000/api/v1/) |

Use `admin` for the local administrator username and password.
The demo customer phone is `09000000002`.
Local customer login returns a verification code without sending an SMS.
The demo command prints the table code for your installation.

Read [LOCAL_SETUP.md](LOCAL_SETUP.md) for daily commands, backup restoration, storage, and tests.
Restore an old database before the first `./local up` command.

## What the backend provides

- Cafe accounts, staff access, menus, products, and stock counts.
- Table orders, pickup orders, delivery orders, and kitchen status.
- Bills, wallet records, refunds, payment records, and reports.
- Live order updates through WebSockets.
- Receipt uploads for card-to-card transfers.
- A local payment simulator for testing without money.

Card-to-card checkout accepts an order after the customer uploads a receipt.
Staff check the bank transfer separately before they record the payment.
A receipt image does not prove that money arrived.
Read [CARD_TRANSFERS.md](CARD_TRANSFERS.md) before enabling this method.

## Tests

```sh
./local test
python3 deploy/local/test_recovery.py
python3 deploy/local/test_prepare_legacy_backup.py
```

GitHub Actions runs all backend tests and recovery helpers for pull requests and pushes to `main`.
The application tests use a separate PostgreSQL database.
They replace payment providers and notification delivery with test substitutes.
See [LOCAL_SETUP.md](LOCAL_SETUP.md#tests) for the complete backend test command.
[AUDIT.md](AUDIT.md) records earlier repairs and their verification limits.

## Other repositories

| Repository | Purpose |
| --- | --- |
| [cafepay-webapp](https://github.com/cafepay-oss/cafepay-webapp) | Customer web app |
| [cafepay-admin](https://github.com/cafepay-oss/cafepay-admin) | Staff web app |
| [cafepay_waiter](https://github.com/cafepay-oss/cafepay_waiter) | Optional waiter app |
| [cafepay-app](https://github.com/cafepay-oss/cafepay-app) | Unfinished Flutter mobile app |
| [cafepay-printer-driver](https://github.com/cafepay-oss/cafepay-printer-driver) | Desktop receipt printing |
| [node-notif](https://github.com/cafepay-oss/node-notif) | Web push service |

## Current limits

The local setup uses Python 3.7, Django 2.2, and older web app dependencies.
It opens application ports only on your computer.
It supplies no live payment or SMS credentials.
It supports local development and recovery.
Public hosting needs dependency upgrades, deployment work, and separate testing.

The root `docker-compose.yml` contains the older deployment setup.
Use `./local` and `compose.local.yml` for the documented local setup.
The mobile app remains unfinished.
Physical printing and live payment providers need separate checks.

## License

CafePay uses the [MIT License](LICENSE).
The bundled Vazirmatn font uses the [SIL Open Font License](local_static/font/OFL.txt).
