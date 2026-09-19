# Setup

Three tiers. **Most people only need Tier 1** — it takes about five minutes and gives
you a working system you can run, test and inspect. Tiers 2 and 3 add optional
capabilities; the system runs without them and tells you what is missing.

Every path below is quoted. If you clone into a directory whose name contains a
space, an unquoted path is the single most common failure on Windows — and it
fails in confusing ways, half-way through the path.

---

## Tier 1 — five minutes, nothing extra

You need **Python 3.12 or newer**. Nothing else.

### PowerShell

```powershell
cd "C:\dev\Shipping-Document-Verification-System"

python -m venv .venv
.\.venv\Scripts\Activate.ps1

python -m pip install --upgrade pip
pip install -e ".[dev]"
```

### bash / Git Bash

```bash
cd "/c/dev/Shipping-Document-Verification-System"

python -m venv .venv
source .venv/Scripts/activate

python -m pip install --upgrade pip
pip install -e ".[dev]"
```

**Correct output** ends with something like:

```
Successfully installed shipdoc-0.6.0 ...
```

Your prompt should now start with `(.venv)`. If it does not, the virtualenv is not
activated and every command below will use the wrong Python.

### Check it works

```powershell
python -m shipdoc doctor
```

**Correct output** — the last line is what matters:

```
shipdoc doctor
  repo: C:\dev\Shipping-Document-Verification-System

  [ok  ] python version           3.13.4
  [ok  ] package imports          shipdoc, shipdoc.pipeline
  [ok  ] corpus                   520 emails, 250 attachments
  [ok  ] config                   7 compared fields defined
  [ok  ] test suite               522 passed in 32s
  [ok  ] pipeline (sample)        10 records processed, submission.json written fresh
  [ok  ] submission schema        every entry has exactly [...]

  optional capabilities
  [--  ] OCR                      tesseract not found — scans -> NEEDS_REVIEW
  [--  ] LLM                      no server at http://localhost:11434 — rules only
  ...
  RESULT: PASS — shipdoc is ready
```

Lines marked `[--  ]` are **optional and expected to be missing** on a fresh machine.
`RESULT: PASS` is the thing to look for.

### Run the tests

```powershell
python -m pytest -q
```

**Correct output:** `522 passed in 32s` (the count may be higher; zero failures is
what matters).

### Run it on the whole corpus

```powershell
python -m shipdoc
```

Takes about 20 seconds with no LLM. Writes four files into `output\`. You are done —
**Tier 1 is a complete, usable system.** See `TESTING.md` for what to do next.

---

## Tier 2 — add OCR

Only needed for three scanned PDFs (`email_512`, `513`, `514`). Without it those
records report `NEEDS_REVIEW / unreadable`, which is the **correct** answer, not a
failure. Add this if you want them read.

```powershell
winget install UB-Mannheim.TesseractOCR
pip install -e ".[ocr,dev]"
```

Close and reopen PowerShell so the new `PATH` takes effect, then:

```powershell
python -m shipdoc doctor --fast
```

**Correct output** — the OCR line changes to:

```
  [ok  ] OCR                      tesseract at C:\Program Files\Tesseract-OCR\tesseract.EXE
```

If it still says `not found`, Tesseract installed but is not on `PATH`. Reopen the
terminal first; if that does not fix it, add `C:\Program Files\Tesseract-OCR` to
`PATH` manually.

---

## Tier 3 — add the LLM and the scoring server

Both are heavy. Skip unless you are working on classification or need a score.

### 3a — Ollama (about 5 GB, slow on a CPU)

```powershell
winget install Ollama.Ollama
ollama pull qwen2.5:7b-instruct
```

The pull is ~4.7 GB and can take 20+ minutes. Verify:

```powershell
ollama list
python -m shipdoc doctor --fast
```

**Correct output:** `[ok  ] LLM   1 model(s) at http://localhost:11434`

Without it, classification falls back to deterministic keyword rules. The system runs
either way and `run_summary.json` records `"degraded": true`.

### 3b — The scoring server

The organisers' Docker bundle goes **outside this repository**, as a sibling:

```
Desktop\
  sdoc-hackathon-bundle\      <- this repo
  sdoc-server\                <- the organiser bundle goes here
```

**Why outside:** that bundle contains `ground_truth.json`, the answer key. Keeping it
out of the repo means it can never be committed, and no glob or recursive read inside
the repo can reach it by accident. The repo must be publishable without it.

```powershell
cd "C:\dev\sdoc-server"
docker compose up --build -d

curl http://localhost:8080/health
```

**Correct output:** `{"status":"ok","emails":520,"scoring_available":true}`

Then, back in the repo:

```powershell
python -m shipdoc --submit --server-url http://localhost:8080
```

---

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `No module named shipdoc` | Package not installed, or the venv is not active | Check your prompt shows `(.venv)`. Then `pip install -e ".[dev]"` from the repo root. **Never** work around this by setting `PYTHONPATH` — that hides the real problem. |
| `python` opens the Microsoft Store | Windows' Python alias, no real Python | Install Python 3.12+ from python.org, or `winget install Python.Python.3.12`. Then `python --version`. |
| `Activate.ps1 cannot be loaded ... execution policy` | PowerShell blocks scripts by default | `Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned`, then reopen PowerShell |
| `doctor` says `corpus  0 emails, 0 attachments` | Running from the wrong directory | `cd` to the repo root — the one containing `pyproject.toml`. `doctor` prints the path it looked in. |
| Paths break, or commands fail with the second half of a folder name | Your clone path contains a space | Quote every path: `cd "C:\Users\Your Name\..."`. The most common Windows failure. |
| `Access is denied` / permission errors on `output\` | OneDrive is syncing, or a file is open in another program | Close anything reading `output\`, pause OneDrive sync, retry |
| `pip install -e .` fails compiling something | Wrong Python, or an old pip | `python --version` must be 3.12+. `python -m pip install --upgrade pip`. Core deps are all pre-built wheels — nothing should need a compiler. |

---

## What you get at each tier

| | Tier 1 | +OCR | +LLM |
|---|---|---|---|
| Read `.txt` `.pdf` `.xlsx` `.docx` | yes | yes | yes |
| Compare all 7 fields | yes | yes | yes |
| Classify emails | keyword rules | keyword rules | model |
| Read the 3 scanned PDFs | no — `NEEDS_REVIEW` | yes | yes |
| Score against the server | needs Tier 3b | | |
