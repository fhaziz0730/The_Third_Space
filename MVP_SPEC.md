# The Third Space MVP

## Product goal

Help people form groups around shared hobbies, find a time when the group can meet, and suggest a nearby activity and place with a reasonably fair distribution of straight-line travel distances.

## Product constraints

- Solo-developer friendly: readable Python, conventional FastAPI, PostgreSQL, server-rendered Jinja templates, plain CSS, and only targeted HTMX or Alpine.js where they remove friction.
- No frontend build or bundle step. The first UI is deliberately barebones and will be restyled later from Figma designs.
- No public JSON API and no native mobile app.

## Accounts and groups

- Minimal account creation and sign-in distinguish users.
- Any signed-in member can create a group. A group has exactly one owner and may have admins. Admins can manage members and group settings and confirm a winning poll option.
- Groups are public (join by link) or private (invite link). A group may optionally have a member cap. At capacity, public and private join pages remain viewable and say the group is full, but joining is disabled.

## Member profile and availability

- Members select hobby/activity tags.
- Each member supplies a recurring weekly schedule separately for each group. A day may contain multiple local-time windows or none.
- Store wall-clock times and an IANA time-zone name, then resolve each date to UTC. Do not persist recurring availability as fixed UTC times because daylight-saving transitions change the offset.
- Hobby tags, availability, and broad location are visible by default, with per-member privacy controls. Exact starting addresses are private and are never shown to other group members.

## Suggestions, polls, and RSVP

- Generate several candidate options over the next month from group/member interests and availability.
- Each option includes activity, its default duration (usually 1–2 hours; absolute maximum 6), date/time, members available, and a suggested place when the place catalog can be ranked.
- Seed a small editable catalog of activity strings and places. MVP activity selection can be randomized from relevant interests.
- A generated option can become a poll. Votes can be changed until the poll closes, two hours after opening by default. An organizer/admin can close it early. On a tie, the organizer chooses; an admin may confirm the winning option.
- After confirmation, members can RSVP going, not going, or maybe.

## Nearby places and privacy

- MVP distance fairness uses straight-line distance. Prefer places that minimize the difference between the farthest and nearest member's distance, using member coordinates and catalog place coordinates. Do not label this as driving distance/time.
- Collect approximate starting addresses for internal calculations. Never reveal exact addresses to other members. Members may hide even their broad location.
- Geocoding is behind a provider interface. Do not submit exact home addresses to the public OpenStreetMap Nominatim service; its policy prohibits submitting personal or confidential material. Choose a privacy-appropriate provider or self-hosted geocoder before enabling address geocoding. Show disclosure to members when a provider receives an address.
- Live venue/event search and estimated driving time are later-stage work.

## MVP acceptance scope

1. Users can register and sign in.
2. Users can create public/private groups, configure optional capacity, invite/join, and manage roles/membership.
3. Members can set interests, broad-location visibility, and recurring per-group weekly availability.
4. The app can generate multiple candidate activity/time options in the next month and rank catalog places by straight-line distance fairness when coordinates are available.
5. Members can vote, change votes before closure, resolve ties, confirm, and RSVP.
6. The app runs against PostgreSQL without a frontend build step.

## Initial technical choices

- FastAPI + synchronous SQLAlchemy + PostgreSQL driver, Jinja templates, regular forms and links, small HTMX enhancements only where useful.
- Schema creation/migrations and deployment details will follow the repository's implementation needs. Keep dependencies and modules few and explicit.
- External geocoding provider remains a configuration/decision point; no provider receives an address by default.
