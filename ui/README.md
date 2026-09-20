# ShipDoc — reviewer UI

The web interface for the **Shipping Document Verification System**. It is a static
single-page app that talks to the backend over HTTP and nothing else — no server, no
database, no secrets.

**Backend repository:**
<https://github.com/Hackathon-Repo-Org/Shipping-Document-Verification-System-Averis_x_Monash_Hackathon>

---

## What the system does, in one paragraph

A freight customer sends a **Shipping Instruction** (SI) saying what they want
shipped, to whom and to which port. The carrier replies with a **draft Bill of
Lading** (BL) — the document of title that actually moves the cargo. Someone has to
check the draft says what the customer asked for, because a wrong consignee or a
wrong discharge port is expensive and slow to unwind once the vessel has sailed. The
engine reads an inbox, works out which emails are asking for that check, and compares
**seven fields**. Every field gets **match**, **mismatch**, or **cannot determine** —
and that third verdict is the point. This UI is where a human sees the result and
rules on it.

---

## Quick start

```bash
npm install
cp .env.example .env          # set VITE_API_BASE_URL to your API origin
npm run dev                   # http://localhost:5173
```

The backend must be running separately. From the backend repo:

```bash
$env:DATABASE_URL="sqlite:///output/shipdoc.db"
$env:DEMO_PASSCODE="averis2026"
$env:CORS_ORIGINS="http://localhost:5173"
python -m shipdoc db seed
python -m shipdoc
python -m uvicorn shipdoc.adapters.api.app:app --port 8000
```

### Configuration — exactly one variable

| Variable | Required | What it is |
|---|---|---|
| `VITE_API_BASE_URL` | **yes** | the backend origin, e.g. `http://localhost:8000` |

**It is build-time config.** Static Web Apps serves a built bundle; there is no
server to read an environment variable at request time, so the value is baked in by
Vite at `npm run build`. No hostname is hardcoded anywhere in `src/` — a build with
the variable unset says so in the UI rather than silently calling a relative path.

```bash
npm run build       # -> dist/
npm run preview     # serve dist/ locally
npm run typecheck
```

---

## The screens

| Route | What it is for |
|---|---|
| `/` | **Dashboard** — counts by status and category, the four score axes, the AI's share of decisions, cache-hit rate, the run's reproducibility hashes, and **Reset demo** |
| `/inbox` | **Inbox** — filter and search. Filter state lives in the URL, so you can send a colleague a link to exactly what you are looking at |
| `/records/:id` | **Email detail** — the most important screen. Seven fields side by side with the evidence for each |
| `/queue` | **Review queue** — keyboard-first, built for someone doing fifty of these |
| `/proposals` | **Label proposals** — approve or reject what a model suggested |
| `/evaluation` | **Evaluation** — the four axes and the qwen vs DeepSeek comparison |
| `/try` | **Try it yourself** — paste your own SI and BL and watch the real engine run |

### The evidence viewer is the trust feature

Every value on the detail screen is a button. Clicking it opens the document that
value was read from, scrolled to and **highlighting the exact line**. A reviewer is
being asked to believe the system read `MOMBASA, KENYA` off line 10 of a bill of
lading; the only thing that earns that belief is seeing line 10.

It shows the **extracted** text, not the original bytes, and that is deliberate: for
a PDF rebuilt from word coordinates, or a spreadsheet flattened to `label | value`,
the evidence's line numbers do not exist in the source file. Highlighting line 10 of
the raw PDF would point confidently at the wrong thing. The original file is offered
alongside, labelled as raw.

### Read versus inferred is always visible

A value the system *inferred* must never look like one it *read*. Where a value was
resolved by reference (`NOTIFY PARTY: SAME AS CONSIGNEE`), pre-filled by OCR, or
matched through a learned label, the row says so.

### Keyboard shortcuts (review queue)

| Key | Action |
|---|---|
| `J` / `K` or ↑ ↓ | move |
| `Enter` | open the record |
| `A` | confirm |
| `C` | correct to the SI value — **one click, never retype** |
| `E` | clear a record-level escalation |
| `R` | retry |
| `N` | next **unreviewed** — skips what you have already decided |
| `Esc` | close the evidence drawer |

The shortcuts are printed at the bottom of the queue, not hidden in a help page.

---

## Try it yourself

`/try` lets a visitor paste their own shipping instruction and draft bill of lading
and see what the system makes of them. **It runs the real engine** — the same
normaliser, comparators and state machine as the 520-record batch. Only ingest and
extract are skipped, because the text arrived as text.

- **No passcode.** Gating it behind a code a visitor does not have defeats the point.
- **Nothing is stored.** No database write; it never becomes a run and cannot appear
  in the run history.
- **No API key is used**, so it cannot be made to burn credits by being refreshed.
- Input is size-capped.

**Load a worked example** prefills a realistic pair with one planted defect, so your
first click finds something rather than returning OK and looking broken. It
demonstrates four behaviours at once: the discharge-port defect is caught; `SDN BHD`
vs `SDN. BHD.` still matches; `SAME AS CONSIGNEE` resolves against its own document
and is labelled as inferred; `22,450.50` and `22.450,50` are recognised as the same
number.

---

## Authentication

**Reads are open. Writes need a passcode.** A judge can browse everything without a
code; acting on a record needs the code from the presentation slide, plus a reviewer
name — an unattributed decision is not auditable, so the name is required.

The passcode travels as the **`X-Demo-Passcode` header, never a cookie.** The
frontend and the API are different origins, so a cookie would be third-party and is
blocked by Safari and by incognito windows — which is exactly how a judge opens a
public link.

That header is also what makes every write a **preflighted** CORS request. If the API
does not allow the header and the `OPTIONS` method, **reads work and writes fail**,
which looks exactly like a backend bug and is not one. It is the first thing to check
if writes stop working after a deployment.

---

## Design credit

The visual design is **adopted from a teammate's prototype**, not original work here.
Colour tokens, typography, spacing, the card and badge styling, and the 64px-header
page shell were taken from:

<https://github.com/Hackathon-Repo-Org/-Front-End-Shipping-Document-Verification-System-Averis_x_Monash_Hackathon->
at commit `6734871`.

That repository was cloned **read-only, outside the working tree, and never
modified**. What was adopted, what was not, and why, is recorded in
`docs/design-notes.md` in the backend repository.

One deliberate change to their design: **every verdict carries an icon as well as a
colour.** The prototype used colour alone, which is unreadable for a meaningful
fraction of reviewers.

---

## Stack, and what is deliberately absent

React 18 · TypeScript · Vite · React Router. Bootstrap Icons from a CDN.

No component library, no CSS framework, no state-management library, no data-fetching
library. The whole app is ~1,500 lines. A design system would have to be fought to
match the prototype's look, and the fetching this UI does is a dozen endpoints behind
one typed module.

**Vocabulary is fetched, never hardcoded.** Category names, statuses, review reasons,
verdicts and field labels all come from `GET /api/vocabulary`. The backend's
`adapters/` layer owns the external spellings; a string pasted into a component
re-implements that mapping in a second language with nothing checking the two agree,
and the rename that follows breaks the UI silently — no error, just a filter that
quietly matches nothing.

---

## Deployment

Built for **Azure Static Web Apps** (`staticwebapp.config.json` is included). The
`navigationFallback` in it is what makes a hard reload of `/records/email_013` work
instead of 404ing — without it the router never runs, which breaks the shareable-URL
behaviour the filter state was built for.

The full command sequence, including the CORS setting that must be fixed **after**
the Static Web App exists, is in `docs/deploy-azure.md` in the backend repository.

---

## Honest status

- Verified locally across two real origins: reads, writes, preflight, and the source
  viewer for `.txt` and `.pdf`.
- **Not yet deployed to Azure** — the commands are written and unexecuted.
- No automated frontend tests. The API contract it depends on has 23.
- Cut list if time runs short: bulk actions, run-from-UI, audit view. **Not** the
  evidence viewer, **not** keyboard navigation.
