# Developer guide

The Third Space is a small server-rendered FastAPI application. Keep a single
application and database, with modules organized around the work they do. There is
no frontend build, repository layer, service container, or generic CRUD framework.

## Start here

1. Read `app/main.py` for startup, middleware order, and router registration.
2. Open the route module for the feature you are changing.
3. Follow its named helpers into validation, scheduling, or external providers.
4. Add an integration test for behavior that crosses HTTP or database boundaries.

| Area | Files | Responsibility |
| --- | --- | --- |
| HTTP routes | `app/routes/` | Authorize, validate, query/update, commit, render/redirect |
| Group/profile forms | `app/groups.py`, `app/profiles.py` | Shared form fields and validation; validate before assigning model values |
| Access rules | `app/access.py` | Current user, membership lookup, and manager checks |
| Activity catalog | `app/activities.py` | Stable tags, labels, durations, and Google venue categories |
| Scheduling | `app/scheduling.py` | Shared times, available attendees, venue choices, and the poll shortlist |
| Venue ranking | `app/venues.py` | Distance math and preference scoring; no network requests |
| External lookups | `app/location_search.py`, `app/place_discovery.py` | Provider requests, parsing, budgets, fallback, and offline behavior |
| Persistence | `app/models.py`, `app/db.py` | Tables/relationships, small entity properties, engines and request sessions |
| Presentation | `app/web.py`, `app/templates/`, `app/static/` | Template context, reusable markup, and progressive enhancement |
| Security/runtime | `app/config.py`, `app/csrf.py`, `app/security.py`, `app/rate_limits.py` | Deployment checks and request/account protection |
| Schema history | `migrations/`, `app/migrate.py` | The only schema-upgrade path |
| Operations | `DEPLOYMENT.md`, `.github/workflows/`, `scripts/backup_database.py` | Deployment, CI, backup/restore, and launch configuration |

## Follow a request

Profile editing follows one path:

```text
POST /groups/{id}/availability
  → CSRF/session/host middleware
  → ProfileForm (FastAPI parses the form fields)
  → require_membership
  → form.apply_to(member) (all validation before mutations)
  → db.commit()
  → redirect to the group
```

Both GET and invalid POST responses use `ProfileForm` to build `form_values`, so
templates have one consistent shape. They do not choose between saved data and
submitted data for each field. Creating and editing groups likewise share
`GroupForm` and the `group_fields.html` partial.

Scheduling is a pipeline:

```text
activity catalog + member profiles
  → shared_times (pure time-zone/availability calculation)
  → bounded sample of unique Candidate objects
  → local/optional external venue lookup
  → distance ranking and alternative venues
  → up to five poll options
```

`Candidate` carries a stable activity tag, time, attendees, and optional venue.
Its display label/duration come from the catalog; there is no reverse lookup from
a human label to an activity tag. Google response details remain transient; only
place IDs are persisted for external venues.

## Database and transaction rules

- `create_app(database_engine=...)` owns a session factory. Request dependencies
  and development startup use that same engine. Tests can provide an isolated
  database without bypassing startup or patching the global engine.
- Routes own their commits. Form validation does not commit or roll back the
  caller's transaction. Check every field before assigning any ORM state.
- Poll mutations go through `poll_for_update`/`option_access`. On PostgreSQL these
  lock and refresh the poll before checking whether voting is open, closed, or
  confirmed. This serializes voting, closing, and confirmation. SQLite tests do
  not prove row-lock behavior; CI also exercises PostgreSQL.
- `Poll.is_closed` and `Poll.voting_open` define state once, including expired
  deadlines and SQLite's naive datetime handling. GET views never close polls
  by writing to the database.
- Poll pages batch-load votes and RSVPs. Do not add a query inside the option
  loop when the data can be loaded once for all option IDs.
- Joining and editing group capacity lock the same group row before checking
  member counts. New features that change capacity must use that discipline.
- Schema changes belong in reviewed Alembic revisions. The obsolete ad hoc schema
  upgrader has been removed. Leave deployed migration history unchanged.
- Account throttling intentionally commits its counters even for rejected login
  attempts; it is an exception to normal feature transaction boundaries.

## Common changes

**Add an activity:** update `ACTIVITIES` in `app/activities.py`. Profile choices,
scheduling durations, provider categories, and demo labels use that catalog.

**Add a profile preference:** add a field to `ProfileForm`, map its initial value
in `from_member`, validate/apply it in `apply_to`, and add its HTML control. Add a
model column/migration only if it needs persistence. Keep submitted values intact
when rendering validation errors.

**Add a group setting:** update `GroupForm` and the shared `group_fields.html`.
Both creation and editing automatically use the same validation and fields.

**Add a group action:** reuse `require_membership` with `manage=True` when needed.
Keep owner-only rules explicit. Ordinary membership failures return 404; manager
failures return 403. Public pages can still redirect anonymous users to login.

**Add a provider:** keep its HTTP/parsing behavior at the provider boundary. Feed
venue candidates into the existing ranking pipeline. Keep mock mode offline,
preserve request budgets/timeouts, and follow the provider's storage requirements.
Introduce a common adapter interface only when multiple real adapters need it.

**Change poll behavior:** start with state properties and `leading_options`, then
the affected action and template. Preserve organizer-only tie resolution and
confirmation immutability. Keep all poll writes under the same lock.

## Readability checks

Install `requirements-dev.txt`. Run:

```sh
ruff check app tests scripts
ruff format --check app tests scripts
djlint app/templates --check
python -m unittest discover -s tests
node tests/location_picker.test.cjs
```

Use `ruff check --fix`, `ruff format`, and `djlint app/templates --reformat` to
apply formatting. Configuration is in `pyproject.toml`, and CI enforces it.
Formatting intentionally excludes historical migrations. JavaScript and CSS use
two-space indentation, with no bundler or runtime framework.

## Structural review: resolved and remaining

Resolved in this pass:

- A large group router mixed profile parsing, location search, and group actions.
  Profile routes and validation now have clear homes, with one form model.
- Failed coordinate validation could require rolling back earlier profile edits.
  Validation now completes before any edits, preserving the current session state.
- Group creation and editing duplicated fields and disagreed about validation.
  They share a model and an HTML partial; malformed limits no longer silently
  remove the group limit.
- Authorization, poll deadlines, winner selection, and provider activity mappings
  were repeated. Each rule now has one named definition.
- Poll reads grew votes/RSVP queries per option; writes could race close/vote
  checks. Reads are batched and writes share locking and refreshed state.
- Candidate sampling counted duplicate times toward its search budget. Unique
  candidates are now sampled before venue lookup.
- An admin role-change request could silently succeed without changing anything.
  Owner-only role changes now consistently return 403 for other callers.
- Legacy CSV attendance could display one available member for an empty string.
  A model property handles serialization and counts empty attendance correctly.
- App startup and request tests could use different database engines. The factory
  now accepts the engine used for both, and paths do not depend on the working directory.
- Minified templates and dense Python made changes difficult to review. Code and
  templates now have enforced formatting.
- CSRF handling had separate body paths for forms and JavaScript headers, and the
  latter bypassed the form-size limit. Both now use one bounded read/replay path.

Remaining design decisions should be handled when the relevant feature needs them:

- **Normalize attendee/interests data before richer participation features.**
  `available_user_ids` and hobbies still use prototype CSV storage. Attendee access
  is isolated behind `PollOption.available_ids`; use a join table when adding
  per-attendee state or cross-event queries. A storage migration is deliberately
  unnecessary for this readability pass.
- **Keep the current settings process-scoped.** Runtime provider configuration is
  read from environment variables; changing it requires a restart. If multiple
  tenants need different providers, introduce explicit per-app/provider settings
  then, rather than an adapter registry now.
- **Scheduling is a bounded heuristic.** It favors early majority-available times,
  not a global optimum across all members and dates. Keep changes to fairness or
  the search strategy separate from HTTP and venue-provider work.
- **Mock and SQLite tests complement PostgreSQL tests.** PostgreSQL is necessary
  for concurrency, constraints, and deployment checks. Do not infer production
  locking guarantees from an in-memory SQLite test.

The account-recovery, email-verification, and deployment-specific policy tasks in
`DEPLOYMENT.md` remain separate product/launch work.
