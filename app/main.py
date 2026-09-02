"""
FastAPI Main Application for LinkedIn Lead Generation & Job Matcher Platform.
"""
import os
import sys
import io
import csv
import json
import uuid
import asyncio

# Ensure Windows uses ProactorEventLoop for Playwright subprocesses
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

from typing import Dict, Any, Optional, List
from fastapi import FastAPI, Request, BackgroundTasks, HTTPException, Query
from fastapi.responses import HTMLResponse, StreamingResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from app.services.email_service import email_service_instance

from app.services.session_service import check_session_status, launch_manual_login
from app.services.scraper_service import ScraperService
from app.services.db_service import (
    get_all_leads,
    update_lead_status_or_notes,
    delete_lead,
    get_search_history,
    save_or_update_lead,
    init_db
)

# Initialize DB
init_db()


class EmailRequest(BaseModel):
    to_email: str
    subject: str
    body: str
    is_html: bool = False

app = FastAPI(
    title="LinkedIn Lead Hunter & Job Matcher",
    description="Plataforma profesional de prospección de clientes y matching de empleo con LinkedIn",
    version="1.0.0"
)

from fastapi.middleware.cors import CORSMiddleware

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], # Permite peticiones desde tu frontend en React/Vite
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Directories
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
TEMPLATES_DIR = os.path.join(BASE_DIR, "templates")
STATIC_DIR = os.path.join(BASE_DIR, "static")

os.makedirs(TEMPLATES_DIR, exist_ok=True)
os.makedirs(STATIC_DIR, exist_ok=True)

app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
templates = Jinja2Templates(directory=TEMPLATES_DIR)

# In-memory progress tracking for real-time SSE streams
ACTIVE_TASKS: Dict[str, Dict[str, Any]] = {}
TASK_QUEUES: Dict[str, asyncio.Queue] = {}
STOP_REQUESTS = set()


# --- Request Models ---
class JobSearchRequest(BaseModel):
    keywords: str = "Software Engineer"
    location: str = "Remote"
    limit: int = 5
    desired_titles: str = ""
    user_skills: str = ""
    preferred_locations: str = ""
    remote_only: bool = False


class LeadSearchRequest(BaseModel):
    keywords: str = ""
    title: str = "Gerente de Ventas"
    location: str = "Mexico"
    limit: int = 5
    target_roles: str = ""
    target_keywords: str = ""
    target_locations: str = ""
    require_email: bool = False


class CompanyAnalyzeRequest(BaseModel):
    company_url: str
    include_posts: bool = True
    target_criteria: Optional[Dict[str, Any]] = None


class InspectRequest(BaseModel):
    url: str
    target_criteria: Optional[Dict[str, Any]] = None


class LeadUpdateStatusRequest(BaseModel):
    crm_status: Optional[str] = None
    notes: Optional[str] = None
    tags: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None

class ManualLeadRequest(BaseModel):
    title: str
    subtitle: Optional[str] = ""
    phone: Optional[str] = ""
    email: Optional[str] = ""
    crm_status: Optional[str] = "Nuevo"
    notes: Optional[str] = ""
    linkedin_url: Optional[str] = ""



# --- Web Page Route ---
@app.get("/", response_class=HTMLResponse)
async def serve_dashboard(request: Request):
    """Serve the main clean dashboard interface."""
    return templates.TemplateResponse(request=request, name="index.html")


# --- Session Management Endpoints ---
@app.get("/api/session/status")
async def get_session_status():
    """Check LinkedIn session file status and active cookies."""
    return check_session_status()


@app.post("/api/session/login")
async def start_interactive_login():
    """Launch interactive browser to log in and save session."""
    try:
        res = await launch_manual_login(timeout=180000)
        return res
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# --- Real-time Task Progress Streaming (SSE) ---
@app.get("/api/tasks/{task_id}/events")
async def task_events_stream(task_id: str):
    """Server-Sent Events (SSE) endpoint to stream scraper progress."""
    if task_id not in TASK_QUEUES:
        TASK_QUEUES[task_id] = asyncio.Queue()

    queue = TASK_QUEUES[task_id]

    async def event_generator():
        try:
            while True:
                data = await queue.get()
                yield f"data: {json.dumps(data, ensure_ascii=False)}\n\n"
                if data.get("status") in ["completado", "error"]:
                    break
        except asyncio.CancelledError:
            pass

    return StreamingResponse(event_generator(), media_type="text/event-stream")


@app.post("/api/tasks/{task_id}/stop")
async def stop_task(task_id: str):
    """Signal a background search task to stop gracefully."""
    STOP_REQUESTS.add(task_id)
    return {"message": "Deteniendo tarea..."}


async def _notify_task(task_id: str, status: str, percent: int, message: str, item: Optional[Any] = None, results: Optional[Any] = None):
    """Notify task listeners via queue."""
    payload = {
        "task_id": task_id,
        "status": status,
        "percent": percent,
        "message": message,
        "item": item,
        "results": results
    }
    ACTIVE_TASKS[task_id] = payload
    if task_id in TASK_QUEUES:
        await TASK_QUEUES[task_id].put(payload)


# --- Core Action Endpoints ---
@app.post("/api/search/jobs")
async def search_jobs(req: JobSearchRequest, background_tasks: BackgroundTasks):
    """Initiate Job search with match scoring."""
    task_id = str(uuid.uuid4())
    TASK_QUEUES[task_id] = asyncio.Queue()
    
    criteria = {
        "desired_titles": req.desired_titles or req.keywords,
        "user_skills": req.user_skills,
        "preferred_locations": req.preferred_locations or req.location,
        "remote_only": req.remote_only
    }
    
    async def run_task():
        try:
            async def on_progress(status, percent, msg, item=None):
                await _notify_task(task_id, status, percent, msg, item=item)

            results = await ScraperService.search_and_score_jobs(
                keywords=req.keywords,
                location=req.location,
                limit=req.limit,
                target_criteria=criteria,
                progress_fn=on_progress,
                is_stopped_fn=lambda: task_id in STOP_REQUESTS
            )
            await _notify_task(task_id, "completado", 100, "Ofertas procesadas con éxito", results=results)
        except Exception as e:
            await _notify_task(task_id, "error", 0, f"Error: {str(e)}")
        finally:
            if task_id in STOP_REQUESTS:
                STOP_REQUESTS.remove(task_id)

    background_tasks.add_task(run_task)
    return {"task_id": task_id, "message": "Búsqueda iniciada"}


@app.post("/api/search/leads")
async def search_leads(req: LeadSearchRequest, background_tasks: BackgroundTasks):
    """Initiate B2B Decision Maker search with Lead Fit scoring."""
    task_id = str(uuid.uuid4())
    TASK_QUEUES[task_id] = asyncio.Queue()
    
    criteria = {
        "target_roles": req.target_roles or req.title,
        "target_keywords": req.target_keywords or req.keywords,
        "target_locations": req.target_locations or req.location,
        "require_email": req.require_email
    }
    
    async def run_task():
        try:
            async def on_progress(status, percent, msg, item=None):
                await _notify_task(task_id, status, percent, msg, item=item)

            results = await ScraperService.search_and_score_leads(
                keywords=req.keywords,
                title=req.title,
                location=req.location,
                limit=req.limit,
                target_criteria=criteria,
                progress_fn=on_progress,
                is_stopped_fn=lambda: task_id in STOP_REQUESTS
            )
            await _notify_task(task_id, "completado", 100, "Leads calificados con éxito", results=results)
        except Exception as e:
            await _notify_task(task_id, "error", 0, f"Error: {str(e)}")
        finally:
            if task_id in STOP_REQUESTS:
                STOP_REQUESTS.remove(task_id)

    background_tasks.add_task(run_task)
    return {"task_id": task_id, "message": "Búsqueda de leads iniciada"}

    background_tasks.add_task(run_task)
    return {"task_id": task_id, "message": "Búsqueda de leads iniciada"}


@app.post("/api/company/analyze")
async def analyze_company(req: CompanyAnalyzeRequest, background_tasks: BackgroundTasks):
    """Analyze company profile and buying signals from posts."""
    task_id = str(uuid.uuid4())
    TASK_QUEUES[task_id] = asyncio.Queue()
    
    async def run_task():
        try:
            async def on_progress(status, percent, msg):
                await _notify_task(task_id, status, percent, msg)

            result = await ScraperService.analyze_company(
                company_url=req.company_url,
                include_posts=req.include_posts,
                target_criteria=req.target_criteria or {},
                progress_fn=on_progress
            )
            await _notify_task(task_id, "completado", 100, "Análisis de empresa completado", [result])
        except Exception as e:
            await _notify_task(task_id, "error", 0, f"Error: {str(e)}")

    background_tasks.add_task(run_task)
    return {"task_id": task_id, "message": "Análisis de empresa iniciado"}


@app.post("/api/inspect")
async def inspect_url(req: InspectRequest, background_tasks: BackgroundTasks):
    """Direct URL inspection for single profile, job, or company."""
    task_id = str(uuid.uuid4())
    TASK_QUEUES[task_id] = asyncio.Queue()
    
    async def run_task():
        try:
            async def on_progress(status, percent, msg):
                await _notify_task(task_id, status, percent, msg)

            result = await ScraperService.inspect_url(
                url=req.url,
                target_criteria=req.target_criteria or {},
                progress_fn=on_progress
            )
            await _notify_task(task_id, "completado", 100, "Inspección completada", [result])
        except Exception as e:
            await _notify_task(task_id, "error", 0, f"Error: {str(e)}")

    background_tasks.add_task(run_task)
    return {"task_id": task_id, "message": "Inspección iniciada"}


# --- CRM & Leads Management Endpoints ---
@app.get("/api/leads")
async def list_leads(item_type: Optional[str] = None, crm_status: Optional[str] = None):
    """Get saved leads / database records."""
    return get_all_leads(item_type=item_type, crm_status=crm_status)


@app.patch("/api/leads/{lead_id}")
async def update_lead(lead_id: int, req: LeadUpdateStatusRequest):
    """Update lead CRM status, notes, tags, phone or email."""
    update_lead_status_or_notes(
        lead_id, 
        crm_status=req.crm_status, 
        notes=req.notes, 
        tags=req.tags,
        phone=req.phone,
        email=req.email
    )
    return {"success": True}

@app.post("/api/leads")
async def create_manual_lead(req: ManualLeadRequest):
    """Add a lead manually."""
    import uuid
    url = req.linkedin_url if req.linkedin_url else f"manual_{uuid.uuid4().hex}"
    lead_id = save_or_update_lead(
        item_type="lead (manual)",
        linkedin_url=url,
        title=req.title,
        subtitle=req.subtitle,
        location="No especificada",
        score=100,
        score_breakdown={"notes": ["Añadido manualmente"]},
        raw_data={},
        crm_status=req.crm_status,
        notes=req.notes,
        phone=req.phone,
        email=req.email
    )
    return {"success": True, "lead_id": lead_id}



@app.delete("/api/leads/{lead_id}")
async def remove_lead(lead_id: int):
    """Delete a lead."""
    delete_lead(lead_id)
    return {"success": True}


@app.get("/api/history")
async def fetch_history():
    """Retrieve search history."""
    return get_search_history(limit=20)


@app.get("/api/export/csv")
async def export_leads_csv(item_type: Optional[str] = None):
    """Export database leads to a formatted CSV file."""
    leads = get_all_leads(item_type=item_type)
    
    output = io.StringIO()
    writer = csv.writer(output)
    
    # Header
    writer.writerow([
        "ID", "Tipo", "Título / Nombre", "Subtítulo / Empresa", "Ubicación",
        "% Match", "Estado CRM", "Notas", "URL LinkedIn", "Fecha Guardado"
    ])
    
    for lead in leads:
        writer.writerow([
            lead.get("id"),
            lead.get("item_type"),
            lead.get("title"),
            lead.get("subtitle"),
            lead.get("location"),
            f"{lead.get('score', 0)}%",
            lead.get("crm_status"),
            lead.get("notes", ""),
            lead.get("linkedin_url"),
            lead.get("created_at")
        ])
        
    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename=leads_linkedin_{item_type or 'all'}.csv"}
    )


@app.post("/api/emails/send")
async def send_email_endpoint(request: EmailRequest):
    success, message = email_service_instance.send_email(
        request.to_email,
        request.subject,
        request.body,
        request.is_html
    )
    if success:
        return {"status": "success", "message": message}
    else:
        raise HTTPException(status_code=500, detail=message)
