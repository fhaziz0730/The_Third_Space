from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import Group, User
from ..security import hash_password, password_matches
from ..web import current_user, membership_for, page

router = APIRouter()


@router.get("/", response_class=HTMLResponse)
def home(request: Request, db: Session = Depends(get_db)):
    user = current_user(request, db)
    if not user:
        return page(request, "welcome.html")
    groups = [membership.group for membership in user.memberships]
    return page(request, "home.html", user=user, groups=groups)


@router.get("/register", response_class=HTMLResponse)
def register_page(request: Request):
    return page(request, "register.html")


@router.post("/register")
def register(request: Request, email: str = Form(), display_name: str = Form(), password: str = Form(), db: Session = Depends(get_db)):
    email = email.strip().lower()
    if len(password) < 10:
        return page(request, "register.html", error="Use a password with at least 10 characters.")
    if db.query(User).filter_by(email=email).first():
        return page(request, "register.html", error="That email is already registered.")
    user = User(email=email, display_name=display_name.strip()[:80], password_hash=hash_password(password))
    db.add(user)
    db.commit()
    request.session["user_id"] = user.id
    return RedirectResponse("/", status_code=303)


@router.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    return page(request, "login.html")


@router.post("/login")
def login(request: Request, email: str = Form(), password: str = Form(), db: Session = Depends(get_db)):
    user = db.query(User).filter_by(email=email.strip().lower()).first()
    if not user or not password_matches(password, user.password_hash):
        return page(request, "login.html", error="Email or password was incorrect.")
    request.session.clear()
    request.session["user_id"] = user.id
    return RedirectResponse("/", status_code=303)


@router.post("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/", status_code=303)
