# Run CafePay locally

The local setup starts PostgreSQL, Redis, the API, the customer app, and the staff app.
It keeps database files, uploaded files, and credentials outside Git.
It does not need a database backup for a fresh installation.

## Requirements

Install Docker with Compose v2, Git, and Python 3.8 or newer on your computer.
Docker Desktop provides Docker and Compose on macOS and Windows.
Image and package downloads need network access.

Keep the source directories beside each other:

```text
cafepay/
  cafepal/
  cafepay-admin/
  cafepay-webapp/
  cafepay_waiter/       # optional
```

The backend container uses Python 3.7 and Django 2.2.
The web app build containers use the older Node version and build tools that these apps need.
The build configuration selects Linux amd64 for compatibility with older dependencies.
Docker can run these containers through emulation on Apple Silicon.

## Create a fresh installation

Clone the repositories with the commands in [README.md](README.md#start-locally).
Run these commands from the `cafepal` directory:

```sh
./local init
./local up
./local admin
./local demo
./local check
```

`init` creates `.env.local` and local storage directories.
`up` builds the applications and starts their containers.
Backend startup applies database migrations and collects static files.
`admin` creates a local administrator with username `admin` and password `admin`.
`demo` creates a separate cafe, customer, menu, category, and table.
It does not create products.

Both account commands preserve existing demo records and passwords.
They refuse conflicts with accounts that lack the expected local markers.
They never reset restored account credentials.
Both commands require `CAFEPAY_LOCAL_RECOVERY=true`.

## Open the applications

| Service | Address |
| --- | --- |
| Customer app | [localhost:3000](http://localhost:3000) |
| Staff app | [localhost:3001](http://localhost:3001) |
| API | [localhost:8000/api/v1/](http://localhost:8000/api/v1/) |
| Django admin | [localhost:8000/admin/](http://localhost:8000/admin/) |
| Backend and database health | [localhost:8000/healthz/](http://localhost:8000/healthz/) |
| Optional waiter app | [localhost:3002](http://localhost:3002) |

Use `admin` for the username and password in either administration app.
Local administrators can access all cafes without adding staff records to those cafes.
Password login uses `POST /api/v1/local/login/` with `username` and `password`.
That endpoint requires local recovery mode.
Other configurations use the existing SMS login.

The demo customer uses these values:

| Item | Value |
| --- | --- |
| Cafe name | CafePay Local Demo |
| Cafe username | `cafepay-local-demo` |
| Customer phone | `09000000002` |
| Customer username | `cafepay-local-customer` |
| Customer password | `customer` |

Use the phone number in the customer login screen.
Local login returns a verification code without sending an SMS.
The demo command prints the cafe, menu, table, and table code for your installation.
Do not assume that database IDs match another installation.

Add a product through the staff app, set its price and stock, then publish the menu.
Use the printed table code in the customer app to place an order.

## Daily commands

Run commands from `cafepal`:

```sh
./local up
./local status
./local check
./local logs
./local down
```

`up` rebuilds changed images and starts the applications.
Source changes need another image build.
`down` stops containers and preserves the database and uploaded files.
`check` checks Django configuration, pending migrations, and application HTTP responses.
It does not test complete tasks in the browser.

Run a Django management command with:

```sh
./local manage help
```

To use the optional waiter app, first clone its repository beside `cafepal`:

```sh
cd ..
git clone https://github.com/cafepay-oss/cafepay_waiter.git
cd cafepal
COMPOSE_PROFILES=waiter ./local up
```

## Restore a backup

Restore before the first `./local up` command.
Backend startup creates application tables.
The restore helper refuses any database that already contains objects.
Do not delete an existing database to bypass this check.

Start with a fresh installation and run:

```sh
./local init
./local restore-db /absolute/path/to/database.dump
./local import-media /absolute/path/to/media-directory
./local up
./local admin
./local demo
./local check
```

The restore helper accepts PostgreSQL custom dumps, tar dumps, SQL dumps, and gzip compression.
SQL imports use one transaction and stop on errors.
Custom and tar restores leave out the original database owners and permission settings.
Only restore backups that you trust.

Some old SQL backups contain cleanup commands and ownership commands.
Prepare a separate copy of the supported older format before restoration:

```sh
python3 deploy/local/prepare_legacy_backup.py /absolute/path/to/database.bkp
./local restore-db local-data/backups/database.bkp.prepared.sql
```

The converter preserves the original file and the database COPY data.
It writes conversion counts and hashes beside the prepared file.
It refuses an existing output file.
Use `--output` to choose another output path.
The converter supports one known older format.
It cannot convert every SQL backup.

The media helper accepts directories, ZIP archives, and tar archives.
Choose content that matches the original Django `MEDIA_ROOT`.
The helper removes one outer `media/` directory automatically.
Inspect deeper archive directories before import.
The helper refuses links, paths outside the destination, and a nonempty destination.

The local database uses PostgreSQL 16 by default.
Set `POSTGRES_TAG` in `.env.local` when you need another compatible version.
A major database version change needs a separate migration plan.

## Tests

Run the local account, test payment, and card-transfer tests with:

```sh
./local test
```

The command builds the backend and starts PostgreSQL and Redis.
Django creates a separate test database and removes it afterward.
Its default name is `test_cafepay`.
With another database name, Django adds the `test_` prefix.
Do not run test commands against the same test database at the same time.

To run every backend test after the build:

```sh
docker compose --env-file .env.local -f compose.local.yml run \
  --rm --no-deps -T backend \
  python manage.py test cafepay --noinput --verbosity 1
```

Payment tests replace provider requests and notification delivery with test substitutes.
They do not send money or confirm browser behavior.
The card-transfer tests use temporary private receipt directories.

Run the recovery helpers and check Compose configuration with:

```sh
python3 deploy/local/test_recovery.py
python3 deploy/local/test_prepare_legacy_backup.py
./local config
```

GitHub Actions runs all backend tests and recovery helper tests from this repository alone.
It builds the backend and starts only PostgreSQL and Redis.
`config` checks configuration without printing generated credentials.
[AUDIT.md](AUDIT.md) records test results and earlier repair checks.

## Test payments

Local Compose enables `CAFEPAY_LOCAL_RECOVERY=true` and `CAFEPAY_MOCK_PAYMENTS=true`.
The test payment page requires both settings.
It provides **تأیید پرداخت آزمایشی** and **رد پرداخت آزمایشی** buttons.
Approval uses the normal order settlement and wallet records.
It then returns to the customer `/paymentResult/` page.
Test payments need no money or card details.

Card-to-card transfers use a separate receipt upload page.
Read [CARD_TRANSFERS.md](CARD_TRANSFERS.md) before enabling that method.
Use a sample receipt during local checks.

## Storage

| Data | Location |
| --- | --- |
| Database | `cafepay-local_database` Docker volume |
| Public uploaded images | `local-data/media/` |
| Private transfer receipts | `local-data/private-media/` |
| Generated credentials | `.env.local` |
| Prepared backups and local reports | `local-data/` |

Keep `.env.local` with the database backup.
The helper creates it with file mode `0600`.
Changing its password does not change an existing PostgreSQL database password.

Keep private receipts outside public media directories.
The proxy receives no private receipt volume.
Protect database backups, receipts, and local reports from public access.
Git ignores `.env.local`, local data, and private receipt storage.

## Limits

This setup supports isolated local development and recovery.
It retains Python 3.7, Django 2.2, and Node 14-era dependencies.
Upgrade these dependencies before public hosting.
The root `docker-compose.yml` describes the older deployment and needs separate review.

Compose exposes application ports only on your computer.
The backend and database network blocks outbound internet access.
The configuration supplies no live payment or SMS credentials.
Local web app builds disable Sentry and Google Tag Manager reporting.
The local setup does not start the push service or desktop printer app.

The Flutter app and printer app need separate development tools.
The Flutter app remains unfinished.
Physical printing and live payment, SMS, and push delivery need separate checks.
