# Design notes — what was adopted from the frontend reference

The visual design of `ui/` is **not original work**. It is adopted from a teammate's
prototype so that the reviewer UI looks like the thing the team already agreed on,
rather than like a third design nobody chose.

**Source** — cloned read-only, outside this working tree, and never modified:

```
https://github.com/Hackathon-Repo-Org/-Front-End-Shipping-Document-Verification-System-Averis_x_Monash_Hackathon-
commit 6734871ce8f566086a2d4c8ac93b11fbac68fbd8
local path ../sdoc-frontend-ref/   (a sibling of the repo, like ../sdoc-server/)
```

It appears nowhere in this repository and nothing here writes to it. `git status`
inside that clone is empty, and it is not a submodule, not vendored, not committed.

---

## Adopted: the look

### Colour tokens — taken verbatim

Lifted exactly as written from `V1 Front End Website/Index.html`, `:root`:

| Token | Value | Used in `ui/` for |
|---|---|---|
| `--bg-main` | `#f8fafc` | page background |
| `--border-color` | `#e2e8f0` | every card, table and input border |
| `--sidebar-bg` / `--header-bg` | `#ffffff` | shell surfaces |
| `--text-dark` | `#0f172a` | body text |
| `--text-muted` | `#64748b` | labels, secondary text, evidence lines |
| `--primary` | `#2563eb` | actions, links, focus rings |
| `--primary-light` | `#eff6ff` | selected rows, active nav |
| `--danger` | `#ef4444` | MISMATCH verdicts, defect counts |
| `--warning` | `#f59e0b` | CANNOT_DETERMINE, NEEDS_REVIEW |
| `--success` | `#10b981` | MATCH verdicts, OK status |

The names were kept too, not just the values, so a diff against the reference is
readable.

### Typography and shape

| Property | Reference | Kept |
|---|---|---|
| Font stack | `-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif` | yes, verbatim |
| Header height | `64px` | yes |
| Header padding | `0.75rem 2rem` | yes |
| Corner radius | `6px` controls, `8px`/`12px` cards, `9999px` pills | yes, as a 4-step scale |
| Card shadow | `0 1px 3px rgba(0,0,0,0.02)` | yes |
| Focus ring | `0 0 0 3px rgba(37,99,235,0.1)` | yes — it is the accessibility affordance |
| Icons | Bootstrap Icons 1.11.3 | yes, same CDN and version |

### Components

`card-panel`, `kpi-card` / `kpi-value` / `kpi-label`, `badge`, `tag`, `nav-btn`, and
the header + `main-layout` page shell were reimplemented as React components keeping
the reference's class names and visual proportions.

---

## Not adopted, and why

The brief was explicit that the **look** is theirs and the **behaviour** is specified
by the API contract. Three things therefore diverge, and none of them is a judgement
on the prototype:

1. **Data model.** The reference invents its own record shape. `ui/` takes its types
   from the OpenAPI schema the API publishes, generated at build time. Two hand-kept
   copies of a shape drift, and the one that drifts is the one nobody is testing.

2. **Vocabulary strings.** The prototype hardcodes category and status strings in
   markup (`tag-${e.category}`). `ui/` fetches them from `GET /api/vocabulary`.
   `adapters/` owns the external spellings — a hardcoded string in the UI breaks
   that boundary, and a rename would then break the UI silently.

3. **Routing and state.** The reference is multi-page static HTML with inline
   scripts. `ui/` is a single-page app with filter state **in the URL**, because a
   reviewer needs to send a colleague a link to exactly what they are looking at.

---

## What the reference did well, and was kept for that reason

- **The KPI card row** reads at a glance, which is the entire job of a dashboard.
- **Muted greys with one strong blue** keeps red and amber meaning something. A
  palette that uses colour everywhere cannot use colour for status.
- **A 64px header with a left nav** is the right shell for a list-plus-detail tool
  and needed no change.

One accessibility addition on top: every verdict carries **an icon as well as a
colour**, so the seven-field comparison is readable without colour vision. The
reference used colour alone. That is a change to their design and it is called out
here rather than made quietly.
