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

## Tier 5 — deploy to Azure: the backend and the database

Everything above runs on a laptop. This tier puts the same image in Azure.

> **What the "backend" is today.** A **batch processor**, not a web service. It reads
> an inbox, writes a submission and exits. The right Azure primitive for that is a
> **Container Apps Job**, not a Container App with ingress — a job runs to completion,
> on a schedule or on demand, and costs nothing while idle. When the HTTP API is
> built, the *same image* gains an ingress and becomes a Container App; nothing below
> is thrown away. That change is described in step 9.

### What gets created

| Azure resource | Why | Demo SKU |
|---|---|---|
| Resource group | one blast radius | — |
| Azure Container Registry | somewhere to push the image | Basic |
| Azure Database for PostgreSQL, Flexible Server | runs, records, decisions | Burstable **B1ms** |
| Storage account + container | attachment bytes | Standard_LRS |
| Container Apps environment | where the job runs | Consumption |
| Container Apps **Job** | the backend | 0.5 vCPU / 1 GiB |

Roughly **USD 15–25/month** if left running; the job itself is billed per second of
execution. The database is the only thing that costs money while idle — stop it
between demos with `az postgres flexible-server stop --name $PG --resource-group $RG`.

### 0. Prerequisites

```bash
az login
az account set --subscription "<your subscription>"
az extension add --name containerapp --upgrade

RG=shipdoc-rg
LOC=southeastasia          # the region nearest your judges/users
ACR=shipdocacr$RANDOM      # globally unique, lowercase, no dashes
PG=shipdoc-db-$RANDOM
STG=shipdocstore$RANDOM
PGPASS='<a strong password>'

az group create --name $RG --location $LOC
```

### 1. The database

Full detail, SSL and firewall notes are in **Tier 4a**. The short version:

```bash
az postgres flexible-server create \
  --resource-group $RG --name $PG --location $LOC \
  --tier Burstable --sku-name Standard_B1ms --version 16 \
  --database-name shipdoc \
  --admin-user shipdocadmin --admin-password "$PGPASS" \
  --public-access 0.0.0.0
```

`--public-access 0.0.0.0` is the **"allow other Azure services"** rule, not public
internet. It is a demo convenience; production wants a private endpoint.

### 2. Blob storage for attachment bytes

```bash
az storage account create --name $STG --resource-group $RG \
  --location $LOC --sku Standard_LRS --min-tls-version TLS1_2
az storage container create --name shipdoc-attachments --account-name $STG
```

Keep the container **private**. The database stores the blob URL; a short-lived SAS
token is minted when a reviewer opens a document. A container with public read on it
is a customer's commercial documents on the open internet.

### 3. Build and push the image

The `Dockerfile` at the repo root is what you deploy. It carries **no secrets**:
`.dockerignore` excludes `.env`, and `infra/dotenv.py` lets a real environment
variable win even if one were somehow baked in.

```bash
az acr create --resource-group $RG --name $ACR --sku Basic --admin-enabled true
az acr build --registry $ACR --image shipdoc:v1 .    # builds in Azure; no local Docker needed
```

> **Build for `linux/amd64`.** Building locally on Apple Silicon without
> `--platform linux/amd64` produces an image that fails to start with
> `exec format error` — a message that says nothing about architecture.

### 4. The Container Apps environment and the job

```bash
az containerapp env create --name shipdoc-env --resource-group $RG --location $LOC

ACR_SERVER=$(az acr show -n $ACR --query loginServer -o tsv)
ACR_PASS=$(az acr credential show -n $ACR --query "passwords[0].value" -o tsv)

az containerapp job create \
  --name shipdoc-run --resource-group $RG --environment shipdoc-env \
  --image $ACR_SERVER/shipdoc:v1 \
  --registry-server $ACR_SERVER --registry-username $ACR --registry-password "$ACR_PASS" \
  --trigger-type Manual --replica-timeout 1800 --replica-retry-limit 1 \
  --cpu 0.5 --memory 1.0Gi \
  --secrets db-url="postgresql+psycopg://shipdocadmin:$PGPASS@$PG.postgres.database.azure.com:5432/shipdoc?sslmode=require" \
            deepseek-key="$DEEPSEEK_API_KEY" \
  --env-vars DATABASE_URL=secretref:db-url DEEPSEEK_API_KEY=secretref:deepseek-key \
  --command shipdoc --args run,--quiet
```

**Secrets go in `--secrets` and are referenced with `secretref:`, never passed
directly in `--env-vars`.** A value passed directly is visible in
`az containerapp job show`, in the portal, and in shell history.

For a nightly run rather than manual:

```bash
--trigger-type Schedule --cron-expression "0 2 * * *"
```

### 5. Migrate and seed — one-off job executions

The schema is owned by Alembic, not by the app. Run it from the **same image**, so
the migration cannot drift from the code that reads it:

```bash
az containerapp job start --name shipdoc-run --resource-group $RG \
  --command alembic --args upgrade,head

az containerapp job start --name shipdoc-run --resource-group $RG \
  --command shipdoc --args db,seed
```

Seeding is **idempotent** — every write is keyed on the natural key, so running it
twice changes nothing. Check with `shipdoc db counts` before and after.

### 6. Run it, and confirm it landed

```bash
az containerapp job start --name shipdoc-run --resource-group $RG
az containerapp job execution list --name shipdoc-run --resource-group $RG -o table
az containerapp logs show --name shipdoc-run --resource-group $RG --type console --follow

az containerapp job start --name shipdoc-run --resource-group $RG \
  --command shipdoc --args db,check
# expect: runs=1  records=520  comparisons=798  submissions=1
```

> ### ⚠️ The firewall is the single most common reason a deployed job cannot reach the DB
>
> A Container App's **outbound** IP is not the one shown in the portal overview, and
> it changes when the app scales or is redeployed. The symptom is a hang and then a
> timeout — never a clear "denied". `--public-access 0.0.0.0` in step 1 covers it for
> a demo. For production use a private endpoint or VNet integration; if you must keep
> an allow-list, pin egress with a NAT gateway so the IP stops moving.

### 7. Which AI model in the cloud

The image ships the committed LLM cache, so **it reproduces the published score with
no API key and no outbound network.** That is the default, and it is free.

To use a hosted model, change two config values and supply the key as a secret:

```yaml
# config/pipeline.yaml
llm:
  provider: deepseek        # deepseek | openai | together | groq | ollama | none
  model: deepseek-chat
```

Measured trade-off on this corpus: DeepSeek costs **0.058 of final score** against
local qwen (0.9277 vs 0.9858) while needing no GPU and costing cents. The table is in
[README.md](README.md); the analysis, including a tempting explanation that was
tested and falsified, is in [HANDOVER.md](HANDOVER.md).

Running Ollama in Azure would need a GPU SKU and is rarely worth it. Ollama's real
role is the **offline / air-gapped** deployment, not this one.

### 8. Verified, not assumed

The image was built and run before this guide was written:

```
docker build -t shipdoc:local .              -> succeeds
docker run --rm shipdoc:local doctor --fast  -> RESULT: PASS - shipdoc is ready

docker run --name r shipdoc:local run --quiet
docker cp r:/app/output/submission.json .
  sha256, Linux container : 7ff39d877aef07c862722767fcac44f7da550f08376477e5d54f03ae0eb81195
  sha256, Windows host    : 7ff39d877aef07c862722767fcac44f7da550f08376477e5d54f03ae0eb81195
```

**Byte-identical across operating systems.** Not a coincidence: artifacts are written
with `newline="\n"` pinned precisely so a Linux container and a Windows laptop
publish the same hash. Before that fix they did not, and the discrepancy would have
surfaced during judging rather than here.

> **Mounting a host volume onto `output/`?** The container runs as uid **10001**
> (non-root, deliberately). A host directory owned by another user gives
> `Permission denied` on the temp file. Either `chown` it to 10001, run with
> `--user "$(id -u)"`, or better — read results from the database instead of a file.

### 9. When the HTTP API lands

Nothing here is wasted. The API is the same image with a different entrypoint:

```bash
az containerapp create --name shipdoc-api --resource-group $RG \
  --environment shipdoc-env --image $ACR_SERVER/shipdoc:v1 \
  --ingress external --target-port 8000 \
  --min-replicas 1 --max-replicas 3 \
  --secrets db-url="..." --env-vars DATABASE_URL=secretref:db-url
```

The job stays, for batch re-processing. The API reads the same database through the
same narrow repository interface (`src/shipdoc/adapters/db/repository.py`) — which is
why it can be a thin translation layer rather than a second place where the rules
live.

---

## Tier 6 — the API and the reviewer UI, deployed split

Phase 14. **The frontend and the backend deploy separately and talk only over HTTP.**
No shared process, no shared filesystem, no server-side rendering of our data.

```
Azure Static Web Apps          Azure Container Apps        Azure PostgreSQL
  ui/  (built SPA)   ──HTTP──►  shipdoc serve  ──────────►  Flexible Server
  free tier                      1 replica min               Burstable B1ms
```

### 6a. Run both halves locally first

Two origins on one machine, which is the real thing in miniature — it exercises CORS
and preflight exactly as the cloud does.

```powershell
# terminal 1 — the API on :8000
$env:DATABASE_URL="sqlite:///output/shipdoc.db"
$env:DEMO_PASSCODE="averis2026"
$env:CORS_ORIGINS="http://localhost:5173"
python -m shipdoc db seed
python -m shipdoc                       # a run, so there is something to review
python -m uvicorn shipdoc.adapters.api.app:app --port 8000

# terminal 2 — the UI on :5173
cd ui
npm install
Copy-Item .env.example .env             # VITE_API_BASE_URL=http://localhost:8000
npm run dev
```

Open <http://localhost:5173>. Set your **name** and the **passcode** from the button
in the top right — reads work without either, writes need both.

### 6b. Deploy the backend

The image from Tier 5 already serves the API; `serve` is the only difference.

```bash
az containerapp create \
  --name shipdoc-api --resource-group $RG --environment shipdoc-env \
  --image $ACR_SERVER/shipdoc:v1 \
  --registry-server $ACR_SERVER --registry-username $ACR --registry-password "$ACR_PASS" \
  --ingress external --target-port 8000 \
  --min-replicas 1 --max-replicas 3 \
  --cpu 1.0 --memory 2.0Gi \
  --secrets db-url="postgresql+psycopg://...?sslmode=require" \
            deepseek-key="$DEEPSEEK_API_KEY" \
            demo-code="$DEMO_PASSCODE" \
  --env-vars DATABASE_URL=secretref:db-url \
             DEEPSEEK_API_KEY=secretref:deepseek-key \
             DEMO_PASSCODE=secretref:demo-code \
             CORS_ORIGINS="https://<your-swa>.azurestaticapps.net" \
             SHIPDOC_ROOT=/app \
  --command /usr/local/bin/docker-entrypoint.sh --args serve

API_URL=https://$(az containerapp show -n shipdoc-api -g $RG \
  --query properties.configuration.ingress.fqdn -o tsv)
```

> **`--min-replicas 1`, not 0.** Scale-to-zero saves pennies and costs you the demo:
> the first judge to click waits ~20 seconds for a cold start and assumes it is
> broken. The UI shows a loading state for exactly this reason, but do not rely on it.

> **`SHIPDOC_ROOT=/app`.** The API looks for `config/`, `dataset/` and `cache/`
> relative to this. Without it, a pip-installed package resolves paths inside
> site-packages, `/api/health` reports `provider: null`, and the cause looks like
> anything except a path. This was found by running the image, not by reading it.

### 6c. Deploy the frontend

The API URL is **build-time** config, so the backend must exist first.

```bash
cd ui
echo "VITE_API_BASE_URL=$API_URL" > .env.production
npm ci && npm run build

az staticwebapp create --name shipdoc-ui --resource-group $RG \
  --location eastasia --sku Free
az staticwebapp deploy --name shipdoc-ui --resource-group $RG \
  --source dist --env production
```

Then **go back and set `CORS_ORIGINS` on the API to the Static Web App's real
origin** — it is not known until the app is created:

```bash
SWA_URL=https://$(az staticwebapp show -n shipdoc-ui -g $RG --query defaultHostname -o tsv)
az containerapp update -n shipdoc-api -g $RG \
  --set-env-vars CORS_ORIGINS="$SWA_URL"
```

### 6d. Five things that break a split deployment

Each of these was handled explicitly; each is worth re-checking after any change.

| # | Trap | How it presents | What was done |
|---|---|---|---|
| 1 | **CORS origin** | every request blocked | exact origins from `CORS_ORIGINS`, never `*`. A wildcard is rejected by browsers once custom headers are involved, and invites anyone's page to drive the API |
| 2 | **Preflight on the passcode header** | **reads work, writes fail** — looks exactly like a backend bug and is not | `X-Demo-Passcode` and `OPTIONS` are allowed explicitly; `test_cors_allows_the_passcode_header_and_options` asserts it |
| 3 | **Cookies for auth** | works on your laptop, fails in incognito and on Safari | there are none. Header-based only; a cookie across two Azure domains is third-party and blocked |
| 4 | **Hardcoded API hostname** | one origin works, the other 404s | `VITE_API_BASE_URL` only; a build with it unset says so instead of silently calling a relative path |
| 5 | **The source viewer crosses the origin too** | the app works, then a PDF will not render | the API serves the extracted text *and* proxies the raw bytes with an explicit `Content-Type`; both were tested cross-origin, `.txt` and `.pdf` |

### 6e. Demo safety

- **The 520-record demo runs entirely from the committed cache** — no model call, no
  API key, nothing that can rate-limit mid-judging.
- **Reads are open; writes need the passcode** on the slide. With no passcode set the
  API is read-only rather than wide open — failing closed is the only safe default
  for something with a public URL.
- **Reset demo** (dashboard) restores the seeded state, so nobody can permanently
  break the link. It clears decisions and un-decides proposals; it leaves the run
  itself alone, because re-running to recover would take minutes.
- **Every failure path is a readable message.** A stack trace in a response body is a
  bad demo and an information leak.

### 6f. Check it the way a judge will

```bash
curl -s $API_URL/api/health | jq
```

Then, **in an incognito window on a phone**:

1. open the Static Web App URL — the dashboard fills in
2. Inbox → filter by status → the URL changes → copy it → open in a new tab: same view
3. open a record with a defect → click a value → the source opens at the highlighted line
4. enter the passcode → confirm a field → the status changes with no reload
5. reload the page → the change is still there

If step 4 fails but everything else works, it is trap #2. Check the preflight before
changing anything else:

```bash
curl -s -i -X OPTIONS $API_URL/api/records/email_013/decisions \
  -H "Origin: $SWA_URL" -H "Access-Control-Request-Method: POST" \
  -H "Access-Control-Request-Headers: content-type,x-demo-passcode" \
  | grep -i access-control
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

| | T1 | +OCR | +LLM | +hosted | +DB | +Azure |
|---|---|---|---|---|---|---|
| Read `.txt` `.pdf` `.xlsx` `.docx` | yes | yes | yes | yes | yes | yes |
| Compare all 7 fields | yes | yes | yes | yes | yes | yes |
| Reproduce the published score | yes | yes | yes | yes | yes | yes |
| Classify emails | keyword rules | keyword rules | local model | hosted model | — | — |
| Read the 3 scanned PDFs | no — `NEEDS_REVIEW` | yes | yes | yes | — | — |
| Score against the server | needs Tier 3b | | | | | |
| Runs with **no outbound network** | yes | yes | yes | no | — | no |
| Needs a GPU | no | no | yes* | no | — | no |
| Durable runs, review history | no | no | no | no | yes | yes |
| Runs unattended / on a schedule | no | no | no | no | no | yes |

\* Ollama runs on CPU, slowly. A GPU is what makes Tier 3 practical for 520 emails.

**The committed LLM cache is why every tier reproduces the published score** — even
Tier 1 with no model, no key and no network. The cache holds this system's own
answers from both providers, keyed by model name.

**Most people need Tier 1.** Tier 4 and 5 exist because the brief asks for cloud and
a database; they change nothing about the verification result.
