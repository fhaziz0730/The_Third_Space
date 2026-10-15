# The Third Space

A small server-rendered FastAPI application for forming activity groups, recurring availability, and meetup polls. The initial product decisions and scope are in [MVP_SPEC.md](MVP_SPEC.md).

## Stack

- Python + FastAPI
- PostgreSQL + SQLAlchemy
- Jinja templates and plain CSS
- Regular HTML forms and links; no frontend build step

## Application layout

- `app/main.py` creates the FastAPI application and includes the route groups.
- `app/routes/auth.py` contains the home, registration, login, and logout routes.
- `app/routes/groups.py` contains group, membership, and availability routes.
- `app/routes/polls.py` contains poll, voting, and RSVP routes.
- `app/routes/places.py` contains the place catalog routes.
- `app/web.py` contains shared request, template, and membership helpers.
- `app/security.py` contains password hashing helpers.

## Run locally

1. Create and activate a Python virtual environment.
2. Install dependencies with `pip install -r requirements.txt`.
3. Copy `.env.example` to `.env` and load its values into your shell.
4. Start PostgreSQL with `docker compose up -d db`.
5. Run `uvicorn app.main:app --reload --env-file .env`.
6. Open `http://127.0.0.1:8000`.

Tables are created on app startup for the prototype. There is no migration workflow yet.

## Run with mock data

Set `USE_MOCK_DATA=true` in `.env`, then run:

```sh
uvicorn app.main:app --reload --env-file .env
```

This uses a separate SQLite database at `.mock/third_space.db`; PostgreSQL and
Docker are not needed in this mode. Your configured `DATABASE_URL` is ignored
while mock mode is enabled. Existing shell environment variables take precedence
over `.env`, so clear an exported `USE_MOCK_DATA` if changing the file has no effect.
Restart the server after switching modes.

The first startup creates six fictional users, three groups (including a private
group), weekly availability, four fictional venues, and three polls covering open,
closed, and confirmed states, with votes and RSVPs. Dates are relative to that first
startup. Log in as `alex@example.com` (owner of the first two groups) or
`jordan@example.com` (owner of the private group). All six accounts use
`ThirdSpaceDemo123!`; the other accounts are `sam@example.com`,
`taylor@example.com`, `morgan@example.com`, and `casey@example.com`.
Use these shared credentials only for local development.

Your changes persist across restarts, and fixtures are only inserted into an empty
database. To reset the demo, stop the server and delete `.mock/third_space.db`, then
start again. Set `USE_MOCK_DATA=false` and restart to return to PostgreSQL.

## Prototype notes

- Candidate times use group member weekly windows and each member's IANA time zone. Times are presented in UTC in this first pass.
- Candidate activities and default durations are in `app/scheduling.py`.
- Place ranking uses haversine straight-line distance; mock mode includes fictional venues and member coordinates for exploring ranking. Members can enter coordinates manually outside mock mode. No geocoding integration is configured. Do not treat these distances as driving estimates.
- Exact address data is currently collected as an optional field, encrypted at rest with `ADDRESS_ENCRYPTION_KEY`, not sent anywhere, and not used for ranking. Keep this key stable and private; existing addresses cannot be decrypted if the key changes. Select a privacy-appropriate geocoding provider before connecting that field to geocoding. The public OpenStreetMap Nominatim service must not receive personal or confidential address data; see its [usage policy](https://operations.osmfoundation.org/policies/nominatim/).
- Set strong, stable `SESSION_SECRET` and `ADDRESS_ENCRYPTION_KEY` values and enable `COOKIE_SECURE=true` when served over HTTPS. Generate the address key with `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`.
- This is a development prototype, not production-hardened authentication. Add CSRF protection, migrations, rate limiting, and production session/security configuration before public deployment.
