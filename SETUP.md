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

## Tier 3c — a hosted model instead of Ollama (optional)

Phase 12. DeepSeek's API is OpenAI-compatible, so one client covers DeepSeek, OpenAI,
Together and Groq — changing provider is a config change, not a code change.

```powershell
pip install -e ".[hosted]"
Copy-Item .env.example .env          # then put your key in it
```

`config/pipeline.yaml`:

```yaml
llm:
  provider: deepseek          # deepseek | openai | together | groq | ollama | none
  model: deepseek-chat        # NOT deepseek-reasoner - see below
  prompt_version: v1
```

The key is read from the **environment only** (`DEEPSEEK_API_KEY`). It is never read
from config, never written to the cache, the run summary, a log line or the database,
and `tests/property/test_no_secret_leak.py` greps the whole tree and the committed
cache for key-shaped strings.

**`deepseek-chat`, not `deepseek-reasoner`.** Every question this system asks a model
is closed — "return exactly one of these five strings". There is nothing to reason
about, so a reasoning model costs more and is slower for no benefit.

**No key set?** The system says so in one readable line and falls back to
deterministic keyword rules. That is a supported mode, not a crash.

**Ollama is not deprecated.** `provider: ollama` remains fully supported and is the
offline / air-gapped option — a freight operator handling commercial documents is
exactly the customer who asks for "no outbound network", and that is a real property
of this system rather than a limitation.

---

## Tier 4 — Azure: the database and blob storage (optional)

Phase 13. **Everything above works with no database.** This tier adds durable
storage, the review history, and what the API and dashboard will read from.

### 4a. Azure Database for PostgreSQL, Flexible Server

**Burstable B1ms** is enough for a demo — 1 vCPU, 2 GiB, and it is the cheapest tier
that supports everything used here.

```bash
az postgres flexible-server create   --resource-group shipdoc-rg --name shipdoc-db   --tier Burstable --sku-name Standard_B1ms   --version 16 --database-name shipdoc   --admin-user shipdocadmin --admin-password '<a strong password>'
```

**SSL is required** — Azure rejects an unencrypted connection, so `sslmode=require`
is not optional:

```
DATABASE_URL=postgresql+psycopg://shipdocadmin:<password>@shipdoc-db.postgres.database.azure.com:5432/shipdoc?sslmode=require
```

Environment variable only. Never commit it: it contains the password, and
`test_no_secret_leak.py` fails the build if a password-bearing URL appears in the tree.

> ### ⚠️ Firewall — the single most common reason a deployed app cannot reach the DB
>
> A Container App's **outbound** IP is not the one you see in the portal's overview,
> and it changes when the app scales or is redeployed. Symptoms are a hang followed
> by a timeout, never a clear "denied".
>
> ```bash
> # allow Azure services (simplest; still not public)
> az postgres flexible-server firewall-rule create >   --resource-group shipdoc-rg --name shipdoc-db >   --rule-name allow-azure --start-ip-address 0.0.0.0 --end-ip-address 0.0.0.0
>
> # and your own machine, for migrations and seeding
> az postgres flexible-server firewall-rule create >   --resource-group shipdoc-rg --name shipdoc-db >   --rule-name my-laptop --start-ip-address <your ip> --end-ip-address <your ip>
> ```
>
> For production prefer a **private endpoint** or VNet integration over an IP
> allow-list; the allow-list is a demo convenience.

### 4b. Migrate and seed

The schema lives in version control. `create_all` is used only by the SQLite test
repository — PostgreSQL is owned by Alembic, because a schema two mechanisms can
create is a schema that differs between environments.

```powershell
pip install -e ".[db]"
alembic upgrade head          # creates 12 tables and the two partial indexes
python -m shipdoc db check    # prints the row counts
python -m shipdoc db seed     # loads 520 emails + 250 attachment records
```

**Seeding is idempotent.** Every write is keyed on the natural key (`email_id`,
`(email_id, filename)`), so running it twice changes nothing. Verify it yourself:

```powershell
python -m shipdoc db counts
python -m shipdoc db seed
python -m shipdoc db counts   # identical
```

### 4c. Azure Blob Storage for attachment bytes

The database holds attachment **metadata and a blob URL**. The bytes live in Blob
Storage — a 520-document corpus fits in a database, the next one will not, and a
bytes column is the hardest thing to migrate out of later.

```bash
az storage account create --name shipdocstore --resource-group shipdoc-rg --sku Standard_LRS
az storage container create --name shipdoc-attachments --account-name shipdocstore
```

```
AZURE_STORAGE_CONNECTION_STRING=DefaultEndpointsProtocol=https;AccountName=...
AZURE_BLOB_CONTAINER=shipdoc-attachments
```

**SAS URLs, never public blobs.** The container stays private; a short-lived SAS
token is issued when a reviewer actually opens a document. A container with public
read on it is a shipping customer's commercial documents on the open internet.

Without a storage account configured, seeding still records the metadata (name, size,
sha256, detected type) and skips the upload — so a database and no storage account
gives you a working, inspectable dataset rather than an error.

### 4d. Running with the database

```powershell
python -m shipdoc            # writes files AND one immutable run to the database
```

A run inserts one `runs` row, 520 `records`, their `comparisons` and `stage_events`,
and one `submissions` row. **Runs are immutable** — re-processing creates a new
`run_id` rather than overwriting, so "what did we say on the 20th?" keeps an answer.

If the database is unreachable the run still completes and writes its files; the
failure is reported on stderr and the files remain the source of truth. A database
outage must never take down a batch.

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
