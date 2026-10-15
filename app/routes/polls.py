"""Poll views and mutations. All mutations lock the poll before checking its state."""

from collections import defaultdict
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import func
from sqlalchemy.orm import Session, selectinload

from ..access import can_manage, current_user, require_membership
from ..db import get_db
from ..models import RSVP, Poll, PollOption, User, Vote
from ..place_discovery import get_place, maps_link
from ..venues import venue_summary
from ..web import page

router = APIRouter()


def leading_options(counts):
    highest = max(counts.values(), default=0)
    return [option_id for option_id, count in counts.items() if count == highest]


def poll_for_update(db, poll_id):
    # Refresh identity-map state after acquiring the lock, including when another
    # request closed or confirmed the poll while this request was waiting.
    return db.query(Poll).filter_by(id=poll_id).with_for_update().populate_existing().first()


def option_access(request, db, option_id):
    option = db.get(PollOption, option_id)
    poll = poll_for_update(db, option.poll_id) if option else None
    if poll is None:
        raise HTTPException(404)
    member = require_membership(db, current_user(request, db), poll.group_id)
    return option, poll, member


def option_rows(db, poll, member):
    """Load votes and RSVPs in batches; resolve each external venue once per page."""
    option_ids = [option.id for option in poll.options]
    votes = defaultdict(list)
    for vote in db.query(Vote).filter(Vote.option_id.in_(option_ids)):
        votes[vote.option_id].append(vote)
    rsvps = defaultdict(list)
    for rsvp, user in db.query(RSVP, User).join(User).filter(RSVP.option_id.in_(option_ids)):
        rsvps[rsvp.option_id].append((rsvp, user))
    external_places = {}
    rows = []
    for option in poll.options:
        venue = option.place
        if option.google_place_id:
            if option.google_place_id not in external_places:
                external_places[option.google_place_id] = get_place(option.google_place_id)
            venue = external_places[option.google_place_id]
        available = [m for m in member.group.memberships if m.user_id in option.available_ids]
        option_votes = votes[option.id]
        option_rsvps = rsvps[option.id]
        rows.append(
            {
                "option": option,
                "votes": option_votes,
                "my_vote": next(
                    (vote for vote in option_votes if vote.user_id == member.user_id), None
                ),
                "rsvp": next(
                    (rsvp for rsvp, _ in option_rsvps if rsvp.user_id == member.user_id), None
                ),
                "rsvps": option_rsvps,
                "place": venue,
                "venue_summary": venue_summary(venue, available, member) if venue else None,
                "maps_url": maps_link(option.google_place_id) if option.google_place_id else None,
            }
        )
    return rows


def poll_redirect(poll):
    return RedirectResponse(f"/groups/{poll.group_id}/polls/{poll.id}", status_code=303)


@router.get("/groups/{group_id}/polls/{poll_id}")
def poll_page(request: Request, group_id: int, poll_id: int, db: Session = Depends(get_db)):
    member = require_membership(db, current_user(request, db), group_id)
    poll = (
        db.query(Poll)
        .options(selectinload(Poll.options).joinedload(PollOption.place))
        .filter_by(id=poll_id, group_id=group_id)
        .first()
    )
    if poll is None:
        raise HTTPException(404)
    rows = option_rows(db, poll, member)
    winners = leading_options({row["option"].id: len(row["votes"]) for row in rows})
    return page(
        request,
        "poll.html",
        user=member.user,
        group=member.group,
        poll=poll,
        options=rows,
        closed=poll.is_closed,
        can_manage=can_manage(member),
        tied=len(winners) > 1,
        can_confirm_tie=poll.created_by == member.user_id,
        winning_option_ids=winners,
    )


@router.post("/poll-options/{option_id}/vote")
def vote(request: Request, option_id: int, db: Session = Depends(get_db)):
    option, poll, member = option_access(request, db, option_id)
    if not poll.voting_open:
        raise HTTPException(409, "Voting is closed")
    if not db.query(Vote).filter_by(option_id=option.id, user_id=member.user_id).first():
        db.add(Vote(option_id=option.id, user_id=member.user_id))
    db.commit()
    return poll_redirect(poll)


@router.post("/poll-options/{option_id}/unvote")
def unvote(request: Request, option_id: int, db: Session = Depends(get_db)):
    option, poll, member = option_access(request, db, option_id)
    if poll.voting_open:
        db.query(Vote).filter_by(option_id=option.id, user_id=member.user_id).delete()
        db.commit()
    return poll_redirect(poll)


@router.post("/polls/{poll_id}/close")
def close_poll(request: Request, poll_id: int, db: Session = Depends(get_db)):
    poll = poll_for_update(db, poll_id)
    if poll is None:
        raise HTTPException(403)
    require_membership(db, current_user(request, db), poll.group_id, manage=True)
    if poll.closed_at is None:
        poll.closed_at = datetime.now(timezone.utc)
    db.commit()
    return poll_redirect(poll)


@router.post("/polls/{poll_id}/confirm")
def confirm_poll(
    request: Request, poll_id: int, option_id: int = Form(), db: Session = Depends(get_db)
):
    poll = poll_for_update(db, poll_id)
    if poll is None:
        raise HTTPException(403)
    member = require_membership(db, current_user(request, db), poll.group_id, manage=True)
    if poll.confirmed_option_id is not None:
        raise HTTPException(409, "This meetup has already been confirmed.")
    if not poll.is_closed:
        raise HTTPException(409, "Close voting before confirming a meetup.")
    if option_id not in {option.id for option in poll.options}:
        raise HTTPException(400, "That option is not part of this poll.")
    counts = dict.fromkeys((option.id for option in poll.options), 0)
    counts.update(
        db.query(Vote.option_id, func.count(Vote.id))
        .filter(Vote.option_id.in_(counts))
        .group_by(Vote.option_id)
        .all()
    )
    winners = leading_options(counts)
    if len(winners) > 1 and poll.created_by != member.user_id:
        raise HTTPException(403, "The organizer must choose between tied options.")
    if option_id not in winners:
        raise HTTPException(400, "Confirm the option with the most votes.")
    if poll.closed_at is None:
        poll.closed_at = poll.closes_at
    poll.confirmed_option_id = option_id
    db.commit()
    return poll_redirect(poll)


@router.post("/poll-options/{option_id}/rsvp")
def rsvp(request: Request, option_id: int, response: str = Form(), db: Session = Depends(get_db)):
    option, poll, member = option_access(request, db, option_id)
    if not poll.confirmed_option_id:
        raise HTTPException(404)
    if option.id != poll.confirmed_option_id or response not in {"going", "not going", "maybe"}:
        raise HTTPException(400)
    existing = db.query(RSVP).filter_by(option_id=option.id, user_id=member.user_id).first()
    if existing:
        existing.response = response
    else:
        db.add(RSVP(option_id=option.id, user_id=member.user_id, response=response))
    db.commit()
    return poll_redirect(poll)
