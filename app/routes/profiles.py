"""Group profile editing and authenticated town search."""

from typing import Annotated

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import JSONResponse, RedirectResponse
from sqlalchemy.orm import Session

from ..access import current_user, require_membership
from ..activities import ACTIVITIES
from ..db import get_db
from ..location_search import LocationSearchUnavailable, search_locations, uses_sample_locations
from ..profiles import ProfileForm
from ..web import page

router = APIRouter()


def profile_page(request, member, *, form=None, error=None):
    form = form or ProfileForm.from_member(member)
    return page(
        request,
        "availability.html",
        activity_choices=ACTIVITIES,
        user=member.user,
        member=member,
        group=member.group,
        form_values=form.template_values(member),
        error=error,
    )


@router.get("/groups/{group_id}/availability")
def availability_page(request: Request, group_id: int, db: Session = Depends(get_db)):
    member = require_membership(db, current_user(request, db), group_id)
    return profile_page(request, member)


@router.post("/groups/{group_id}/availability")
def save_availability(
    request: Request,
    group_id: int,
    form: Annotated[ProfileForm, Form()],
    db: Session = Depends(get_db),
):
    member = require_membership(db, current_user(request, db), group_id)
    try:
        form.apply_to(member)
    except ValueError as exc:
        return profile_page(request, member, form=form, error=str(exc))
    db.commit()
    return RedirectResponse(f"/groups/{group_id}", status_code=303)


@router.post("/groups/{group_id}/location-search")
def location_search(
    request: Request, group_id: int, q: Annotated[str, Form()], db: Session = Depends(get_db)
):
    require_membership(db, current_user(request, db), group_id)
    try:
        results = search_locations(q)
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)
    except LocationSearchUnavailable:
        return JSONResponse(
            {"error": "Location search is unavailable. Try again or use your current location."},
            status_code=503,
        )
    return JSONResponse(
        {"results": results, "sample": uses_sample_locations()},
        headers={"Cache-Control": "no-store"},
    )
