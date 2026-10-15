"""Fictional development fixtures, inserted once into an empty mock database."""

from datetime import datetime, time, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import AvailabilityWindow, Group, Membership, Place, Poll, PollOption, RSVP, User, Vote
from .security import hash_password

DEMO_PASSWORD = "ThirdSpaceDemo123!"


def seed_mock_data(db: Session) -> bool:
    # Preserve edits across reloads; never mix fixtures into an existing dataset.
    if any(db.scalar(select(model.id).limit(1)) is not None
           for model in (User, Group, Membership, AvailabilityWindow, Place, Poll, PollOption, Vote, RSVP)):
        return False

    now = datetime.now(timezone.utc)
    password_hash = hash_password(DEMO_PASSWORD)
    users = [User(email=f"{name.lower()}@example.com", display_name=name,
                  password_hash=password_hash)
             for name in ("Alex", "Jordan", "Sam", "Taylor", "Morgan", "Casey")]
    db.add_all(users)
    db.flush()
    venues = [Place(name=name, activity_tag=tag, broad_location="Brooklyn, NY",
                    latitude=lat, longitude=lon, description="Fictional demo venue.")
              for name, tag, lat, lon in (
                  ("Demo Corner Cafe", "coffee", 40.678, -73.975),
                  ("Demo Games Lounge", "board games", 40.681, -73.977),
                  ("Demo Park Trail", "walking", 40.660, -73.970),
                  ("Demo Book Nook", "reading", 40.675, -73.980),
              )]
    db.add_all(venues)
    db.flush()
    for index, (name, hobbies, private, member_indexes) in enumerate((
        ("Brooklyn Coffee & Games", "coffee,board games,reading", False, (0, 1, 2, 3)),
        ("Weekend Wanderers", "walking,photography,hiking", False, (0, 2, 4, 5)),
        ("Friends Book Club", "reading,coffee", True, (1, 3, 5)),
    )):
        members = [users[i] for i in member_indexes]
        group = Group(name=name, description="A fictional group for exploring The Third Space.",
                      hobbies=hobbies, is_private=private, member_limit=12,
                      owner_id=members[0].id, join_token=f"demo-group-{index + 1}")
        db.add(group)
        db.flush()
        for position, user in enumerate(members):
            membership = Membership(group_id=group.id, user_id=user.id,
                                    role="owner" if position == 0 else "admin" if position == 1 else "member",
                                    hobbies=hobbies, timezone_name="America/New_York",
                                    broad_location="Brooklyn, NY", latitude=40.67 + position * .003,
                                    longitude=-73.98 + position * .002,
                                    hide_location=position == 3)
            membership.windows = [AvailabilityWindow(weekday=day, starts_at=start, ends_at=end)
                                  for day, start, end in ((2, time(18), time(21)),
                                                          (5, time(10), time(15)),
                                                          (6, time(10), time(15)))]
            db.add(membership)
        poll = Poll(group_id=group.id, created_by=members[0].id,
                    closes_at=now + timedelta(days=2) if index == 0 else now - timedelta(hours=1),
                    closed_at=None if index == 0 else now - timedelta(hours=1))
        db.add(poll)
        db.flush()
        for option_index in range(3):
            venue = venues[(index + option_index) % len(venues)]
            option = PollOption(poll_id=poll.id, activity={"coffee": "Coffee meetup",
                                "board games": "Board game cafe", "walking": "Neighborhood walk",
                                "reading": "Bookshop visit"}[venue.activity_tag],
                                duration_minutes=60 if venue.activity_tag == "coffee" else 120,
                                starts_at=(now + timedelta(days=4 + option_index)).replace(hour=15, minute=0, second=0, microsecond=0),
                                place_id=venue.id, available_user_ids=",".join(str(u.id) for u in members))
            poll.options.append(option)
            db.flush()
            voters = members[:3] if option_index == 0 else members[:1]
            db.add_all(Vote(option_id=option.id, user_id=u.id) for u in voters)
        if index == 2:
            db.flush()
            poll.confirmed_option_id = poll.options[0].id
            db.add_all(RSVP(option_id=poll.options[0].id, user_id=u.id, response=response)
                       for u, response in zip(members, ("going", "maybe", "not going")))
    db.commit()
    return True
