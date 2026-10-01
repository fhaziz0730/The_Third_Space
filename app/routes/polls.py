from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import Poll, PollOption, RSVP, User, Vote
from ..web import can_manage, current_user, membership_for, page

router = APIRouter()


@router.get("/groups/{group_id}/polls/{poll_id}", response_class=HTMLResponse)
def poll_page(request: Request, group_id: int, poll_id: int, db: Session = Depends(get_db)):
    user = current_user(request, db)
    member = membership_for(db, user, group_id) if user else None
    poll = db.get(Poll, poll_id)
    if not member or not poll or poll.group_id != group_id:
        raise HTTPException(404)
    now = datetime.now(timezone.utc)
    closed = poll.closed_at is not None or now >= poll.closes_at
    if now >= poll.closes_at and poll.closed_at is None:
        poll.closed_at = poll.closes_at
        db.commit()
    options = []
    for option in poll.options:
        votes = db.query(Vote).filter_by(option_id=option.id).all()
        vote = next((item for item in votes if item.user_id == user.id), None)
        rsvp = db.query(RSVP).filter_by(option_id=option.id, user_id=user.id).first()
        attendees = db.query(RSVP, User).join(User, User.id == RSVP.user_id).filter(RSVP.option_id == option.id).all()
        options.append({"option": option, "votes": votes, "my_vote": vote, "rsvp": rsvp, "rsvps": attendees, "place": option.place})
    vote_counts = [len(row["votes"]) for row in options]
    tied = len(vote_counts) > 1 and len(set(vote_counts)) == 1
    can_confirm_tie = poll.created_by == user.id
    return page(request, "poll.html", user=user, group=member.group, poll=poll, options=options, closed=closed, can_manage=can_manage(member), tied=tied, can_confirm_tie=can_confirm_tie)


@router.post("/poll-options/{option_id}/vote")
def vote(request: Request, option_id: int, db: Session = Depends(get_db)):
    user = current_user(request, db)
    option = db.get(PollOption, option_id)
    poll = db.get(Poll, option.poll_id) if option else None
    if not user or not option or not membership_for(db, user, poll.group_id):
        raise HTTPException(404)
    if poll.closed_at or datetime.now(timezone.utc) >= poll.closes_at:
        raise HTTPException(409, "Voting is closed")
    if not db.query(Vote).filter_by(option_id=option_id, user_id=user.id).first():
        db.add(Vote(option_id=option_id, user_id=user.id))
    db.commit()
    return RedirectResponse(f"/groups/{poll.group_id}/polls/{poll.id}", status_code=303)


@router.post("/poll-options/{option_id}/unvote")
def unvote(request: Request, option_id: int, db: Session = Depends(get_db)):
    user = current_user(request, db)
    option = db.get(PollOption, option_id)
    poll = db.get(Poll, option.poll_id) if option else None
    if not user or not option or not membership_for(db, user, poll.group_id):
        raise HTTPException(404)
    if not poll.closed_at and datetime.now(timezone.utc) < poll.closes_at:
        vote = db.query(Vote).filter_by(option_id=option_id, user_id=user.id).first()
        if vote:
            db.delete(vote)
            db.commit()
    return RedirectResponse(f"/groups/{poll.group_id}/polls/{poll.id}", status_code=303)


@router.post("/polls/{poll_id}/close")
def close_poll(request: Request, poll_id: int, db: Session = Depends(get_db)):
    user = current_user(request, db)
    poll = db.get(Poll, poll_id)
    member = membership_for(db, user, poll.group_id) if user and poll else None
    if not member or not can_manage(member):
        raise HTTPException(403)
    poll.closed_at = datetime.now(timezone.utc)
    db.commit()
    return RedirectResponse(f"/groups/{poll.group_id}/polls/{poll.id}", status_code=303)


@router.post("/polls/{poll_id}/confirm")
def confirm_poll(request: Request, poll_id: int, option_id: int = Form(), db: Session = Depends(get_db)):
    user = current_user(request, db)
    poll = db.get(Poll, poll_id)
    member = membership_for(db, user, poll.group_id) if user and poll else None
    if not member or member.role not in {"owner", "admin"} or not poll.closed_at:
        raise HTTPException(403)
    selected = db.get(PollOption, option_id)
    if not selected or selected.poll_id != poll.id:
        raise HTTPException(400, "That option is not part of this poll.")
    counts = {option.id: db.query(Vote).filter_by(option_id=option.id).count() for option in poll.options}
    highest = max(counts.values(), default=0)
    winners = [candidate_id for candidate_id, count in counts.items() if count == highest]
    if len(winners) > 1 and poll.created_by != user.id:
        raise HTTPException(403, "The organizer must choose between tied options.")
    if len(winners) == 1 and option_id != winners[0]:
        raise HTTPException(400, "Confirm the option with the most votes.")
    poll.confirmed_option_id = option_id
    db.commit()
    return RedirectResponse(f"/groups/{poll.group_id}/polls/{poll.id}", status_code=303)


@router.post("/poll-options/{option_id}/rsvp")
def rsvp(request: Request, option_id: int, response: str = Form(), db: Session = Depends(get_db)):
    user = current_user(request, db)
    option = db.get(PollOption, option_id)
    poll = db.get(Poll, option.poll_id) if option else None
    if not user or not option or not poll.confirmed_option_id or not membership_for(db, user, poll.group_id):
        raise HTTPException(404)
    if option.id != poll.confirmed_option_id or response not in {"going", "not going", "maybe"}:
        raise HTTPException(400)
    existing = db.query(RSVP).filter_by(option_id=option_id, user_id=user.id).first()
    if existing:
        existing.response = response
    else:
        db.add(RSVP(option_id=option_id, user_id=user.id, response=response))
    db.commit()
    return RedirectResponse(f"/groups/{poll.group_id}/polls/{poll.id}", status_code=303)
