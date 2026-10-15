from fastapi import Request
from fastapi.templating import Jinja2Templates
from markupsafe import Markup

from .config import PROJECT_ROOT
from .csrf import csrf_token
from .venues import KM_PER_MILE

templates = Jinja2Templates(directory=PROJECT_ROOT / "app" / "templates")
templates.env.globals["km_per_mile"] = KM_PER_MILE


def csrf_input(request):
    return Markup('<input type="hidden" name="csrf_token" value="{}">').format(csrf_token(request))


templates.env.globals["csrf_input"] = csrf_input


def page(request: Request, name: str, **context):
    response = templates.TemplateResponse(
        request=request,
        name=name,
        context={
            "request": request,
            "csrf_token": csrf_token(request),
            "user": context.pop("user", None),
            **context,
        },
    )
    response.headers["Cache-Control"] = "no-store"
    return response
