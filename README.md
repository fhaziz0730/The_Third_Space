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

Tables are created on app startup for the prototype. Existing SQLite and PostgreSQL
databases receive the additive venue-preference columns automatically, preserving
existing records. There is no general migration workflow yet.

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

## Nearby venues

In **Your group profile**, search for a town, city, or ZIP/postal code and choose a
matching area. Alternatively, choose **Use my current location**, which rounds browser
coordinates to two decimal places before filling the hidden location fields. Browser
location requires localhost or HTTPS and your permission. Save a preferred travel
radius between 1 and 200 km (default: 25 km). Users never need to enter coordinates.
An exact address is not needed and is kept in a collapsed optional section.

Town search uses Open-Meteo's geocoding service with GeoNames attribution and a
four-second timeout. It runs only after pressing Search (or Enter), and requires group
membership. Queries are sent in POST form data to avoid putting them in app access-log
URLs; only the search text is sent upstream. Public locality results are cached in
memory for up to ten minutes (256 queries per process). Selected names and coordinates
are saved only when the profile is submitted. Editing a selected area requires a new
selection, preventing old coordinates from being saved against a different town.
Use **Clear location** and save to remove the starting area.

`LOCATION_SEARCH_PROVIDER=open-meteo` is the default; no API key is required for its
non-commercial free service. For commercial deployment, configure a subscribed
`OPEN_METEO_API_KEY`, which selects the customer endpoint, and review the provider's
[terms](https://open-meteo.com/en/terms) and [geocoding documentation](https://open-meteo.com/en/docs/geocoding-api).
Mock mode (or `LOCATION_SEARCH_PROVIDER=local`) always searches a small offline sample
list, including Brooklyn/11201, Manhattan, Queens, New York City, Jersey City, Boston,
and Philadelphia. It never calls the external geocoder. Browser current location
continues to work when a town search fails or is unavailable.

**Generate suggestions** ranks activity-matching venues using only members available
for that event option. It prefers venues within every located attendee's preferred
radius, then minimizes the longest straight-line distance, then average distance.
If none fits everyone's radius, alternatives are labeled as outside a preferred
radius. Members without coordinates do not influence distance ranking, and the poll
reports missing locations. Only your own distance is displayed; other members'
starting coordinates and individual distances stay private. Hiding a broad location
does not disable private distance ranking.

Polls contain up to five options, balancing distinct times/activities and up to three
venue choices per time/activity. Local catalog venues work without external services
and are used in mock mode. If no matching venue is found, a time/activity can still
be offered without a venue.

### Optional Google Places discovery

1. Enable **Places API (New)** and billing in your Google Cloud project, create a
   server-side API key, and restrict it to the Places API and your deployment as
   appropriate. Configure quotas and billing alerts in Google Cloud.
2. Set the following in `.env`, keeping your actual key out of version control:

   ```dotenv
   USE_MOCK_DATA=false
   PLACES_PROVIDER=google
   GOOGLE_PLACES_API_KEY=your-server-side-key
   ```

3. Restart with `uvicorn app.main:app --reload --env-file .env`.
4. Members who want their locations used for external searches must check **Allow
   my approximate location to help find venues through Google Places** in their
   group profile. No members are opted in automatically.
5. Generate suggestions as a group owner or admin. The app combines matching local
   venues with Google results and applies the same group distance ranking.

Searches use rounded central areas derived only from opted-in, available members.
For dispersed groups, additional outlying areas are considered. Search radii are
capped at Google's 50 km limit, and each generation makes at most three Nearby
Search requests, with a four-second timeout per request and no automatic retries.
Results are deduplicated by place ID. This is a bounded shortlist, not an exhaustive
search of every possible meeting area. Venue categories are approximate: for
example, cafes suggested for board games need organizer verification.

Only Google place IDs are stored with poll options. Names, addresses, coordinates,
and provider attributions are retrieved live when viewing a poll, once per distinct
Google venue per page request. These Place Details calls also incur usage; no
cross-request venue cache is maintained. Poll pages disable browser caching. If
Google fails during discovery, local suggestions still work and the poll shows a
notice; if live details fail, the selected venue retains its Google Maps link.
Mock mode disables all Google API calls even if credentials are configured.

The app includes public `/privacy` and `/terms` pages and Google Maps attribution.
Complete the deployment-specific policy details before public hosting. Review the
[Nearby Search API](https://developers.google.com/maps/documentation/places/web-service/nearby-search),
[Place Details API](https://developers.google.com/maps/documentation/places/web-service/place-details),
and [Google Places policies](https://developers.google.com/maps/documentation/places/web-service/policies)
when configuring a deployment. Opening hours, booking, accessibility, and suitability
are not automatically verified. Distances are not driving or transit estimates.

Run the test suite with `python -m unittest discover -s tests`. Provider tests use
mocked responses and never require API credentials or network access.

## Prototype notes

- Candidate times use group member weekly windows and each member's IANA time zone. Times are presented in UTC in this first pass.
- Candidate activities and default durations are in `app/scheduling.py`.
- Place ranking uses haversine straight-line distance; mock mode includes fictional venues and member coordinates for exploring ranking. Members can enter coordinates manually outside mock mode. No geocoding integration is configured. Do not treat these distances as driving estimates.
- Exact address data is currently collected as an optional field, encrypted at rest with `ADDRESS_ENCRYPTION_KEY`, not sent anywhere, and not used for ranking. Keep this key stable and private; existing addresses cannot be decrypted if the key changes. Select a privacy-appropriate geocoding provider before connecting that field to geocoding. The public OpenStreetMap Nominatim service must not receive personal or confidential address data; see its [usage policy](https://operations.osmfoundation.org/policies/nominatim/).
- Set strong, stable `SESSION_SECRET` and `ADDRESS_ENCRYPTION_KEY` values and enable `COOKIE_SECURE=true` when served over HTTPS. Generate the address key with `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`.
- This is a development prototype, not production-hardened authentication. Add CSRF protection, migrations, rate limiting, and production session/security configuration before public deployment.
