# Deploy to Azure — the exact command sequence

Copy-paste, top to bottom. **Every step is marked 👤 (needs a human) or 📋 (pure
copy-paste).** Values you must supply are marked `<FILL ME>` with a note on where to
get them.

Written by someone without an Azure subscription, so **nothing here has been executed
against real Azure.** The image, the API, the UI and the cross-origin write were all
verified locally and in a container — see "What was and was not verified" at the end.

Budget about **25 minutes** the first time.

---

## 0. Before you start 👤

```bash
az login                                   # 👤 opens a browser
az account set --subscription "<FILL ME>"  # 👤 `az account list -o table` to find it
az extension add --name containerapp --upgrade
az provider register --namespace Microsoft.App
az provider register --namespace Microsoft.OperationalInsights
```

Set these once and the rest is paste-able:

```bash
export RG=shipdoc-rg
export LOC=southeastasia                   # nearest your judges
export ACR=shipdocacr$RANDOM               # globally unique, lowercase, no dashes
export PG=shipdoc-db-$RANDOM
export PGPASS='<FILL ME>'                  # 👤 invent a strong one; you need it twice
export DEMO_PASSCODE='<FILL ME>'           # 👤 goes on your slide
export DEEPSEEK_KEY='<FILL ME>'            # 👤 optional — see step 3b

az group create --name $RG --location $LOC
```

---

## 1. Container registry, build and push 📋

`az acr build` builds **in Azure**, so you do not need Docker locally and you cannot
get the architecture wrong.

```bash
az acr create --resource-group $RG --name $ACR --sku Basic --admin-enabled true
az acr build --registry $ACR --image shipdoc:v1 .     # run from the repo root

export ACR_SERVER=$(az acr show -n $ACR --query loginServer -o tsv)
export ACR_PASS=$(az acr credential show -n $ACR --query "passwords[0].value" -o tsv)
```

---

## 2. PostgreSQL 📋

```bash
az postgres flexible-server create \
  --resource-group $RG --name $PG --location $LOC \
  --tier Burstable --sku-name Standard_B1ms --version 16 \
  --database-name shipdoc \
  --admin-user shipdocadmin --admin-password "$PGPASS" \
  --public-access 0.0.0.0 \
  --yes

export DB_URL="postgresql+psycopg://shipdocadmin:${PGPASS}@${PG}.postgres.database.azure.com:5432/shipdoc?sslmode=require"
```

> ### ⚠️ STEP 5 IS THE ONE THAT BITES. READ IT NOW, NOT LATER.
> `--public-access 0.0.0.0` above is the **"allow other Azure services"** rule, not
> public internet. It is what lets the Container App reach the database. If you skip
> it or tighten it later, the symptom is **a hang and then a timeout** — never a
> clear "access denied" — and it looks exactly like a bug in the application.
>
> **If the deployed app cannot reach the database, check this before changing any
> code.** It is the single most common cause.

---

## 3. The Container App (the backend) 📋

### 3a. Create it

```bash
az containerapp env create --name shipdoc-env --resource-group $RG --location $LOC

az containerapp create \
  --name shipdoc-api --resource-group $RG --environment shipdoc-env \
  --image $ACR_SERVER/shipdoc:v1 \
  --registry-server $ACR_SERVER --registry-username $ACR --registry-password "$ACR_PASS" \
  --ingress external --target-port 8000 \
  --min-replicas 1 --max-replicas 3 \
  --cpu 1.0 --memory 2.0Gi \
  --secrets db-url="$DB_URL" demo-code="$DEMO_PASSCODE" \
  --env-vars DATABASE_URL=secretref:db-url \
             DEMO_PASSCODE=secretref:demo-code \
             SHIPDOC_ROOT=/app \
             CORS_ORIGINS="http://localhost:5173" \
  --command /usr/local/bin/docker-entrypoint.sh --args serve

export API_URL="https://$(az containerapp show -n shipdoc-api -g $RG \
  --query properties.configuration.ingress.fqdn -o tsv)"
echo "$API_URL"
```

**Every App Setting, by name:**

| Setting | Value | Required? | Why |
|---|---|---|---|
| `DATABASE_URL` | `secretref:db-url` | yes | runs, records, decisions |
| `DEMO_PASSCODE` | `secretref:demo-code` | yes | without it the API is **read-only** |
| `SHIPDOC_ROOT` | `/app` | **yes** | without it the API cannot find `config/` and reports `provider: null` |
| `CORS_ORIGINS` | the Static Web App origin | yes | set properly in step 4; a placeholder for now |
| `DEEPSEEK_API_KEY` | `secretref:deepseek-key` | **no** | see 3b |
| `PORT` | `8000` | no | the entrypoint defaults to it |

> **`--min-replicas 1`, never 0.** Scale-to-zero saves pennies and costs you the
> demo: the first judge waits ~20s for a cold start and assumes it is broken.

> **Secrets go in `--secrets` and are referenced as `secretref:`.** A value passed
> straight into `--env-vars` is visible in `az containerapp show` and in the portal.

### 3b. The AI provider

`config/pipeline.yaml` ships with **`provider: deepseek`**.

**You still do NOT need a key for the demo.** The image bakes in the committed LLM
cache, which holds deepseek-chat's answers for all 520 records, so the corpus demo
runs with **no API key and no outbound AI call**. That is the safest configuration
for judging: nothing can rate-limit you mid-demo.

A key is only needed for **new** emails — the `/try` page with unseen text, or real
inbox traffic. Without one the system degrades to deterministic keyword rules and
says so, rather than failing.

To supply it:

```bash
az containerapp secret set -n shipdoc-api -g $RG \
  --secrets deepseek-key="$DEEPSEEK_KEY"
az containerapp update -n shipdoc-api -g $RG \
  --set-env-vars DEEPSEEK_API_KEY=secretref:deepseek-key
```

**Score note:** the default costs **0.058** against `provider: ollama`
(0.9277 vs 0.9858) — entirely in stage-1 classification; defect detection and
end-to-end are identical. If the judged number matters more than cloud realism, set
`provider: ollama` in `config/pipeline.yaml` **before** `az acr build`. It needs no
GPU and no key either, because the cache covers both.

---

## 4. Static Web App (the frontend) 📋

The API URL is **build-time** config, so the backend must exist first.

```bash
cd ui
echo "VITE_API_BASE_URL=$API_URL" > .env.production
npm ci
npm run build

az staticwebapp create --name shipdoc-ui --resource-group $RG \
  --location eastasia --sku Free
export SWA_TOKEN=$(az staticwebapp secrets list --name shipdoc-ui \
  --resource-group $RG --query "properties.apiKey" -o tsv)

npx --yes @azure/static-web-apps-cli deploy ./dist \
  --deployment-token "$SWA_TOKEN" --env production

export SWA_URL="https://$(az staticwebapp show -n shipdoc-ui -g $RG \
  --query defaultHostname -o tsv)"
echo "$SWA_URL"
cd ..
```

### 4b. 🔴 NOW GO BACK AND FIX CORS — it is wrong until you do

The Static Web App's origin is not known until it exists, so the API was created with
a placeholder. **Reads will work and writes will fail** until this runs:

```bash
az containerapp update -n shipdoc-api -g $RG \
  --set-env-vars CORS_ORIGINS="$SWA_URL"
```

---

## 5. Database firewall 👤📋

Step 2's `--public-access 0.0.0.0` already covers the Container App. Add **your own
machine** so you can run the migration and the seed:

```bash
MYIP=$(curl -s https://api.ipify.org)
az postgres flexible-server firewall-rule create \
  --resource-group $RG --name $PG \
  --rule-name my-laptop --start-ip-address $MYIP --end-ip-address $MYIP
```

> For production, prefer a **private endpoint** or VNet integration over an
> IP allow-list. A Container App's outbound IP changes on scale and redeploy, so an
> allow-list pinned to one IP will silently stop working; pin egress with a NAT
> gateway if you must keep one.

---

## 6. Migrate and seed 📋

Run them **from the same image** as the app, so the schema cannot drift from the code
that reads it.

```bash
az containerapp exec -n shipdoc-api -g $RG --command "alembic upgrade head"
az containerapp exec -n shipdoc-api -g $RG --command "shipdoc db seed"
az containerapp exec -n shipdoc-api -g $RG --command "shipdoc"        # the 520-record run
az containerapp exec -n shipdoc-api -g $RG --command "shipdoc db check"
```

Expect, after `db check`: `emails 520 · attachments 250 · runs 1 · records 520 ·
comparisons 798`.

**Seeding is idempotent** — run it twice, the counts do not change.

If `az containerapp exec` is awkward, the same commands run as one-off jobs; see
`SETUP.md` Tier 5 step 5.

---

## 7. Keep it warm for judging 📋

```bash
az containerapp update -n shipdoc-api -g $RG --min-replicas 1
```

Already set in step 3, listed again because it is the thing people turn off to save
money and then regret.

---

# POST-DEPLOY CHECK — in this order, one action each

Do not skip ahead. Each step rules out a different failure.

### 1. Health endpoint 📋
```bash
curl -s $API_URL/api/health
```
**Expect** `"status":"ok"`, `"database":true`, `"records":520`, and
**`"provider"` NOT null**.
`provider: null` ⇒ `SHIPDOC_ROOT` is missing. `database:false` ⇒ step 5, the firewall.

### 2. A read from the deployed UI 👤
Open `$SWA_URL`. The dashboard fills in with counts.
Empty page or "API: unreachable" ⇒ CORS (step 4b) or the API is down.

### 3. A WRITE from the deployed UI, on a phone, in incognito 👤
**This is the real test.** On a phone, incognito:
open `$SWA_URL` → Sign in (any name + the passcode) → open a record → Confirm.
The status must change **with no reload**.

If reads work and this fails, it is the **preflight on the passcode header**:
```bash
curl -s -i -X OPTIONS $API_URL/api/records/email_013/decisions \
  -H "Origin: $SWA_URL" -H "Access-Control-Request-Method: POST" \
  -H "Access-Control-Request-Headers: content-type,x-demo-passcode" \
  | grep -i access-control
```
You need `access-control-allow-headers` to include `x-demo-passcode` and the origin
to match `$SWA_URL` exactly — no trailing slash.

### 4. A source document renders 👤
Open `email_013` → click the BL discharge-port value.
The drawer opens the document highlighted at **line 10**. Then "Raw file" → the
original opens.

### 5. Try it yourself 👤
`/try` → **Load a worked example** → **Run it**.
Expect `MISMATCH` on `port_of_discharge` and MATCH on the other six.

### 6. Reset demo 👤
Dashboard → **Reset demo**. Decisions clear; the 520 records stay.

---

## What was and was not verified

**Verified locally and in a container:**

- the image builds, runs as **non-root (uid 10001)**, exposes **8000**
- Tesseract present; LLM cache baked in
- `/api/health` reports `provider: ollama`, 520 records **from inside the container**
- the full 520-record pipeline completes **with no API key** and reproduces
  `7ff39d87…`
- cross-origin: preflight allows `X-Demo-Passcode` + `OPTIONS`, a write succeeds, a
  foreign origin is refused
- the evidence viewer serves `.txt` and `.pdf` across the origin
- 776 tests pass

**Not verified — needs an Azure account:**

- every `az` command above. They follow current Azure CLI syntax but have not been
  run.
- `az containerapp exec` behaviour for the migration; if it misbehaves, use the
  one-off job form in `SETUP.md` Tier 5.
- Static Web Apps deployment via the SWA CLI.
- real-world cold-start timing.
