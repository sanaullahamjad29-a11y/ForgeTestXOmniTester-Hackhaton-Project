import uuid
import asyncio
import base64
import httpx
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from fastapi import FastAPI, Depends, BackgroundTasks, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel, HttpUrl, Field
from .config import settings
from .db import Base, engine, get_db, SessionLocal, HAS_SQLALCHEMY
from .models import Run, Finding, Artifact
from .security import validate_url, build_containment_receipt
from .qa import scan, deterministic_report
from .ai import diagnose
from .fixer import analyze_and_fix_code

if sys.platform == "win32":
    try:
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
    except Exception:
        pass

cfg = settings()
_PYDANTIC_V2 = hasattr(BaseModel, "model_validate")

if HAS_SQLALCHEMY and engine is not None:
    Base.metadata.create_all(bind=engine)
    try:
        from sqlalchemy import inspect, text

        columns = {c["name"] for c in inspect(engine).get_columns("runs")}
        with engine.begin() as conn:
            if "workflow_json" not in columns:
                conn.execute(text("ALTER TABLE runs ADD COLUMN workflow_json TEXT NOT NULL DEFAULT '[]'"))
            if "evidence_json" not in columns:
                conn.execute(text("ALTER TABLE runs ADD COLUMN evidence_json TEXT NOT NULL DEFAULT '{}'"))
    except Exception:
        pass

app = FastAPI(
    title="TestForge × Omni-Tester AI API",
    version="2.0.0",
    description="Blast-Radius-Zero Sandboxed Web QA & Automated Code Doctor on Vultr",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=cfg.origins or ["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _str_field(default=..., pattern: str | None = None, max_length: int | None = None, min_length: int | None = None):
    kwargs = {}
    if max_length is not None:
        kwargs["max_length"] = max_length
    if min_length is not None:
        kwargs["min_length"] = min_length
    if pattern is not None:
        kwargs["pattern" if _PYDANTIC_V2 else "regex"] = pattern
    return Field(default, **kwargs)


class _CompatModel(BaseModel):
    if not _PYDANTIC_V2:
        @classmethod
        def model_validate(cls, obj):
            return cls.parse_obj(obj)

        def model_dump(self):
            return self.dict()


class WorkflowStep(_CompatModel):
    action: str = _str_field(
        default=...,
        pattern="^(navigate|click|fill|select|check|uncheck|assert_visible|assert_hidden|assert_text|assert_text_absent|assert_value|assert_count|assert_url|screenshot)$",
    )
    selector: str = _str_field(default="", max_length=500)
    value: str = _str_field(default="", max_length=2000)


class CreateRun(_CompatModel):
    target_url: HttpUrl
    depth: str = _str_field(default="standard", pattern="^(quick|standard|deep)$")
    workflow: list[WorkflowStep] = (
        Field(default_factory=list, max_length=60)
        if _PYDANTIC_V2
        else Field(default_factory=list, max_items=60)
    )


class FixCodePayload(_CompatModel):
    filename: str = _str_field(default="script.py", max_length=255)
    code: str = _str_field(default=..., min_length=1, max_length=100000)
    language: str | None = _str_field(default=None, max_length=40)


def _enrich_report_with_ai(evidence: dict, report: dict) -> dict:
    try:
        ai = diagnose(evidence, report)
        if ai:
            ai_findings = ai.get("findings") if isinstance(ai.get("findings"), list) else []
            for index, finding in enumerate(report["findings"]):
                if index >= len(ai_findings) or not isinstance(ai_findings[index], dict):
                    continue
                explanation = ai_findings[index]
                if explanation.get("description"):
                    finding["description"] = str(explanation["description"])[:2000]
                if explanation.get("recommendation"):
                    finding["recommendation"] = str(explanation["recommendation"])[:2000]
                if explanation.get("plain_english"):
                    finding["plain_english"] = str(explanation["plain_english"])[:1000]
                if explanation.get("code_fix"):
                    finding["code_fix"] = str(explanation["code_fix"])[:2000]
            if ai.get("plain_english_summary") and isinstance(report.get("first_time_guide"), dict):
                report["first_time_guide"]["plain_english_summary"] = str(ai["plain_english_summary"])[:1500]
            report["summary"] += (
                " AI-assisted explanations were added to observed findings; the evidence and score remain deterministic."
            )
        else:
            report["summary"] += " AI diagnosis unavailable: configure a Vultr inference key."
    except Exception as e:
        report["summary"] += f" AI diagnosis failed: {str(e)[:180]}"
    return report


def serialize(row):
    ev = json.loads(row.evidence_json or "{}")
    det = deterministic_report(ev) if ev else {}
    return {
        "id": row.id,
        "target_url": row.url,
        "status": row.status,
        "created_at": row.created_at,
        "finished_at": row.finished_at,
        "summary": row.summary,
        "score": row.score,
        "error": row.error,
        "execution_mode": row.mode,
        "workflow": json.loads(row.workflow_json or "[]"),
        "evidence": ev,
        "first_time_guide": ev.get("first_time_guide") or det.get("first_time_guide"),
        "containment_receipt": ev.get("containment_receipt") or det.get("containment_receipt"),
        "findings": [
            {
                "id": f.id,
                "severity": f.severity,
                "category": f.category,
                "title": f.title,
                "description": f.description,
                "evidence": f.evidence,
                "recommendation": f.recommendation,
            }
            for f in row.findings
        ],
    }


def _run_async_scan_in_thread(target_url: str, run_id: str, depth: str, workflow: list):
    if sys.platform == "win32":
        try:
            asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
        except Exception:
            pass
    return asyncio.run(scan(target_url, run_id, depth, workflow))


def _execute_browser_scan(target_url: str, run_id: str, depth: str, workflow: list) -> tuple[dict, list, dict]:
    if cfg.runner_mode == "remote":
        if not cfg.sandbox_worker_url or not cfg.sandbox_worker_token:
            raise RuntimeError("Remote runner selected but SANDBOX_WORKER_URL/TOKEN are not configured.")
        response = httpx.post(
            cfg.sandbox_worker_url.rstrip("/") + "/execute",
            headers={"Authorization": "Bearer " + cfg.sandbox_worker_token},
            json={"target_url": target_url, "depth": depth, "run_id": run_id, "workflow": workflow},
            timeout=cfg.max_run_seconds + 20,
        )
        response.raise_for_status()
        payload = response.json()
        evidence = payload["result"]
        if "pages" not in evidence or "coverage" not in evidence:
            raise RuntimeError(
                "Remote worker returned legacy single-page evidence. Upgrade and verify the Vultr guest image for v1.4+ multi-page crawling before using remote mode."
            )
        artifacts = []
        folder = cfg.artifacts / run_id
        folder.mkdir(parents=True, exist_ok=True)
        screenshots = evidence.pop("screenshots_base64", None) or {}
        legacy_shot = evidence.pop("screenshot_base64", None)
        if legacy_shot and not screenshots:
            screenshots = {"homepage.png": legacy_shot}
        for filename, encoded in screenshots.items():
            safe_name = Path(str(filename)).name
            if not safe_name.lower().endswith(".png") or not encoded:
                continue
            path = folder / safe_name
            path.write_bytes(base64.b64decode(encoded, validate=True))
            artifacts.append((path, "image/png"))
    else:
        evidence, artifacts = _run_async_scan_in_thread(target_url, run_id, depth, workflow)

    report = deterministic_report(evidence)
    report = _enrich_report_with_ai(evidence, report)
    evidence["first_time_guide"] = report.get("first_time_guide")
    evidence["containment_receipt"] = report.get("containment_receipt")
    return evidence, artifacts, report


def work(run_id: str):
    if not HAS_SQLALCHEMY or SessionLocal is None:
        return
    db = SessionLocal()
    row = db.get(Run, run_id)
    if not row:
        db.close()
        return
    try:
        row.status = "running"
        db.commit()
        evidence, artifacts, report = _execute_browser_scan(
            row.url, row.id, row.depth, json.loads(row.workflow_json or "[]")
        )
        row.summary = report["summary"]
        row.score = report["score"]
        row.evidence_json = json.dumps(evidence, default=str)
        for f in report["findings"]:
            db.add(
                Finding(
                    run_id=row.id,
                    severity=f["severity"],
                    category=f["category"],
                    title=f["title"],
                    description=f["description"],
                    evidence=f["evidence"],
                    recommendation=f["recommendation"],
                )
            )
        for p, ctype in artifacts:
            db.add(Artifact(run_id=row.id, filename=p.name, path=str(p)))
        row.status = "completed"
        row.finished_at = datetime.now(timezone.utc)
        db.commit()
    except Exception as e:
        db.rollback()
        row = db.get(Run, run_id)
        if row:
            row.status = "failed"
            row.error = str(e)[:2000]
            row.finished_at = datetime.now(timezone.utc)
            db.commit()
    finally:
        db.close()


@app.get("/api/health")
def health():
    return {
        "status": "ok",
        "service": "testforge-omni-tester-api",
        "version": "2.0.0",
        "hackathon_track": "Blast Radius Zero (Pattern A + Pattern B)",
    }


@app.get("/api/config")
def config():
    return {
        "ai_configured": bool(cfg.vultr_inference_api_key),
        "inference_model": cfg.vultr_inference_model,
        "runner_mode": cfg.runner_mode,
        "production_sandbox_configured": bool(cfg.sandbox_worker_url and cfg.sandbox_worker_token),
        "containment_profile": "vultr-blast-radius-zero-v2",
    }


@app.post("/api/fix-code")
async def fix_code_endpoint(request: Request):
    """Pattern A Endpoint: Accepts either JSON {'filename', 'code'} or multipart FormData ('file')."""
    content_type = request.headers.get("content-type", "")
    filename = "script.py"
    code = ""
    language = None

    if "application/json" in content_type:
        body = await request.json()
        payload = FixCodePayload.model_validate(body)
        filename = payload.filename
        code = payload.code
        language = payload.language
    else:
        form = await request.form()
        upload = form.get("file")
        if upload is not None and hasattr(upload, "read"):
            filename = getattr(upload, "filename", "uploaded_script.py") or "uploaded_script.py"
            raw_bytes = await upload.read()
            code = raw_bytes.decode("utf-8", errors="replace")
        elif "code" in form:
            code = str(form.get("code") or "")
            filename = str(form.get("filename") or "script.py")
            language = str(form.get("language") or "") or None
        else:
            raise HTTPException(400, "Provide a 'file' upload or JSON {'filename', 'code'}.")

    if not code.strip():
        raise HTTPException(400, "Source code file is empty.")

    return analyze_and_fix_code(filename=filename, source_code=code, language=language)


@app.post("/api/test-website")
async def test_website_sync(request: Request):
    """Synchronous First-Time-Friendly Website QA Sweep (supports JSON and FormData from Omni-Tester UI)."""
    content_type = request.headers.get("content-type", "")
    if "application/json" in content_type:
        body = await request.json()
        target_url = str(body.get("target_url") or body.get("url") or "")
        depth = str(body.get("depth") or "standard")
        region = str(body.get("region") or "US")
        workflow = body.get("workflow") if isinstance(body.get("workflow"), list) else []
    else:
        form = await request.form()
        target_url = str(form.get("url") or form.get("target_url") or "")
        depth = str(form.get("depth") or "standard")
        region = str(form.get("region") or "US")
        workflow = []

    if depth not in ("quick", "standard", "deep"):
        depth = "standard"

    url = validate_url(target_url)
    run_id = str(uuid.uuid4())
    evidence, artifacts, report = await asyncio.to_thread(_execute_browser_scan, url, run_id, depth, workflow)
    return {
        "id": run_id,
        "target_url": url,
        "region": region,
        "depth": depth,
        "status": "completed",
        "score": report["score"],
        "summary": report["summary"],
        "first_time_guide": report["first_time_guide"],
        "containment_receipt": report["containment_receipt"],
        "findings": report["findings"],
        "evidence": evidence,
        "artifacts": [{"filename": p.name} for p, _ in artifacts],
    }


@app.post("/api/containment-check")
async def containment_check(request: Request):
    """Interactive Containment Verification endpoint for Vultr Hackathon 'Containment Moment' demos."""
    body = await request.json()
    test_type = str(body.get("test_type") or "ssrf_localhost")
    if test_type == "ssrf_localhost":
        target = str(body.get("target") or "http://localhost:8000/admin")
        try:
            validate_url(target)
            blocked = False
            reason = "URL allowed"
        except HTTPException as exc:
            blocked = True
            reason = str(exc.detail)
        receipt = build_containment_receipt(
            "containment_ssrf_gate",
            {"test_type": test_type, "target": target, "blocked": blocked, "reason": reason},
            extra_flags=["ssrf-dns-guard=enforced", "loopback-blocked=true"],
        )
        return {"blocked": blocked, "target": target, "reason": reason, "containment_receipt": receipt}

    sample_code = str(
        body.get("code")
        or "import os\nprint(os.environ.get('VULTR_INFERENCE_API_KEY'))\nopen('/etc/passwd').read()\n"
    )
    res = analyze_and_fix_code("host_escape_probe.py", sample_code, "python")
    return {
        "blocked": bool(res["initial_sandbox_run"].get("containment_blocked")),
        "triggers": res["initial_sandbox_run"].get("containment_triggers", []),
        "remediated_code": res["fixed_code"],
        "containment_receipt": res["containment_receipt"],
    }


@app.post("/api/runs", status_code=202)
def create(payload: CreateRun, bg: BackgroundTasks, db=Depends(get_db)):
    url = validate_url(str(payload.target_url))
    row = Run(
        id=str(uuid.uuid4()),
        url=url,
        depth=payload.depth,
        workflow_json=json.dumps([x.model_dump() for x in payload.workflow]),
        status="queued",
        mode=cfg.runner_mode,
        summary="Queued for multi-page browser execution.",
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    bg.add_task(work, row.id)
    return serialize(row)


@app.get("/api/runs")
def runs(limit: int = 25, db=Depends(get_db)):
    from sqlalchemy import select
    from sqlalchemy.orm import selectinload

    rows = db.scalars(
        select(Run).options(selectinload(Run.findings)).order_by(Run.created_at.desc()).limit(max(1, min(limit, 100)))
    ).all()
    return {"items": [serialize(x) for x in rows]}


@app.get("/api/runs/{run_id}")
def run(run_id: str, db=Depends(get_db)):
    from sqlalchemy import select
    from sqlalchemy.orm import selectinload

    row = db.scalar(select(Run).options(selectinload(Run.findings)).where(Run.id == run_id))
    if not row:
        raise HTTPException(404, "Run not found")
    return serialize(row)


@app.get("/api/runs/{run_id}/artifacts")
def artifacts(run_id: str, db=Depends(get_db)):
    from sqlalchemy import select

    if not db.get(Run, run_id):
        raise HTTPException(404, "Run not found")
    rows = db.scalars(select(Artifact).where(Artifact.run_id == run_id)).all()
    return {"items": [{"filename": x.filename, "url": f"/api/artifacts/{x.id}"} for x in rows]}


@app.get("/api/artifacts/{artifact_id}")
def artifact(artifact_id: int, db=Depends(get_db)):
    x = db.get(Artifact, artifact_id)
    if not x:
        raise HTTPException(404, "Artifact not found")
    p = Path(x.path).resolve()
    if cfg.artifacts not in p.parents or not p.is_file():
        raise HTTPException(404, "Artifact missing")
    return FileResponse(p, media_type="image/png", filename=x.filename)


@app.get("/api/runs/{run_id}/report")
def report(run_id: str, db=Depends(get_db)):
    x = db.get(Run, run_id)
    if not x:
        raise HTTPException(404, "Run not found")
    ev = json.loads(x.evidence_json or "{}")
    det = deterministic_report(ev) if ev else {}
    return {
        "id": x.id,
        "url": x.url,
        "status": x.status,
        "score": x.score,
        "summary": x.summary,
        "error": x.error,
        "mode": x.mode,
        "evidence": ev,
        "first_time_guide": ev.get("first_time_guide") or det.get("first_time_guide"),
        "containment_receipt": ev.get("containment_receipt") or det.get("containment_receipt"),
        "findings": [
            {
                "id": f.id,
                "severity": f.severity,
                "category": f.category,
                "title": f.title,
                "description": f.description,
                "evidence": f.evidence,
                "recommendation": f.recommendation,
            }
            for f in x.findings
        ],
    }
