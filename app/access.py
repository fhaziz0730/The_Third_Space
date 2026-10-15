"""Shared authentication and group permissions. Routes choose redirects or errors."""

from fastapi import HTTPException, Request
from sqlalchemy.orm import Session

from .models import Membership, User


def current_user(request: Request, db: Session) -> User | None:
    user_id = request.session.get("user_id")
    return db.get(User, user_id) if user_id else None


def membership_for(db: Session, user: User | None, group_id: int) -> Membership | None:
    if user is None:
        return None
    return db.query(Membership).filter_by(group_id=group_id, user_id=user.id).first()


def can_manage(member: Membership) -> bool:
    return member.role in {"owner", "admin"}


def require_membership(db, user, group_id, *, manage=False) -> Membership:
    member = membership_for(db, user, group_id)
    if member is None or (manage and not can_manage(member)):
        raise HTTPException(403 if manage else 404)
    return member
