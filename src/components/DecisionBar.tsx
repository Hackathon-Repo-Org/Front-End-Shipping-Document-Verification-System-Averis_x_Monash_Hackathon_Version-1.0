/**
 * The five review actions (A4), and the rule that correcting a value is ONE CLICK
 * when a value is already on screen.
 *
 * A reviewer doing fifty of these must never retype a value they can see. Where the
 * SI already holds the right value — which is the common case, since the SI is
 * authoritative — correcting the BL is a single button with the value pre-filled.
 */
import { useState } from "react";
import { ApiError, api, type RecordDetail } from "../lib/api";
import { termOf, useVocab } from "../lib/vocab";

export function DecisionBar({ record, onDone, reviewer }: {
  record: RecordDetail;
  onDone: (r: RecordDetail) => void;
  reviewer: string;
}) {
  const vocab = useVocab();
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [note, setNote] = useState("");
  const [field, setField] = useState<string>(
    record.defect_fields?.[0] ?? record.comparisons[0]?.field ?? "");

  const chosen = record.comparisons.find((c) => c.field === field);
  const suggested = chosen?.si_value ?? null;

  async function act(decision_type: string, extra: Record<string, unknown> = {}) {
    if (!reviewer) {
      setErr("Set your name first (top right). An unattributed decision is not auditable.");
      return;
    }
    setBusy(true); setErr(null);
    try {
      onDone(await api.decide(record.email_id, {
        decision_type, reviewer, note, ...extra,
      } as never));
      setNote("");
    } catch (e) {
      setErr((e as ApiError).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="card-panel">
      <h2>Decide</h2>
      {err && <div className="banner err"><i className="bi bi-exclamation-triangle" /><span>{err}</span></div>}

      <div className="filters">
        <select value={field} onChange={(e) => setField(e.target.value)}
                aria-label="Field to act on">
          {record.comparisons.map((c) => (
            <option key={c.field} value={c.field}>
              {vocab?.fields.find((f) => f.value === c.field)?.label ?? c.field}
              {" · "}{c.verdict}
            </option>
          ))}
        </select>
        <input value={note} onChange={(e) => setNote(e.target.value)}
               placeholder="Note (optional, but future you will want it)"
               style={{ flex: 1, minWidth: "14rem" }} />
      </div>

      <div className="filters">
        <button className="btn primary" disabled={busy || !field}
                onClick={() => act("confirm", { field, verdict: "MATCH" })}>
          <kbd>A</kbd> Confirm match
        </button>
        <button className="btn" disabled={busy || !field}
                onClick={() => act("confirm", { field, verdict: "MISMATCH" })}>
          Confirm defect
        </button>

        {/* ONE CLICK. The SI value is already on screen; making someone retype it is
            how a review queue becomes something people avoid. */}
        {suggested && (
          <button className="btn" disabled={busy}
                  title={`Set the BL value to the SI's: ${suggested}`}
                  onClick={() => act("correct_value",
                                     { field, corrected_value: suggested, verdict: "MATCH" })}>
            <kbd>C</kbd> Correct to SI value
            <span className="mono muted" style={{ fontSize: ".72rem" }}>
              {suggested.length > 22 ? `${suggested.slice(0, 22)}…` : suggested}
            </span>
          </button>
        )}

        <button className="btn" disabled={busy}
                onClick={() => act("clear_escalation", { field: null })}
                title="Resolve a record-level escalation. May bypass the monotone state rule — which will be shown and logged.">
          <kbd>E</kbd> Clear escalation
        </button>
        <button className="btn" disabled={busy}
                onClick={() => act("retry", { field: null })}>
          <kbd>R</kbd> Retry
        </button>
        <OverrideCategory record={record} onAct={act} busy={busy} />
        {busy && <span className="spinner" />}
      </div>

      <p className="muted" style={{ fontSize: ".74rem", margin: 0 }}>
        Decisions apply immediately and are keyed to the email, not to a run — every
        future run inherits them. Nothing is deleted; a later ruling supersedes an
        earlier one.
      </p>
    </div>
  );
}

function OverrideCategory({ record, onAct, busy }: {
  record: RecordDetail;
  onAct: (t: string, extra?: Record<string, unknown>) => void;
  busy: boolean;
}) {
  const vocab = useVocab();
  const [open, setOpen] = useState(false);
  if (!open) {
    return (
      <button className="btn" disabled={busy} onClick={() => setOpen(true)}>
        <kbd>O</kbd> Override category
      </button>
    );
  }
  return (
    <select autoFocus defaultValue="" disabled={busy}
            onChange={(e) => {
              if (e.target.value) {
                onAct("override_category", { field: null, corrected_category: e.target.value });
              }
              setOpen(false);
            }}>
      <option value="" disabled>
        Currently {termOf(vocab?.categories, record.category).label} — change to…
      </option>
      {vocab?.categories.filter((c) => c.value !== record.category).map((c) => (
        <option key={c.value} value={c.value}>{c.label}</option>
      ))}
    </select>
  );
}
