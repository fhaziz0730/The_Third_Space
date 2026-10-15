from fastapi import Request
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from .models import Membership, User
from .venues import KM_PER_MILE
from .csrf import csrf_token
from markupsafe import Markup

templates = Jinja2Templates(directory="app/templates")
templates.env.globals["km_per_mile"] = KM_PER_MILE
templates.env.globals["csrf_input"] = lambda request: Markup(
    '<input type="hidden" name="csrf_token" value="' + csrf_token(request) + '">'
)

def current_user(request: Request, db: Session):
    user_id = request.session.get("user_id")
    return db.get(User, user_id) if user_id else None

def page(request: Request, name: str, **context):
    response = templates.TemplateResponse(request=request, name=name, context={"request": request, "csrf_token": csrf_token(request), "user": context.pop("user", None), **context})
    response.headers["Cache-Control"] = "no-store"
    return response

def membership_for(db: Session, user: User, group_id: int):
    return db.query(Membership).filter_by(group_id=group_id, user_id=user.id).first()

def can_manage(member: Membership):
    return member.role in {"owner", "admin"}
