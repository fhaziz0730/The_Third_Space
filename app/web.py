from fastapi import Request
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from .models import Membership, User

templates = Jinja2Templates(directory="app/templates")

def current_user(request: Request, db: Session):
    user_id = request.session.get("user_id")
    return db.get(User, user_id) if user_id else None

def page(request: Request, name: str, **context):
    return templates.TemplateResponse(request=request, name=name, context={"request": request, "user": context.pop("user", None), **context})

def membership_for(db: Session, user: User, group_id: int):
    return db.query(Membership).filter_by(group_id=group_id, user_id=user.id).first()

def can_manage(member: Membership):
    return member.role in {"owner", "admin"}
