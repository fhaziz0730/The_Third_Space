from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import Place
from ..web import current_user, page

router = APIRouter()


@router.get("/places", response_class=HTMLResponse)
def place_catalog_page(request: Request, db: Session = Depends(get_db)):
    user = current_user(request, db)
    if not user:
        return RedirectResponse("/login", status_code=303)
    from .models import Place
    places = db.query(Place).order_by(Place.activity_tag, Place.name).all()
    return page(request, "places.html", user=user, places=places)


@router.post("/places")
def add_place(request: Request, name: str = Form(), activity_tag: str = Form(), broad_location: str = Form(""), latitude: float = Form(), longitude: float = Form(), description: str = Form(""), db: Session = Depends(get_db)):
    from .models import Place
    user = current_user(request, db)
    if not user:
        return RedirectResponse("/login", status_code=303)
    if not (-90 <= latitude <= 90 and -180 <= longitude <= 180):
        raise HTTPException(400, "Coordinates are out of range.")
    db.add(Place(name=name.strip()[:120], activity_tag=activity_tag.strip().lower()[:60], broad_location=broad_location.strip()[:160], latitude=latitude, longitude=longitude, description=description.strip()[:300]))
    db.commit()
    return RedirectResponse("/places", status_code=303)
