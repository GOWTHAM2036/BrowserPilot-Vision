# BrowserPilot Vision — Hackathon Submission Summary

*This document contains editable submission copy tailored for hackathon submission portals (Devpost, GitHub, Google AI Hackathon forms). All statements reflect the actual, verified codebase.*

---

## 1. Short Project Description (~100 words)

**BrowserPilot Vision** is a local-first, autonomous AI browser automation agent designed from scratch to run on consumer laptops without cloud LLM APIs. The user inputs a natural-language task through a clean Gradio interface. A local open-weight model (`gemma3:4b` via Ollama) evaluates compact, token-bounded semantic page observations, decides structured browser actions, and executes them through Playwright on a controlled single-tab session. Crucially, tasks are never declared successful based on LLM claims alone; an observable evidence engine independently verifies DOM changes against content keywords. The system enforces strict hostname whitelisting, prohibited scheme guards, consequential action halts, and credential masking.

---

## 2. Problem Addressed

Traditional web automation relies on rigid, easily broken CSS/XPath selectors that require constant engineering maintenance. While cloud-based AI browser agents have emerged, they introduce three critical liabilities:
1. **Severe Privacy & Data Leakage:** Transmitting live DOM trees, session cookies, personal credentials, and browser screenshots to external cloud APIs exposes users to data breaches and third-party tracking.
2. **High Recurring API Costs:** Large DOM contexts quickly exhaust cloud token limits, making continuous browser automation cost-prohibitive.
3. **Hallucinated "Success":** Cloud LLMs frequently claim a task succeeded (such as declaring a product was purchased or added to cart) when the website actually displayed an error banner or remained unchanged.

BrowserPilot Vision solves these problems by performing 100% of reasoning, execution, and verification on the user's local machine.

---

## 3. Main Technical Approach

- **Decoupled Architecture:** A lightweight Gradio UI connects over HTTP to a robust FastAPI backend. FastAPI manages request validation, single-task concurrency control, and non-blocking background worker threads to keep Playwright and LLM synchronous loops from blocking the API.
- **Token-Bounded Semantic Observation:** Rather than passing raw DOM trees (which overflow local context windows), `PageObserver` extracts visible body text bounded to 3,000 characters and indexes interactive elements with accessible roles, names, and parent-card contextual enrichment.
- **Deterministic Action Schemata:** Strict Pydantic v2 schemas reject arbitrary Python/JavaScript/shell injection. Supported actions are strictly limited to `click`, `fill`, `goto`, `scroll`, `wait`, and `finish`.
- **Observable Verification Loop:** When the LLM outputs `finish`, the agent cross-references claimed evidence against actual visible DOM text, filtering out common stopwords to prevent false-positive completions.
- **Multimodal Fallback:** Multimodal vision (screenshot analysis via `gemma3:4b`) is invoked only when DOM text is insufficient, conserving laptop VRAM.

---

## 4. What Is Original About This Project

1. **Independent Evidence Verification:** Unlike typical LLM agents that terminate blindly when the model outputs a finish tag, BrowserPilot Vision independently validates observable DOM state before granting `COMPLETED` status, categorizing unverified finishes as `UNVERIFIED`.
2. **Consumer Hardware Optimization:** Specifically engineered for laptops with 4 GB VRAM (e.g. NVIDIA RTX 3050 Laptop GPU) and 16 GB RAM using a compact 4096-token context window, sequential single-task locking, and bounded 4-step prompt history.
3. **Comprehensive Defense-in-Depth:**
   - Hostname whitelisting (`localhost`, `127.0.0.1` by default).
   - Prohibited URL schemes (`file:`, `javascript:`, `data:`, `blob:`).
   - Automatic closure of unexpected popup tabs.
   - Consequential action guards halting before purchases, deletions, or password fields.
   - Redaction of cookies, bearer tokens, and passwords in both file logs and API responses.

---

## 5. How Open-Source / Local AI Is Central

BrowserPilot Vision is built exclusively around the local open-weights AI ecosystem:
- **Model Engine:** Powered by [Ollama](https://ollama.ai) running local open-weight models:
  - `gemma3:4b` (Google Gemma 3 open-weights multimodal model — default)
  - `qwen3:4b` / `qwen2.5:1.5b-instruct-q4_K_M` (alternative local open models)
- **Zero Cloud Reliance:** No API keys, cloud credits, or internet connection required for core agent operation.
- **Full Transparency:** Execution records are written locally to `data/<task_id>.jsonl` with timestamps, model thoughts, and verification proofs.

---

## 6. Current Limitations

1. **GPU/CPU Layer Splitting:** On 4 GB VRAM GPUs, Windows system display processes consume ~0.8–1.2 GB of VRAM, causing Ollama to split 4B models (~3.5 GB) across GPU and CPU (typically ~56% CPU / 44% GPU). Initial cold model loading takes 15–20 seconds; subsequent steps take 2.5–4.5 seconds.
2. **Single Active Task:** To protect limited system RAM and VRAM, the API enforces a strict single-active-task lock (`4096` token context). Concurrent task requests return `409 Conflict`.
3. **No Automated Bypass of Captchas:** Complex anti-bot challenges or Cloudflare interstitials on external websites are outside the local scope.

---

## 7. Exact Setup and Demo Instructions

### Environment
- **OS:** Windows 11 / 10 (or Linux/macOS with equivalent virtual environment)
- **Python:** 3.10+
- **Local Runtime:** Ollama running `gemma3:4b` (`ollama serve`)

### Quick Setup (PowerShell)
```powershell
cd "C:\Users\B Gowtham Reddy\.vscode\HACKTOBERFEST\browserpilot-vision"
..\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
playwright install chromium
```

### Running the Services
1. **Demo Site (Terminal 1):**
   ```powershell
   ..\.venv\Scripts\python.exe -m demo_site.app
   ```
2. **FastAPI Backend (Terminal 2):**
   ```powershell
   $env:PYTHONPATH="."
   ..\.venv\Scripts\python.exe -m uvicorn app.main:app --port 8000
   ```
3. **Gradio UI (Terminal 3):**
   ```powershell
   $env:PYTHONPATH="."
   ..\.venv\Scripts\python.exe ui.py
   ```
   *Open `http://127.0.0.1:7860` in any web browser.*

### Running Automated Tests
```powershell
$env:PYTHONPATH="."
..\.venv\Scripts\python.exe -m pytest tests/ -v
```
*(All 53 automated tests pass in ~26 seconds).*

### Automated End-to-End Verification
```powershell
$env:PYTHONPATH="."
..\.venv\Scripts\python.exe verify_full_stack_live.py
```
*(Executes end-to-end shopping and cart verification through API in ~17 seconds).*
