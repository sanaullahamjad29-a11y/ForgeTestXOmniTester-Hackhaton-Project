# TestForge × Omni-Tester AI (v2.0) — Blast Radius Zero on Vultr

**Built for the [Vultr: Agent Rush Hackathon](https://lablab.build/ai-hackathons/vultr-hackathon) (`Challenge 01: Blast Radius Zero — Pattern A + Pattern B`)**

TestForge × Omni-Tester AI is a containment-first web QA & self-healing code execution platform running on **Vultr Cloud Compute** and **Vultr Serverless Inference** (`https://api.vultrinference.com/v1`). Every browser navigation and every untrusted code execution happens inside an isolated, resource-capped, secret-stripped sandbox and returns a verifiable **SHA-256 Containment Receipt**.

---

## Key Capabilities & Hackathon Alignment

| Capability | Challenge Pattern | What It Does |
| :--- | :--- | :--- |
| **First-Time-Friendly Website QA Sweep** | **Pattern B · Sandboxed Browser Use** | Crawls multi-page websites inside headless Playwright, blocks SSRF/private IPs via DNS/IP validation, tests safe buttons & explicit user workflows, and returns a plain-English **Executive Health Guide (`A+` to `F`)** with copyable code fixes for every finding. |
| **Self-Healing Code Sandbox Fixer** | **Pattern A · Sandboxed Code Execution** | Runs broken `.py`, `.js`, `.jsx`, and `.json` files inside a secret-stripped, time-capped ephemeral sandbox, captures real `stderr` tracebacks, repairs syntax/runtime bugs via **Vultr Serverless Inference** + deterministic AST healers, and re-runs the fixed code in a fresh throwaway sandbox to prove `exit_code == 0`. |
| **Blast Radius Zero Containment Lab** | **Mandatory Containment Moment** | Interactive attack & containment verifier demonstrating real-time blocking of localhost SSRF (`http://localhost:8000`), cloud metadata probes (`169.254.169.254`), API key exfiltration (`VULTR_INFERENCE_API_KEY`), and host filesystem reads (`/etc/passwd`). |

---

## Architecture & Containment Guarantees

1. **Process & Filesystem Isolation**:
   - Browser sweeps run in isolated Playwright contexts with a request-level route guard (`page.route("**/*", guard)`).
   - Code execution runs with `python3 -I` (isolated mode) inside an ephemeral `tempfile.TemporaryDirectory` (`--rm`, `--read-only`, `--cap-drop=ALL`, `--security-opt=no-new-privileges` in Docker).
2. **Strict Secret Hygiene**:
   - Subprocesses receive a sanitized environment whitelist (`PATH`, `HOME`, `TMPDIR`, `PYTHONDONTWRITEBYTECODE=1`)—`VULTR_INFERENCE_API_KEY` and host credentials are never mounted or exposed inside the sandbox.
3. **Resource Caps & Lifecycle Discipline**:
   - Every browser crawl enforces `MAX_RUN_SECONDS` and page limits (`quick=3`, `standard=12`, `deep=30`).
   - Every code sandbox execution enforces `CODE_SANDBOX_TIMEOUT_SECONDS` (default `6s`) and destroys the temporary directory immediately upon exit.
4. **Cryptographic SHA-256 Receipts**:
   - Every Website QA report and Code Fixer run produces a `containment_receipt` (`vultr-brz-<hash>`) with the SHA-256 digest of the canonical evidence and the exact isolation flags enforced.

---

## Quick Start Guide (Local & Vultr Cloud Compute VM)

### Option 1: One-Command Docker Compose (Recommended for Vultr VM)

```bash
# 1. Copy environment variables and add your Vultr Serverless Inference API key
cp backend/.env.example backend/.env

# 2. Launch hardened backend + frontend containers
docker compose up --build -d
```

- **Web UI**: `http://<YOUR_VULTR_VM_IP>:5173`
- **FastAPI Docs**: `http://<YOUR_VULTR_VM_IP>:8000/docs`

### Option 2: Manual Development Setup (Backend + Frontend)

#### Step 1 — Start the FastAPI Backend (`port 8000`)

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
playwright install --with-deps chromium

# Configure Vultr Serverless Inference (optional; deterministic fallback works without a key)
cp .env.example .env

# Run the unit test suite (19 tests covering report scoring, SSRF security, workflows, and code fixer)
pytest -v

# Start the API server
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

#### Step 2 — Start the React + Vite Frontend (`port 5173`)

```bash
cd frontend
npm install
npm run dev
```

Open `http://localhost:5173`. Vite automatically proxies `/api/*` requests to `http://127.0.0.1:8000`, or you can click **API Config** in the top header to point to any remote Vultr VM IP.
