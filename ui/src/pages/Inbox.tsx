/**
 * INBOX — filterable, searchable, and shareable.
 *
 * FILTER STATE LIVES IN THE URL. A reviewer who finds something odd needs to send a
 * colleague a link to exactly what they are looking at, not a description of which
 * dropdowns to set. That is the whole reason this uses search params rather than
 * component state.
 *
 * `awaiting_documents` is its OWN filter and is OFF by default. Those records are a
 * shipper saying "the draft is coming" — they are OK, not work. Mixing them into the
 * list buries the handful of genuinely broken records under routine correspondence.
 */
import { useEffect, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { ApiError, api, type Page, type RecordRow } from "../lib/api";
import { Badge, termOf, useVocab } from "../lib/vocab";

const PAGE = 50;

export function Inbox() {
  const vocab = useVocab();
  const nav = useNavigate();
  const [sp, setSp] = useSearchParams();
  const [page, setPage] = useState<Page<RecordRow> | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [q, setQ] = useState(sp.get("q") ?? "");

  const get = (k: string) => sp.get(k) ?? "";
  const set = (k: string, v: string) => {
    const next = new URLSearchParams(sp);
    if (v) next.set(k, v); else next.delete(k);
    next.delete("offset");
    setSp(next, { replace: false });
  };
  const offset = Number(get("offset") || 0);

  useEffect(() => {
    setErr(null); setPage(null);
    api.records({
      category: get("category") || undefined,
      status: get("status") || undefined,
      review_reason: get("reason") || undefined,
      awaiting_documents: get("awaiting") === "1" ? true : undefined,
      decided: get("decided") === "1" ? true : get("decided") === "0" ? false : undefined,
      q: get("q") || undefined,
      limit: PAGE, offset,
    }).then(setPage).catch((e: ApiError) => setErr(e.message));
  }, [sp]);

  return (
    <>
      <h1 style={{ fontSize: "1.1rem", marginTop: 0 }}>Inbox</h1>

      <div className="card-panel">
        <form className="filters" onSubmit={(e) => { e.preventDefault(); set("q", q.trim()); }}>
          <input value={q} onChange={(e) => setQ(e.target.value)}
                 placeholder="Search email id, party name or port…"
                 style={{ flex: 1, minWidth: "16rem" }} />
          <button className="btn" type="submit"><i className="bi bi-search" /> Search</button>

          <select value={get("status")} onChange={(e) => set("status", e.target.value)}>
            <option value="">Any status</option>
            {vocab?.statuses.map((s) => <option key={s.value} value={s.value}>{s.label}</option>)}
          </select>
          <select value={get("category")} onChange={(e) => set("category", e.target.value)}>
            <option value="">Any category</option>
            {vocab?.categories.map((c) => <option key={c.value} value={c.value}>{c.label}</option>)}
          </select>
          <select value={get("reason")} onChange={(e) => set("reason", e.target.value)}>
            <option value="">Any reason</option>
            {vocab?.review_reasons.map((r) => <option key={r.value} value={r.value}>{r.label}</option>)}
          </select>
          <select value={get("decided")} onChange={(e) => set("decided", e.target.value)}>
            <option value="">Decided or not</option>
            <option value="1">Human decided</option>
            <option value="0">Not yet decided</option>
          </select>

          <label className="btn" style={{ gap: ".45rem" }}
                 title="These records are a shipper saying the draft is coming. They are OK, not work — so they are hidden unless you ask.">
            <input type="checkbox" checked={get("awaiting") === "1"}
                   onChange={(e) => set("awaiting", e.target.checked ? "1" : "")}
                   style={{ width: "auto" }} />
            Awaiting documents
          </label>

          {[...sp.keys()].length > 0 && (
            <button className="btn" type="button" onClick={() => setSp(new URLSearchParams())}>
              Clear
            </button>
          )}
        </form>

        {err && <div className="banner err"><i className="bi bi-exclamation-triangle" /><span>{err}</span></div>}
        {!page && !err && <div className="muted"><span className="spinner" /> Loading&hellip;</div>}

        {page && (
          <>
            <div className="muted" style={{ marginBottom: ".4rem", fontSize: ".78rem" }}>
              {page.total} record{page.total === 1 ? "" : "s"}
              {get("awaiting") !== "1" && " · awaiting-documents hidden"}
            </div>
            <div className="table-wrap">
              <table className="data">
                <thead>
                  <tr>
                    <th>Email</th><th>Category</th><th>Status</th>
                    <th>Reason</th><th>Defects</th><th>Decided</th>
                  </tr>
                </thead>
                <tbody>
                  {page.items.map((r) => (
                    <tr key={r.email_id} className="row"
                        onClick={() => nav(`/records/${r.email_id}`)}>
                      <td className="mono">{r.email_id}</td>
                      <td><Badge term={termOf(vocab?.categories, r.category)} /></td>
                      <td><Badge term={termOf(vocab?.statuses, r.status)} /></td>
                      <td className="muted">
                        {r.review_reason ? termOf(vocab?.review_reasons, r.review_reason).label : "—"}
                      </td>
                      <td>{r.defect_count > 0
                        ? <span className="tag tone-danger">{r.defect_count}</span>
                        : <span className="muted">—</span>}</td>
                      <td>{r.human_decided
                        ? <span className="tag tone-primary"><i className="bi bi-person-check" /> yes</span>
                        : <span className="muted">—</span>}</td>
                    </tr>
                  ))}
                  {page.items.length === 0 && (
                    <tr><td colSpan={6} className="muted" style={{ padding: "1rem" }}>
                      Nothing matches these filters.
                    </td></tr>
                  )}
                </tbody>
              </table>
            </div>

            {page.total > PAGE && (
              <div className="filters" style={{ marginTop: ".6rem" }}>
                <button className="btn" disabled={offset === 0}
                        onClick={() => set("offset", String(Math.max(0, offset - PAGE)))}>
                  <i className="bi bi-chevron-left" /> Previous
                </button>
                <span className="muted">
                  {offset + 1}–{Math.min(offset + PAGE, page.total)} of {page.total}
                </span>
                <button className="btn" disabled={offset + PAGE >= page.total}
                        onClick={() => set("offset", String(offset + PAGE))}>
                  Next <i className="bi bi-chevron-right" />
                </button>
              </div>
            )}
          </>
        )}
      </div>
    </>
  );
}
