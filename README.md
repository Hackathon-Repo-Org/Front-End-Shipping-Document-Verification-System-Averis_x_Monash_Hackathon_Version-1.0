# ShipDoc Reviewer UI (Frontend)

The web interface for **ShipDoc**, a system that checks a customer's **Shipping Instruction (SI)** against the carrier's **draft Bill of Lading (BL)** and flags any differences before the ship sails.

This repository holds the **frontend only**: a React website that reviewers use to browse results, check evidence and record decisions. All the verification logic, the database and the AI live in the backend repository:

**Backend:** <https://github.com/Hackathon-Repo-Org/Shipping-Document-Verification-System-Averis_x_Monash_Hackathon>

Built for the **Averis x Monash Hackathon 2026**.

---

## Live demo

The system is deployed on **AWS** and ready to use. Nothing needs to be installed to try it.

| | Link |
|---|---|
| Website | <https://shipdoc.duckdns.org> |
| API health check | <https://shipdoc.duckdns.org/api/health> |

- **Reading is open to everyone.** Browse the dashboard, inbox, records and evaluation freely.
- **Review actions need a passcode.** To confirm, correct or approve something, open **Reviewer** in the page header, type any name in **Your name**, enter the passcode below in **Demo passcode**, and click **Save**.

```
averis2026
```

The "Run locally" section below is only needed if you want to run your own copy.

---

## What you can do in the app

| Page | Address | What it is for |
|---|---|---|
| Dashboard | `/` | Totals by status and email category, how many decisions the AI made, and details of the current run |
| Inbox | `/inbox` | All 520 emails with their category and status. Filter and search; the filters are kept in the address bar, so a filtered view can be shared as a link |
| Email detail | `/records/:emailId` | The seven compared fields (shipper, consignee, notify party, port of loading, port of discharge, container count, gross weight) side by side for the SI and the BL. Click a value to open the source document at that line |
| Review queue | `/queue` | Emails the system sent to a human, with the reason (for example a missing attachment or an unreadable file) and the evidence. Confirm or correct them here |
| Label proposals | `/proposals` | Field labels the AI suggested learning. A reviewer approves or rejects each one, and the decision is signed with their name |
| Evaluation | `/evaluation` | The scoring axes and the measured comparison of the two AI models (local Qwen vs hosted DeepSeek) |
| Try it yourself | `/try` | Paste your own shipping instruction and draft bill of lading and run the real verification engine on them. Nothing is stored |

---

## How it fits together

```
Browser
   |
   v
https://shipdoc.duckdns.org   (AWS EC2 server)
   |-- Caddy web server
   |      serves this website (the built files in dist/)
   |      forwards every /api/* request to the backend
   |
   |-- Backend API (FastAPI + verification engine)   <- backend repository
          |
          v
       PostgreSQL database (AWS RDS)
```

The website and the API share one address, so the browser never has to call a different domain.

---

## Tech stack

| Part | Used |
|---|---|
| Framework | React 18 + TypeScript |
| Build tool | Vite 5 |
| Routing | React Router 6 |
| Styling | Plain CSS (`src/styles.css`) and Bootstrap Icons |
| Talking to the backend | `fetch`, all in one file: `src/lib/api.ts` |

---

## Project structure

```
src/
  main.tsx              App entry point and the list of pages (routes)
  styles.css            All styling
  lib/
    api.ts              The only file that calls the backend
    vocab.tsx           Labels and colours for categories and statuses
  components/
    Shell.tsx           Page layout, navigation bar and reviewer sign-in
    Evidence.tsx        Source-document viewer with the highlighted line
    DecisionBar.tsx     Confirm / correct / override buttons
  pages/
    Dashboard.tsx  Inbox.tsx  Detail.tsx  Queue.tsx
    Proposals.tsx  Evaluation.tsx  TryIt.tsx
index.html
vite.config.ts
.env.example            Example of the one setting this app needs
```

---

## Configuration

The app needs **one setting**: the address of the backend API.

| Setting | Example | Meaning |
|---|---|---|
| `VITE_API_BASE_URL` | `http://localhost:8000` | Where the backend API is running |

This value is **built into the website when you run the build**. If you change it, build again. If it is missing, every page shows "This build has no API address".

---

## Run locally

Use this if you want your own copy instead of the live demo. You run the backend and the frontend side by side on your computer.

### What you need

| Tool | Version | Check with |
|---|---|---|
| Git | any recent | `git --version` |
| Python | 3.12 or newer | `python --version` |
| Node.js | 20 (18 or newer works) | `node --version` |

The commands below are for **Windows PowerShell**. On macOS or Linux, use `source .venv/bin/activate` instead of `.\.venv\Scripts\Activate.ps1`, and `export NAME=value` instead of `$env:NAME="value"`.

### Step 1: start the backend (first terminal)

```powershell
git clone https://github.com/Hackathon-Repo-Org/Shipping-Document-Verification-System-Averis_x_Monash_Hackathon.git backend
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev,db,api]"

# local settings: a SQLite file instead of PostgreSQL, and your own passcode
$env:DATABASE_URL="sqlite:///output/shipdoc.db"
$env:DEMO_PASSCODE="choose-any-passcode"
$env:CORS_ORIGINS="http://localhost:5173"

python -m shipdoc db seed      # load the 520 emails into the database
python -m shipdoc              # run the verification engine on all of them
python -m uvicorn shipdoc.adapters.api.app:app --port 8000
```

Leave this terminal open. Check it works by opening <http://localhost:8000/api/health>. You should see `"status":"ok"` and `"records":520`.

No API key is needed: the answers the AI gave for all 520 dataset emails are saved in the backend repository. More setup options (OCR for scanned PDFs, a local AI model, PostgreSQL) are in the "Optional add-ons" section of the [backend README](https://github.com/Hackathon-Repo-Org/Shipping-Document-Verification-System-Averis_x_Monash_Hackathon#optional-add-ons).

### Step 2: start the frontend (second terminal)

```powershell
git clone https://github.com/Hackathon-Repo-Org/Front-End-Shipping-Document-Verification-System-Averis_x_Monash_Hackathon_Version-1.0.git frontend
cd frontend
copy .env.example .env.local     # contains VITE_API_BASE_URL=http://localhost:8000
npm install
npm run dev
```

Open <http://localhost:5173>. The dashboard should fill with numbers.

To sign in as a reviewer locally, use any name and the passcode you set in `DEMO_PASSCODE` in Step 1.

### Available scripts

| Command | What it does |
|---|---|
| `npm run dev` | Starts the development server at <http://localhost:5173> with live reload |
| `npm run typecheck` | Checks the TypeScript code for errors without building |
| `npm run build` | Type-checks, then builds the production website into `dist/` |
| `npm run preview` | Serves the built `dist/` folder at <http://localhost:4173> to check it before deploying |

---

## Testing

### 1. Automatic checks (run before every push)

```powershell
npm run typecheck
npm run build
```

Both must finish with no errors. `npm run build` is exactly what the cloud server runs, so if it fails on your computer, the live site will not update either.

### 2. Test the app by hand

Do these on the live demo (<https://shipdoc.duckdns.org>) or on your local copy (<http://localhost:5173>).

| # | What to do | What you should see |
|---|---|---|
| 1 | Open `/api/health` | `"status":"ok"`, `"database":true`, `"records":520` |
| 2 | Open the Dashboard | Counts by status (OK, MISMATCH, NEEDS_REVIEW) and by category |
| 3 | Inbox: filter by status **MISMATCH**, then copy the address and open it in a new tab | The same filtered list appears |
| 4 | Open record `email_013` and click the BL **port of discharge** value | The source document opens with the matching line highlighted |
| 5 | Open record `email_501` | Sent to review as **wrong document type**: the BL attachment is really a commercial invoice, so no comparison is made |
| 6 | Open record `email_507` | Sent to review as **missing attachment**: only the SI was attached |
| 7 | Open record `email_511` | Sent to review as **unreadable**: the PDF is damaged |
| 8 | Review queue: open **Reviewer**, enter any name and the passcode (`averis2026` on the live demo), then open an item and **Confirm** it | The status changes at once, without reloading the page |
| 9 | Repeat step 8 on a **phone in a private / incognito window** | Works the same. This is how judges usually open a link |
| 10 | Evaluation page | The Qwen vs DeepSeek comparison table is shown |
| 11 | Try it yourself: fill in or pick an example, then run it | A field-by-field result with MATCH, MISMATCH or CANNOT_DETERMINE for each field |

### 3. Common problems

| What you see | Likely cause | Fix |
|---|---|---|
| "This build has no API address" | `VITE_API_BASE_URL` was not set when building | Create `.env.local` from `.env.example`, then run `npm run dev` or `npm run build` again |
| "Could not reach the API at ..." | The backend is not running, or the address is wrong | Start the backend (Step 1) and open `/api/health` to check it |
| Pages load but Confirm or Approve fails | Wrong or missing passcode, or the backend's `CORS_ORIGINS` does not match the website address | Sign in again with the right passcode; set `CORS_ORIGINS` to the exact website address with no trailing `/` |
| `npm run build` stops with `error TS...` | A TypeScript error in the code | Fix the file and line named in the error, then build again |

---

## Deployment (cloud)

The live site runs on an AWS EC2 server. The server builds this repository with Node 20 and the live address, and Caddy serves the result:

```bash
cd /opt/shipdoc/frontend
git pull
sudo docker run --rm -v "$PWD":/app -w /app \
  -e VITE_API_BASE_URL="https://shipdoc.duckdns.org" \
  node:20 sh -c "npm ci && npm run build"
```

No restart is needed; the new files are served straight away. The full server setup (Docker Compose, Caddy, database) is in the backend repository under `deploy/aws/`.
