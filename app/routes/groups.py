import secrets
from datetime import datetime, timedelta, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from ..access import can_manage, current_user, membership_for, require_membership
from ..db import get_db
from ..groups import GroupForm
from ..models import Group, Membership, Poll, PollOption
from ..scheduling import generate_candidates
from ..web import page

router = APIRouter()


@router.get("/groups/new", response_class=HTMLResponse)
def new_group_page(request: Request, db: Session = Depends(get_db)):
    user = current_user(request, db)
    if not user:
        return RedirectResponse("/login", status_code=303)
    return page(request, "new_group.html", user=user, form=GroupForm())


@router.post("/groups")
def create_group(
    request: Request, form: Annotated[GroupForm, Form()], db: Session = Depends(get_db)
):
    user = current_user(request, db)
    if not user:
        return RedirectResponse("/login", status_code=303)
    group = Group(owner_id=user.id, join_token=secrets.token_urlsafe(18))
    try:
        form.apply_to(group, member_count=1)
    except ValueError as exc:
        return page(request, "new_group.html", user=user, form=form, error=str(exc))
    db.add(group)
    db.flush()
    db.add(Membership(group_id=group.id, user_id=user.id, role="owner"))
    db.commit()
    return RedirectResponse(f"/groups/{group.id}", status_code=303)


@router.get("/join/{token}", response_class=HTMLResponse)
def join_page(request: Request, token: str, db: Session = Depends(get_db)):
    group = db.query(Group).filter_by(join_token=token).first()
    if not group:
        raise HTTPException(404)
    user = current_user(request, db)
    members = len(group.memberships)
    if not user:
        request.session["pending_invitation"] = f"/join/{group.join_token}"
    full = group.member_limit is not None and members >= group.member_limit
    return page(
        request,
        "join.html",
        user=user,
        group=group,
        full=full,
        is_member=bool(user and membership_for(db, user, group.id)),
    )


@router.post("/join/{token}")
def join_group(request: Request, token: str, db: Session = Depends(get_db)):
    # Serialize joins so concurrent requests cannot exceed the member limit.
    group = (
        db.query(Group).filter_by(join_token=token).with_for_update().populate_existing().first()
    )
    if not group:
        raise HTTPException(404)
    user = current_user(request, db)
    if not user:
        request.session["pending_invitation"] = f"/join/{group.join_token}"
        return RedirectResponse("/login", status_code=303)
    if membership_for(db, user, group.id):
        return RedirectResponse(f"/groups/{group.id}", status_code=303)
    if group.member_limit is not None and len(group.memberships) >= group.member_limit:
        return page(request, "join.html", user=user, group=group, full=True, is_member=False)
    db.add(Membership(group_id=group.id, user_id=user.id))
    db.commit()
    return RedirectResponse(f"/groups/{group.id}/availability", status_code=303)


@router.get("/groups/{group_id}", response_class=HTMLResponse)
def group_page(request: Request, group_id: int, db: Session = Depends(get_db)):
    user = current_user(request, db)
    if not user:
        return RedirectResponse("/login", status_code=303)
    group = db.get(Group, group_id)
    member = membership_for(db, user, group_id) if group else None
    if not group or not member:
        raise HTTPException(404)
    polls = db.query(Poll).filter_by(group_id=group_id).order_by(Poll.created_at.desc()).all()
    return page(
        request,
        "group.html",
        user=user,
        group=group,
        member=member,
        polls=polls,
        can_manage=can_manage(member),
        member_count=len(group.memberships),
    )


@router.get("/groups/{group_id}/settings", response_class=HTMLResponse)
def group_settings_page(request: Request, group_id: int, db: Session = Depends(get_db)):
    user = current_user(request, db)
    member = require_membership(db, user, group_id, manage=True)
    return page(
        request,
        "group_settings.html",
        user=user,
        group=member.group,
        form=GroupForm.from_group(member.group),
    )


@router.post("/groups/{group_id}/settings")
def save_group_settings(
    request: Request,
    group_id: int,
    form: Annotated[GroupForm, Form()],
    db: Session = Depends(get_db),
):
    user = current_user(request, db)
    member = require_membership(db, user, group_id, manage=True)
    group = db.query(Group).filter_by(id=group_id).with_for_update().populate_existing().one()
    try:
        form.apply_to(group, member_count=len(group.memberships))
    except ValueError as exc:
        return page(
            request, "group_settings.html", user=user, group=member.group, form=form, error=str(exc)
        )
    db.commit()
    return RedirectResponse(f"/groups/{group_id}", status_code=303)


@router.post("/groups/{group_id}/members/{user_id}/role")
def change_member_role(
    request: Request, group_id: int, user_id: int, db: Session = Depends(get_db)
):
    user = current_user(request, db)
    manager = require_membership(db, user, group_id, manage=True)
    target = db.query(Membership).filter_by(group_id=group_id, user_id=user_id).first()
    if not target or target.role == "owner":
        raise HTTPException(403)
    if manager.role != "owner":
        raise HTTPException(403)
    target.role = "member" if target.role == "admin" else "admin"
    db.commit()
    return RedirectResponse(f"/groups/{group_id}", status_code=303)


@router.post("/groups/{group_id}/members/{user_id}/remove")
def remove_member(request: Request, group_id: int, user_id: int, db: Session = Depends(get_db)):
    user = current_user(request, db)
    manager = require_membership(db, user, group_id, manage=True)
    target = db.query(Membership).filter_by(group_id=group_id, user_id=user_id).first()
    if not target or target.role == "owner":
        raise HTTPException(403)
    if manager.role != "owner" and target.role == "admin":
        raise HTTPException(403)
    db.delete(target)
    db.commit()
    return RedirectResponse(f"/groups/{group_id}", status_code=303)


@router.post("/groups/{group_id}/leave")
def leave_group(request: Request, group_id: int, db: Session = Depends(get_db)):
    user = current_user(request, db)
    member = require_membership(db, user, group_id)
    if member.role == "owner":
        raise HTTPException(409, "The owner must transfer ownership before leaving.")
    db.delete(member)
    db.commit()
    return RedirectResponse("/", status_code=303)


@router.post("/groups/{group_id}/suggestions")
def create_suggestions(request: Request, group_id: int, db: Session = Depends(get_db)):
    user = current_user(request, db)
    member = require_membership(db, user, group_id, manage=True)
    group = member.group
    notices = []
    options = generate_candidates(db, group, notices=notices)
    if not options:
        return RedirectResponse(f"/groups/{group_id}?message=no-suggestions", status_code=303)
    poll = Poll(
        group_id=group_id,
        created_by=user.id,
        closes_at=datetime.now(timezone.utc) + timedelta(hours=2),
    )
    db.add(poll)
    db.flush()
    for option in options:
        venue = option.place
        poll.options.append(
            PollOption(
                activity=option.activity,
                duration_minutes=option.duration_minutes,
                starts_at=option.starts_at,
                place_id=venue.id if venue else None,
                google_place_id=getattr(venue, "google_place_id", None),
                available_ids=[person.user_id for person in option.available],
            )
        )
    db.commit()
    suffix = "?message=places-unavailable" if notices else ""
    return RedirectResponse(f"/groups/{group_id}/polls/{poll.id}{suffix}", status_code=303)
