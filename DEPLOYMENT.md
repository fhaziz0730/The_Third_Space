# Deploy The Third Space

This repository is prepared for Railway (web app), Neon (PostgreSQL), and GitHub
Actions (CI). No cloud resources are created by these files. Begin with a small
invited beta and complete the launch checklist before opening registration widely.

## 1. Accounts and access

Create the accounts yourself and enter billing details directly with the providers.

| Service | Access needed for setup | What is stored there |
| --- | --- | --- |
| GitHub | Repository write access; settings access for Actions, required checks, and the Railway GitHub App | Code, test runs, optional encrypted backup artifacts |
| Railway | An authenticated project session or project-scoped credential with deployment/variable access | App deployment and production environment secrets |
| Neon | Access to create a project/database and retrieve its connection strings | Persistent PostgreSQL data |
| Domain registrar (optional) | DNS record access | Custom domain configuration |
| Google Cloud (optional) | Places API project/key and billing/quota configuration | Venue search service; not required for local catalog use |
| Open-Meteo (commercial use) | Subscribed geocoding API key | Town/postal-code search service; no key needed for non-commercial use |

Do not put passwords, tokens, encryption keys, or database URLs into commits, issue
comments, or chat. Configure them in provider secret settings. A Railway deployment
token is not required in GitHub when using its native GitHub integration. GitHub
Actions tests use a disposable database and never need the production database URL.

## 2. Create PostgreSQL in Neon

1. Create a project near the Railway deployment region and a database for the app.
2. Copy a TLS-enabled connection URL. The application accepts `postgresql://`,
   `postgres://`, or `postgresql+psycopg://` and uses psycopg 3. Keep
   `sslmode=require` (or stronger). Use the direct connection for migration/backup
   commands initially. Keep the app at one replica until connection limits and
   resource usage have been measured.
3. Use a separate Neon branch/database for staging. Never point a preview, mock
   deployment, test job, or local experiment at the production database.
4. Review the selected plan's storage, compute, restore-history, and billing limits.
   Set provider budget alerts. Free-plan restore history is not a complete backup
   strategy; configure the encrypted backup workflow below as well.

The app persists its data in PostgreSQL. Container disk is disposable; never deploy
mock SQLite mode for real users.

## 3. Configure Railway

1. Create a project and connect this GitHub repository with the Railway GitHub App.
   Grant repository access only to this repository where possible.
2. Select `main` as the deployment branch. Railway reads `railway.json` and builds
   the non-root Docker image. It runs `python -m app.migrate` as a **pre-deploy**
   command, starts `python -m app.serve`, and checks `/health/ready` before routing
   traffic. Do not override these commands with a development `--reload` server.
3. Generate a Railway public domain. Enter its hostname and HTTPS origin in the
   variables below before the first successful production launch. For a custom
   domain, update both variables, add its DNS records, and wait for HTTPS to work.
4. In Railway's service settings, enable **Wait for CI**. This dashboard setting is
   not created by `railway.json`. Our CI workflow runs on pushes to `main` and PRs.
5. Keep one replica initially, set memory/CPU limits appropriate to your budget,
   configure usage alerts, and verify Railway's deployment logs. Platform billing,
   DNS, the public domain, and the CI gate need account-side setup.

Use `.env.production.example` as a reference; enter actual values in Railway's
Variables UI. Never upload your local development `.env` or commit a production
environment file.

| Variable | Production value |
| --- | --- |
| `APP_ENV` | `production` |
| `USE_MOCK_DATA` | `false` |
| `DATABASE_URL` | Neon PostgreSQL URL with TLS enabled |
| `SESSION_SECRET` | Random secret with at least 32 characters |
| `ADDRESS_ENCRYPTION_KEY` | A generated Fernet key; preserve it separately and securely |
| `COOKIE_SECURE` | `true` |
| `APP_ORIGIN` | `https://YOUR-APP.up.railway.app`, no path or trailing slash |
| `ALLOWED_HOSTS` | `YOUR-APP.up.railway.app,healthcheck.railway.app` |
| `FORWARDED_ALLOW_IPS` | `*` only for a container reachable exclusively through Railway's managed proxy |
| `PLACES_PROVIDER` | `local` initially; `google` when billing, quota, and a key are ready |
| `GOOGLE_PLACES_API_KEY` | Server-side key, only if enabling Google discovery |
| `LOCATION_SEARCH_PROVIDER` | `local` for initial smoke tests; `open-meteo` for live town search |
| `OPEN_METEO_API_KEY` | Commercial subscription key if the live app is commercial |

Generate secrets locally with these commands and enter the output directly into
Railway's secrets. Do not paste their output into build logs or this repository:

```sh
python -c "import secrets; print(secrets.token_urlsafe(48))"
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

Production refuses mock mode, weak/default secrets, insecure cookies, missing TLS
database configuration, invalid address encryption keys, missing HTTPS origins,
and an unrestricted host allowlist. Keep session/encryption keys stable across
redeploys. Losing the address key makes existing encrypted addresses unreadable.

The proxy setting matters for correct HTTPS links and IP-based login limits. Do
not use `FORWARDED_ALLOW_IPS=*` on a server directly accessible by untrusted clients.
CSRF validation uses the configured public origin and signed session tokens, not
CORS. Normal same-origin deployment does not need CORS enabled.

## 4. CI and release flow

`.github/workflows/ci.yml` installs Python 3.13 and Node 22, runs Python and JavaScript
tests, checks migrations against PostgreSQL 17, checks for model/schema drift, and
builds the production Docker image. It requires no production secrets. CI also
checks SQLite and adoption of existing prototype data.

In GitHub repository settings, enable a branch ruleset for `main`: require pull
requests and the `Test and verify migrations` CI check, and prevent force pushes.
Configure your GitHub notification preferences for failed Actions runs. A failing
CI check must block deployment through Railway's Wait for CI setting.

Use this release flow:

1. Make changes on a branch and open a pull request.
2. Let CI pass; review schema/data changes and provider cost implications.
3. Before a migration that changes existing data, take and verify a backup.
4. Merge to `main`. Railway waits for CI, runs migrations, builds/starts the app, and
   checks database/schema readiness. Do not run a second independent deploy workflow.
5. Verify `/health/live`, `/health/ready`, login, and a representative group flow.

Railway deployment health checks are deployment gates, not continuous monitoring.
Use an external uptime monitor for `/health/ready` when launching, and configure
provider email notifications. Expect a sleeping/free database to add latency; use
monitor intervals that fit your database compute allowance.

## 5. Database migrations

Install `requirements-dev.txt` for local development/testing. Run:

```sh
python -m app.migrate
python -m alembic current
python -m alembic check
```

These commands read shell environment variables, not `.env` automatically. For
example, to load the same environment file as the local server:

```sh
python -m dotenv -f .env run -- python -m app.migrate
```

Development startup applies migrations automatically and mock startup then seeds an
empty demo database. Production startup never creates or alters tables; its
pre-deploy command applies migrations, and readiness rejects an outdated schema.
Existing complete prototype databases are adopted without dropping tables or rows.
Back up existing real data before the first adoption, verify on a staging copy,
and investigate any unexpected-schema error rather than bypassing it with `stamp`.

For future changes, create a reviewed revision:

```sh
python -m alembic revision --autogenerate -m "describe the schema change"
```

The baseline is frozen in migration files, independent of later ORM edits. Prefer
additive, backward-compatible changes so the old deployment still works if a new
release fails after migration. The initial revisions intentionally refuse destructive
downgrades. App rollback does not roll back the database; use a forward fix or a
tested database restore when necessary. PostgreSQL migrations use an advisory lock
to serialize concurrent deployment attempts.

## 6. Encrypted backups and restore drill

The optional `.github/workflows/backup.yml` runs daily at 07:20 UTC and on manual
dispatch, **only when** repository variable `ENABLE_DB_BACKUPS=true` is configured.
It uses PostgreSQL 17 `pg_dump`, encrypts its stream with GnuPG AES-256, and uploads
only the encrypted file as a GitHub Actions artifact, retained for seven days.
Scheduled runs are best-effort and not a guaranteed backup service. Artifact storage
and download charges depend on your GitHub plan. For longer retention or independent
disaster recovery, copy encrypted archives into an appropriate private object store.

In GitHub Actions secrets, configure:

- `BACKUP_DATABASE_URL`: the direct TLS-enabled database URL. Use a dedicated backup
  role with read access to every application table and sequence if possible.
- `BACKUP_PASSPHRASE`: a separate random, single-line secret of at least 32 characters.
  Store a recovery copy in a password manager outside GitHub. Do not reuse the
  session secret or address encryption key.

Enable the variable, run the workflow manually, and verify the artifact and a restore
**before relying on daily runs**. Backups contain user data and must stay encrypted.
Check failed-run notifications. Match the PostgreSQL client major version to your
database version if upgrading from PostgreSQL 17. These backups do not include
Railway settings or secrets: retain the address encryption key separately.

Restore drill on a trusted machine with GnuPG and PostgreSQL 17 client tools:

1. Create a new, empty Neon staging branch/database, never the live production target.
2. Download an encrypted artifact and decrypt it locally with `gpg --output
   restore.dump --decrypt YOUR-BACKUP.dump.gpg`. GnuPG prompts for the backup
   passphrase; keep the plaintext dump off shared/synced directories.
3. Configure `PGHOST`, `PGPORT`, `PGDATABASE`, `PGUSER`, `PGPASSWORD`, and
   `PGSSLMODE=require` in your shell for the **new staging target**. Keeping passwords
   in environment variables avoids putting them into command arguments/history.
4. Run `pg_restore --dbname=YOUR_NEW_STAGING_DATABASE --exit-on-error --single-transaction
   --no-owner --no-acl restore.dump`, replacing the database name with the new empty
   staging target. `pg_restore` needs an explicit database argument to perform a restore.
5. Start a staging deployment using that database, the original address key, a
   separate session secret/origin, and HTTPS. Verify records, encrypted address
   readability, login, memberships, and polls. Do not send real users to it.
6. Remove the plaintext local dump using your normal secure data-handling process.
   Record the drill result. Only switch production to a restored database after
   verifying it and planning for any data written after the backup's timestamp.

For local backup creation, install PostgreSQL 17 client tools and GnuPG, configure
the two backup environment variables, then run `python scripts/backup_database.py`.
The script never writes a plaintext dump to disk, passes credentials outside command
arguments, and keeps a temporary passphrase file restricted to the current user on
POSIX systems. Run it only on a trusted machine.

## 7. Launch checklist

- [ ] CI is green and required on `main`; Railway Wait for CI is enabled.
- [ ] Production variables and HTTPS are configured; mock mode is off.
- [ ] Both health endpoints succeed; an unmigrated/unavailable database fails readiness.
- [ ] Register, sign in/out, create/join a group, save a profile, generate a poll,
  vote, close, confirm, and RSVP using two separate browser sessions.
- [ ] Browser forms and location search work with CSRF tokens. Invalid tokens and
  cross-origin submissions fail without modifying data.
- [ ] Login/registration throttling works. Limits are shared in PostgreSQL: 20 login
  requests/IP/15 minutes, 10 login requests/email/15 minutes, 5 registrations/IP/hour.
  Users on shared networks share an IP allowance; monitor and tune for your beta.
- [ ] Real town search and optional Google Places credentials/quotas are configured
  appropriately. Do not use the non-commercial free geocoder for a commercial app.
- [ ] An encrypted backup has been downloaded and successfully restored to staging.
- [ ] Privacy/terms pages contain operator contact information, retention periods,
  and the process for requesting account/data deletion. Prototype placeholders
  must be completed by the operator before public launch.
- [ ] Provider budget alerts, deployment-failure notifications, and external uptime
  checks are enabled. Keep the beta small until actual usage and costs are known.

Password resets and email verification are not yet implemented. For an invited
beta, document a support process; add a verified recovery flow before broader use.

References: [Railway configuration](https://docs.railway.com/config-as-code/reference),
[deployment CI gate](https://docs.railway.com/deployments/github-autodeploys),
[health checks](https://docs.railway.com/deployments/healthchecks),
[Neon pricing/limits](https://neon.com/pricing),
[OWASP CSRF guidance](https://cheatsheetseries.owasp.org/cheatsheets/Cross-Site_Request_Forgery_Prevention_Cheat_Sheet.html).
