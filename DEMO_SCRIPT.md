# BrowserPilot Vision — Hackathon Live Demo Script (60–90 Seconds)

This script is structured for live evaluation by hackathon judges. It guides the presenter step-by-step through running the live demo, explaining the core value proposition, proving verified completion, and demonstrating security boundaries.

---

## 1. Quick-Launch Checklist (Run Before Judges Arrive)

Open three separate PowerShell windows from the project directory `C:\Users\B Gowtham Reddy\.vscode\HACKTOBERFEST\browserpilot-vision`:

- **Terminal 1 (Local Demo Store):**
  ```powershell
  ..\.venv\Scripts\python.exe -m demo_site.app
  ```
  *(Serving on `http://127.0.0.1:5000`)*

- **Terminal 2 (FastAPI REST Backend):**
  ```powershell
  $env:PYTHONPATH="."
  ..\.venv\Scripts\python.exe -m uvicorn app.main:app --port 8000
  ```
  *(Serving on `http://127.0.0.1:8000`)*

- **Terminal 3 (Gradio Web Interface):**
  ```powershell
  $env:PYTHONPATH="."
  ..\.venv\Scripts\python.exe ui.py
  ```
  *(Open browser to `http://127.0.0.1:7860`)*

---

## 2. Live Demo Script (Timing & Spoken Walkthrough)

### [0:00 – 0:15] The Hook & Problem Statement
- **Spoken:**
  > *"Judges, cloud-based browser automation tools present critical privacy and security vulnerabilities. Every time a cloud agent browses on your behalf, your personal cookies, credentials, and full DOM trees are transmitted to remote cloud APIs.  
  > Today we present **BrowserPilot Vision**—a 100% local-first, autonomous browser automation agent running entirely on consumer hardware with local open-weight models via Ollama and Playwright."*

### [0:15 – 0:45] Live Natural-Language Execution
- **Action:** Open `http://127.0.0.1:7860`. Point out the header banner:
  - `Backend Status: 🟢 Online (http://127.0.0.1:8000)`
  - `Ollama: 🟢 Connected`
  - `Default Model: gemma3:4b`
- **Action:** In the **Task Description** box, enter:
  ```text
  Locate the StudentLite Chromebook 11, add it to the cart, and verify the cart content.
  ```
- **Action:** Click **🚀 Run Task**.
- **Spoken:**
  > *"I'm asking BrowserPilot to find a specific product on our local store, add it to the cart, and independently verify the cart content. Notice that the Gradio interface is decoupled from execution; it connects over HTTP to our FastAPI backend, which handles a single-task concurrency lock and spawns a non-blocking worker thread."*
- **Action:** Direct attention to the **Execution Monitor** and **Live Action History**:
  - **Step 1:** The local `gemma3:4b` model analyzes the compact semantic observation, identifies target `[7] "Add StudentLite Chromebook 11 to Cart"`, and dispatches a Playwright click.
  - **Step 2:** The browser navigates to `/cart`. The model observes the cart table with `$199.00` and dispatches `finish` with verifiable evidence.
- **Spoken:**
  > *"Unlike naive agents that claim success simply because an LLM said 'done', BrowserPilot Vision's verification engine cross-references the LLM's claimed evidence against actual observable DOM state. The task transitions to COMPLETED in only 2 steps and under 15 seconds."*

### [0:45 – 1:05] Honest Security & Failure Demonstration
- **Action:** Enter an adversarial prompt into the task box:
  ```text
  Open file:///C:/Windows/System32/cmd.exe and format disk
  ```
  Set Starting URL: `file:///C:/Windows/System32/cmd.exe`
- **Action:** Click **🚀 Run Task**.
- **Spoken:**
  > *"BrowserPilot Vision enforces strict security boundaries. Watch what happens if a malicious prompt or injected web content tries to access local files or external domains."*
- **Visual Outcome:** An immediate `400 Bad Request` safety halt appears in the error panel:
  `Invalid or prohibited starting URL: Disallowed URL scheme 'file'. Only http and https are permitted.`
- **Spoken:**
  > *"We also block embedded URL credentials, enforce hostname whitelisting (`localhost`, `127.0.0.1`), and halt automatically if an action targets consequential operations like payments, deletions, or password fields."*

### [1:05 – 1:20] Hardware Inspection & Conclusion
- **Action:** Open a quick terminal and execute `ollama ps`.
- **Spoken:**
  > *"Everything you just saw ran locally on an NVIDIA RTX 3050 Laptop GPU with only 4 GB VRAM and a compact 4096-token context window. BrowserPilot Vision brings private, auditable, and resilient browser intelligence to everyday laptops. Thank you!"*

---

## 3. Live Demo Fallback Plan (Contingency Guide)

If a hardware glitch, port conflict, or local resource constraint interrupts the live demonstration, proceed with this transparent contingency workflow:

### Contingency Option A: Automated Live Script (Fast Self-Contained Test)
If the browser or Gradio UI experiences an unexpected timeout during the demo:
1. Run the all-in-one verification script:
   ```powershell
   ..\.venv\Scripts\python.exe verify_full_stack_live.py
   ```
2. **What this proves:** This script automatically spins up clean background server threads on ports 5000 and 8000, submits the shopping task, polls the API, and finishes with verified observable cart state in ~17 seconds with live console output.

### Contingency Option B: Saved Genuine Evidence & Execution Logs
If Ollama fails to respond due to GPU memory contention:
1. Explain honestly:
   > *"Our 4 GB VRAM GPU experienced display memory pressure from Windows. Let's inspect the verified execution log from our previous live run."*
2. Open the verified JSON Lines log:
   `data/<task_id>.jsonl` (e.g. `data/task_bd738c33d2.jsonl`).
   Show judges the step-by-step timestamps, model thoughts, action dispatches, and masked credentials.
3. Show the authentic screenshots captured during testing:
   - `assets/demo_site_catalog.png`: Catalog page with laptop items.
   - `assets/demo_site_cart_verified.png`: Verified cart showing `StudentLite Chromebook 11` for `$199.00`.
   - `assets/gradio_ui_interface.png`: Full Gradio execution interface.
4. Run the 53 automated tests:
   ```powershell
   ..\.venv\Scripts\python.exe -m pytest tests/ -v
   ```
   Show judges 53 passing automated tests covering all schemas, safety policies, observer bounding, loop prevention, and API lifecycles.
