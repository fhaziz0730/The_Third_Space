from datetime import datetime, timedelta, timezone
import secrets

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import AvailabilityWindow, Group, Membership, Poll, PollOption, User
from ..scheduling import generate_candidates
from ..web import can_manage, current_user, membership_for, page

router = APIRouter()


@router.get("/groups/new", response_class=HTMLResponse)
def new_group_page(request: Request, db: Session = Depends(get_db)):
    user = current_user(request, db)
    if not user:
        return RedirectResponse("/login", status_code=303)
    return page(request, "new_group.html", user=user)


@router.post("/groups")
def create_group(request: Request, name: str = Form(), description: str = Form(""), hobbies: str = Form(""), visibility: str = Form("public"), member_limit: str = Form(""), db: Session = Depends(get_db)):
    user = current_user(request, db)
    if not user:
        return RedirectResponse("/login", status_code=303)
    limit = int(member_limit) if member_limit.strip().isdigit() else None
    group = Group(name=name.strip()[:100], description=description.strip()[:500], hobbies=hobbies[:1000], is_private=visibility == "private", member_limit=limit, owner_id=user.id, join_token=secrets.token_urlsafe(18))
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
    full = group.member_limit is not None and members >= group.member_limit
    return page(request, "join.html", user=user, group=group, full=full, is_member=bool(user and membership_for(db, user, group.id)))


@router.post("/join/{token}")
def join_group(request: Request, token: str, db: Session = Depends(get_db)):
    user = current_user(request, db)
    if not user:
        return RedirectResponse("/login", status_code=303)
    group = db.query(Group).filter_by(join_token=token).first()
    if not group:
        raise HTTPException(404)
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
    return page(request, "group.html", user=user, group=group, member=member, polls=polls, can_manage=can_manage(member), member_count=len(group.memberships))


@router.get("/groups/{group_id}/settings", response_class=HTMLResponse)
def group_settings_page(request: Request, group_id: int, db: Session = Depends(get_db)):
    user = current_user(request, db)
    member = membership_for(db, user, group_id) if user else None
    if not member or not can_manage(member):
        raise HTTPException(403)
    return page(request, "group_settings.html", user=user, group=member.group)


@router.post("/groups/{group_id}/settings")
def save_group_settings(request: Request, group_id: int, name: str = Form(), description: str = Form(""), hobbies: str = Form(""), visibility: str = Form("public"), member_limit: str = Form(""), db: Session = Depends(get_db)):
    user = current_user(request, db)
    member = membership_for(db, user, group_id) if user else None
    if not member or not can_manage(member):
        raise HTTPException(403)
    limit = int(member_limit) if member_limit.strip().isdigit() else None
    if limit is not None and limit < len(member.group.memberships):
        return page(request, "group_settings.html", user=user, group=member.group, error="The member limit cannot be lower than the current number of members.")
    member.group.name = name.strip()[:100]
    member.group.description = description.strip()[:500]
    member.group.hobbies = hobbies[:1000]
    member.group.is_private = visibility == "private"
    member.group.member_limit = limit
    db.commit()
    return RedirectResponse(f"/groups/{group_id}", status_code=303)


@router.get("/groups/{group_id}/availability", response_class=HTMLResponse)
def availability_page(request: Request, group_id: int, db: Session = Depends(get_db)):
    user = current_user(request, db)
    member = membership_for(db, user, group_id) if user else None
    if not member:
        raise HTTPException(404)
    return page(request, "availability.html", user=user, member=member, group=member.group, windows=member.windows)


@router.post("/groups/{group_id}/availability")
def save_availability(request: Request, group_id: int, timezone_name: str = Form("UTC"), schedule: str = Form(""), hobbies: str = Form(""), broad_location: str = Form(""), exact_address: str = Form(""), latitude: str = Form(""), longitude: str = Form(""), hide_hobbies: str | None = Form(None), hide_availability: str | None = Form(None), hide_location: str | None = Form(None), db: Session = Depends(get_db)):
    from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
    user = current_user(request, db)
    member = membership_for(db, user, group_id) if user else None
    if not member:
        raise HTTPException(404)
    try:
        ZoneInfo(timezone_name)
        parsed = []
        for line in schedule.splitlines():
            if not line.strip():
                continue
            day, start, end = [part.strip() for part in line.split(",")]
            day_num = int(day)
            start_time, end_time = datetime.strptime(start, "%H:%M").time(), datetime.strptime(end, "%H:%M").time()
            if not 0 <= day_num <= 6 or start_time == end_time:
                raise ValueError
            parsed.append((day_num, start_time, end_time))
    except (ValueError, ZoneInfoNotFoundError):
        return page(request, "availability.html", user=user, member=member, group=member.group, windows=member.windows, error="Use a valid time zone and one 'weekday,start,end' window per line. Weekdays are Monday=0 through Sunday=6.")
    member.windows.clear()
    for weekday, starts_at, ends_at in parsed:
        member.windows.append(AvailabilityWindow(weekday=weekday, starts_at=starts_at, ends_at=ends_at))
    member.timezone_name = timezone_name
    member.hobbies = hobbies[:1000]
    member.broad_location = broad_location[:160]
    member.exact_address = exact_address[:400]
    try:
        member.latitude = float(latitude) if latitude.strip() else None
        member.longitude = float(longitude) if longitude.strip() else None
        if (member.latitude is None) != (member.longitude is None):
            raise ValueError
        if member.latitude is not None and not (-90 <= member.latitude <= 90 and -180 <= member.longitude <= 180):
            raise ValueError
    except ValueError:
        db.rollback()
        return page(request, "availability.html", user=user, member=member, group=member.group, windows=member.windows, error="Enter both valid latitude and longitude values, or leave both blank.")
    member.hide_hobbies = bool(hide_hobbies)
    member.hide_availability = bool(hide_availability)
    member.hide_location = bool(hide_location)
    db.commit()
    return RedirectResponse(f"/groups/{group_id}", status_code=303)


@router.post("/groups/{group_id}/members/{user_id}/role")
def change_member_role(request: Request, group_id: int, user_id: int, db: Session = Depends(get_db)):
    user = current_user(request, db)
    manager = membership_for(db, user, group_id) if user else None
    target = membership_for(db, db.get(User, user_id), group_id) if db.get(User, user_id) else None
    if not manager or not can_manage(manager) or not target or target.role == "owner":
        raise HTTPException(403)
    # Only the owner can grant or revoke admin privileges.
    if target.role == "admin" and manager.role != "owner":
        raise HTTPException(403)
    if manager.role == "owner":
        target.role = "member" if target.role == "admin" else "admin"
    db.commit()
    return RedirectResponse(f"/groups/{group_id}", status_code=303)


@router.post("/groups/{group_id}/members/{user_id}/remove")
def remove_member(request: Request, group_id: int, user_id: int, db: Session = Depends(get_db)):
    user = current_user(request, db)
    manager = membership_for(db, user, group_id) if user else None
    target_user = db.get(User, user_id)
    target = membership_for(db, target_user, group_id) if target_user else None
    if not manager or not can_manage(manager) or not target or target.role == "owner":
        raise HTTPException(403)
    if manager.role != "owner" and target.role == "admin":
        raise HTTPException(403)
    db.delete(target)
    db.commit()
    return RedirectResponse(f"/groups/{group_id}", status_code=303)


@router.post("/groups/{group_id}/leave")
def leave_group(request: Request, group_id: int, db: Session = Depends(get_db)):
    user = current_user(request, db)
    member = membership_for(db, user, group_id) if user else None
    if not member:
        raise HTTPException(404)
    if member.role == "owner":
        raise HTTPException(409, "The owner must transfer ownership before leaving.")
    db.delete(member)
    db.commit()
    return RedirectResponse("/", status_code=303)


@router.post("/groups/{group_id}/suggestions")
def create_suggestions(request: Request, group_id: int, db: Session = Depends(get_db)):
    user = current_user(request, db)
    member = membership_for(db, user, group_id) if user else None
    if not member or not can_manage(member):
        raise HTTPException(403)
    group = member.group
    options = generate_candidates(db, group)
    if not options:
        return RedirectResponse(f"/groups/{group_id}?message=no-suggestions", status_code=303)
    poll = Poll(group_id=group_id, created_by=user.id, closes_at=datetime.now(timezone.utc) + timedelta(hours=2))
    db.add(poll)
    db.flush()
    for option in options:
        poll.options.append(PollOption(activity=option["activity"], duration_minutes=option["duration_minutes"], starts_at=option["starts_at"], place_id=option["place"].id if option["place"] else None, available_user_ids=",".join(str(person.user_id) for person in option["available"])))
    db.commit()
    return RedirectResponse(f"/groups/{group_id}/polls/{poll.id}", status_code=303)
