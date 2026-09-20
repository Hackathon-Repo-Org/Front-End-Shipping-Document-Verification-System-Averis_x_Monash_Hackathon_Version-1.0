/**
 * REVIEW QUEUE — built for someone doing fifty of these, not for a screenshot.
 *
 * KEYBOARD FIRST. A reviewer working a queue keeps their hands on the keyboard;
 * every action that requires reaching for a mouse costs a second and, fifty times
 * over, costs the reviewer's willingness to use the tool at all.
 *
 *   J / K or arrows  move          Enter  open the record
 *   A  confirm       C  correct to the SI value      R  retry
 *   E  clear escalation             Esc  close
 *   N  next unreviewed
 *
 * "NEXT UNREVIEWED" skips anything already decided, so an interrupted session
 * resumes where it left off rather than at the top of the list.
 *
 * Only ACTIONABLE items appear. Awaiting-documents records are excluded by the API
 * default, which is the point of that default existing.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { ApiError, api, getReviewer, type RecordDetail, type RecordRow } from "../lib/api";
import { Badge, termOf, useVocab } from "../lib/vocab";
import { EvidenceDrawer, type EvidenceTarget } from "../components/Evidence";

export function Queue() {
  const vocab = useVocab();
  const nav = useNavigate();
  const [rows, setRows] = useState<RecordRow[] | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [cursor, setCursor] = useState(0);
  const [detail, setDetail] = useState<RecordDetail | null>(null);
  const [target, setTarget] = useState<EvidenceTarget | null>(null);
  const [flash, setFlash] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const listRef = useRef<HTMLTableSectionElement | null>(null);

  const load = useCallback(() => {
    api.records({ status: "NEEDS_REVIEW", limit: 200 })
      .then((p) => setRows(p.items))
      .catch((e: ApiError) => setErr(e.message));
  }, []);
  useEffect(load, [load]);

  const current = rows?.[cursor];

  // Load the focused record's detail so an action can be taken without opening it.
  useEffect(() => {
    if (!current) { setDetail(null); return; }
    let alive = true;
    api.record(current.email_id)
      .then((d) => { if (alive) setDetail(d); })
      .catch(() => { if (alive) setDetail(null); });
    return () => { alive = false; };
  }, [current?.email_id]);

  const byReason = useMemo(() => {
    const m = new Map<string, number>();
    for (const r of rows ?? []) {
      const k = r.review_reason ?? "other";
      m.set(k, (m.get(k) ?? 0) + 1);
    }
    return [...m.entries()].sort((a, b) => b[1] - a[1]);
  }, [rows]);

  const act = useCallback(async (decision_type: string, extra: Record<string, unknown> = {}) => {
    const reviewer = getReviewer();
    if (!current) return;
    if (!reviewer) { setErr("Set your name first (top right)."); return; }
    setBusy(true);
    try {
      const updated = await api.decide(current.email_id,
        { decision_type, reviewer, ...extra } as never);
      setFlash(`${current.email_id} → ${updated.status}`);
      setRows((rs) => (rs ?? []).map((r) =>
        r.email_id === current.email_id
          ? { ...r, status: updated.status, human_decided: true,
              defect_count: updated.defect_fields?.length ?? 0 }
          : r));
      setTimeout(() => setFlash(null), 2200);
    } catch (e) {
      setErr((e as ApiError).message);
    } finally {
      setBusy(false);
    }
  }, [current]);

  const nextUnreviewed = useCallback(() => {
    if (!rows) return;
    for (let i = cursor + 1; i < rows.length; i++) {
      if (!rows[i].human_decided) { setCursor(i); return; }
    }
    for (let i = 0; i <= cursor; i++) {
      if (!rows[i].human_decided) { setCursor(i); return; }
    }
    setFlash("Nothing left unreviewed.");
    setTimeout(() => setFlash(null), 2200);
  }, [rows, cursor]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const el = e.target as HTMLElement;
      if (el && /^(INPUT|TEXTAREA|SELECT)$/.test(el.tagName)) return;
      if (target) return;                       // the drawer owns Esc
      const n = rows?.length ?? 0;
      switch (e.key.toLowerCase()) {
        case "j": case "arrowdown":
          e.preventDefault(); setCursor((c) => Math.min(n - 1, c + 1)); break;
        case "k": case "arrowup":
          e.preventDefault(); setCursor((c) => Math.max(0, c - 1)); break;
        case "enter":
          if (current) { e.preventDefault(); nav(`/records/${current.email_id}`); }
          break;
        case "n": e.preventDefault(); nextUnreviewed(); break;
        case "a": e.preventDefault(); void act("confirm", { field: firstField(detail), verdict: "MATCH" }); break;
        case "c": {
          e.preventDefault();
          const f = firstField(detail);
          const si = detail?.comparisons.find((c) => c.field === f)?.si_value;
          if (f && si) void act("correct_value", { field: f, corrected_value: si, verdict: "MATCH" });
          break;
        }
        case "r": e.preventDefault(); void act("retry", { field: null }); break;
        case "e": e.preventDefault(); void act("clear_escalation", { field: null }); break;
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [rows, current, detail, act, nextUnreviewed, nav, target]);

  useEffect(() => {
    listRef.current?.querySelectorAll("tr")[cursor]
      ?.scrollIntoView({ block: "nearest" });
  }, [cursor]);

  if (err && !rows) {
    return <div className="banner err"><i className="bi bi-exclamation-triangle" /><span>{err}</span></div>;
  }

  const firstDefectField = firstField(detail);
  const siValue = detail?.comparisons.find((c) => c.field === firstDefectField)?.si_value;

  return (
    <>
      <h1 style={{ fontSize: "1.1rem", marginTop: 0 }}>Review queue</h1>

      {flash && <div className="banner info"><i className="bi bi-check2-circle" /><span>{flash}</span></div>}
      {err && <div className="banner err"><i className="bi bi-exclamation-triangle" /><span>{err}</span></div>}

      <div className="filters">
        {byReason.map(([reason, n]) => (
          <span key={reason} className="tag tone-muted">
            {termOf(vocab?.review_reasons, reason).label}: <strong>{n}</strong>
          </span>
        ))}
        <button className="btn" onClick={nextUnreviewed}>
          <kbd>N</kbd> Next unreviewed
        </button>
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "minmax(0,1fr) minmax(0,1fr)", gap: "1rem" }}
           className="queue-split">
        <div className="card-panel" style={{ maxHeight: "68vh", overflow: "auto" }}>
          <table className="data">
            <thead><tr><th>Email</th><th>Reason</th><th>Status</th><th /></tr></thead>
            <tbody ref={listRef}>
              {(rows ?? []).map((r, i) => (
                <tr key={r.email_id} className={`row${i === cursor ? " sel" : ""}`}
                    onClick={() => setCursor(i)}>
                  <td className="mono">{r.email_id}</td>
                  <td className="muted">{termOf(vocab?.review_reasons, r.review_reason).label}</td>
                  <td><Badge term={termOf(vocab?.statuses, r.status)} /></td>
                  <td>{r.human_decided && <i className="bi bi-person-check" title="decided" />}</td>
                </tr>
              ))}
              {rows?.length === 0 && (
                <tr><td colSpan={4} className="muted" style={{ padding: "1rem" }}>
                  <i className="bi bi-check2-circle" /> Queue empty — nothing needs review.
                </td></tr>
              )}
            </tbody>
          </table>
        </div>

        <div className="card-panel" style={{ maxHeight: "68vh", overflow: "auto" }}>
          {!current && <span className="muted">Nothing selected.</span>}
          {current && (
            <>
              <div style={{ display: "flex", gap: ".5rem", alignItems: "center", flexWrap: "wrap" }}>
                <strong className="mono">{current.email_id}</strong>
                <Badge term={termOf(vocab?.statuses, current.status)} />
                <button className="btn" onClick={() => nav(`/records/${current.email_id}`)}>
                  <kbd>Enter</kbd> Open
                </button>
              </div>

              {!detail && <p className="muted"><span className="spinner" /> Loading&hellip;</p>}
              {detail && detail.comparisons.length > 0 && (
                <table className="cmp" style={{ marginTop: ".6rem" }}>
                  <thead><tr><th>Field</th><th>SI</th><th>BL</th><th /></tr></thead>
                  <tbody>
                    {orderFields(detail, vocab?.fields).map((c) => (
                      <tr key={c.field} className={`v-${c.verdict}`}>
                        <td>{vocab?.fields.find((f) => f.value === c.field)?.label ?? c.field}</td>
                        <td>
                          <button className="val" onClick={() => setTarget({
                            emailId: detail.email_id, role: "SI", field: c.field,
                            value: c.si_value, evidence: c.si_evidence,
                            attachmentId: detail.attachments?.find((a) => a.filename.includes("_SI"))?.attachment_id,
                          })}>{c.si_value ?? "—"}</button>
                        </td>
                        <td>
                          <button className="val" onClick={() => setTarget({
                            emailId: detail.email_id, role: "BL", field: c.field,
                            value: c.bl_value, evidence: c.bl_evidence,
                            attachmentId: detail.attachments?.find((a) => a.filename.includes("_BL"))?.attachment_id,
                          })}>{c.bl_value ?? "—"}</button>
                        </td>
                        <td><Badge term={termOf(vocab?.verdicts, c.verdict)} /></td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
              {detail && detail.comparisons.length === 0 && (
                <p className="muted">
                  No comparison was performed — {termOf(vocab?.review_reasons, detail.review_reason).label}.
                </p>
              )}

              <div className="filters" style={{ marginTop: ".7rem" }}>
                <button className="btn primary" disabled={busy || !firstDefectField}
                        onClick={() => act("confirm", { field: firstDefectField, verdict: "MATCH" })}>
                  <kbd>A</kbd> Confirm
                </button>
                {siValue && (
                  <button className="btn" disabled={busy}
                          title={`Set BL to: ${siValue}`}
                          onClick={() => act("correct_value",
                            { field: firstDefectField, corrected_value: siValue, verdict: "MATCH" })}>
                    <kbd>C</kbd> Correct to SI
                  </button>
                )}
                <button className="btn" disabled={busy}
                        onClick={() => act("clear_escalation", { field: null })}>
                  <kbd>E</kbd> Clear
                </button>
                <button className="btn" disabled={busy}
                        onClick={() => act("retry", { field: null })}>
                  <kbd>R</kbd> Retry
                </button>
                {busy && <span className="spinner" />}
              </div>
            </>
          )}

          <div className="shortcut-bar">
            <span><kbd>J</kbd>/<kbd>K</kbd> move</span>
            <span><kbd>Enter</kbd> open</span>
            <span><kbd>A</kbd> confirm</span>
            <span><kbd>C</kbd> correct</span>
            <span><kbd>E</kbd> clear</span>
            <span><kbd>R</kbd> retry</span>
            <span><kbd>N</kbd> next unreviewed</span>
            <span><kbd>Esc</kbd> close</span>
          </div>
        </div>
      </div>

      {target && <EvidenceDrawer target={target} onClose={() => setTarget(null)} />}
    </>
  );
}

/** The field an action defaults to: the first confirmed defect, else the first
 *  unresolved field. Acting on "the thing that is wrong" is what the reviewer means
 *  when they press A without choosing anything. */
/** Document order, from the vocabulary — same reason as on the detail screen. */
function orderFields(d: RecordDetail, fields?: { value: string }[]) {
  const order = fields?.map((f) => f.value) ?? [];
  return [...d.comparisons].sort(
    (a, b) => (order.indexOf(a.field) + 1 || 99) - (order.indexOf(b.field) + 1 || 99));
}

function firstField(d: RecordDetail | null): string | undefined {
  if (!d) return undefined;
  return d.comparisons.find((c) => c.verdict === "MISMATCH")?.field
      ?? d.comparisons.find((c) => c.verdict === "CANNOT_DETERMINE")?.field
      ?? d.comparisons[0]?.field;
}
