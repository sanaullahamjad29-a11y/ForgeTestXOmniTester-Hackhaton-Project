import json
import httpx
from .config import settings


def _call_vultr_llm(system_prompt: str, user_payload: dict, max_tokens: int = 1800) -> dict | None:
    cfg = settings()
    if not cfg.vultr_inference_api_key:
        return None
    user_text = json.dumps(user_payload, default=str)[:24000]
    try:
        from openai import OpenAI
        client = OpenAI(
            base_url=cfg.vultr_inference_base_url,
            api_key=cfg.vultr_inference_api_key,
            timeout=40,
            max_retries=1,
        )
        r = client.chat.completions.create(
            model=cfg.vultr_inference_model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_text},
            ],
            temperature=0.1,
            max_completion_tokens=max_tokens,
            response_format={"type": "json_object"},
        )
        return json.loads(r.choices[0].message.content or "{}")
    except ImportError:
        url = cfg.vultr_inference_base_url.rstrip("/") + "/chat/completions"
        resp = httpx.post(
            url,
            headers={
                "Authorization": f"Bearer {cfg.vultr_inference_api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": cfg.vultr_inference_model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_text},
                ],
                "temperature": 0.1,
                "max_tokens": max_tokens,
                "response_format": {"type": "json_object"},
            },
            timeout=40.0,
        )
        resp.raise_for_status()
        data = resp.json()
        content = data.get("choices", [{}])[0].get("message", {}).get("content", "{}")
        return json.loads(content or "{}")


def diagnose(evidence: dict, report: dict) -> dict | None:
    """Enriches deterministic website QA findings with plain-English explanations & code fixes."""
    system = (
        "You are TestForge AI, a senior full-stack web QA engineer and code doctor running on Vultr. "
        "Analyze ONLY the supplied deterministic browser evidence. "
        "Do not invent issues, remove observations, change severity, change evidence, or claim tests passed without evidence. "
        "Return a JSON object with: "
        "1) 'summary': a clear, friendly 2-sentence executive summary for a first-time user. "
        "2) 'plain_english_summary': an easy-to-understand explanation of how the site performed and what matters most. "
        "3) 'findings': a list in the EXACT same order as deterministic_report.findings, where each item has "
        "'description' (clear explanation), 'recommendation' (step-by-step fix), 'plain_english' (jargon-free impact), "
        "and 'code_fix' (concrete copy-pasteable code snippet to fix the issue in JS/HTML/backend). "
        "If evidence is inconclusive, say so explicitly."
    )
    return _call_vultr_llm(system, {"evidence": evidence, "deterministic_report": report}, max_tokens=2000)


def fix_code_with_ai(filename: str, language: str, source_code: str, sandbox_run: dict) -> dict | None:
    """Uses Vultr Serverless Inference to repair broken source code based on real sandbox stderr."""
    system = (
        "You are Omni-Tester Code Doctor running on Vultr Serverless Inference inside a Blast-Radius-Zero architecture. "
        "You receive a broken source file and its real execution output (stdout, stderr, exit_code) from an isolated sandbox. "
        "Fix all syntax, runtime, logic, and safety bugs in the file while preserving its intended behavior. "
        "Return strict JSON with keys: "
        "'plain_english_summary' (friendly explanation of what was wrong and how you fixed it), "
        "'fixed_code' (the complete, runnable fixed file contents with no truncation), "
        "'issues_fixed' (list of objects with 'line', 'severity', 'title', 'why_it_happened', 'how_it_was_fixed')."
    )
    return _call_vultr_llm(
        system,
        {
            "filename": filename,
            "language": language,
            "source_code": source_code[:16000],
            "initial_sandbox_execution": sandbox_run,
        },
        max_tokens=2400,
    )
