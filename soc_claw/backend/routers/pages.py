from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from soc_claw.pipeline import load_alerts

router = APIRouter(tags=["pages"])

TEMPLATES_DIR = Path(__file__).parent.parent.parent / "frontend" / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


@router.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    return templates.TemplateResponse(request, "index.html", context={
        "alerts": load_alerts(),
        "analyst": request.state.user,  # S6: real authenticated username
    })
