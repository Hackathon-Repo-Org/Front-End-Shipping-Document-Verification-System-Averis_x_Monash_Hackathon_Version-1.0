/**
 * LABEL PROPOSALS — the screen that proves the human gate is load-bearing.
 *
 * Each row carries the label, the field a model proposed for it, WHICH model, and
 * the evidence line with its surrounding context. Without that context a reviewer is
 * being asked to guess, and a queue that trains its reviewer to guess is worse than
 * no queue.
 *
 * Rejecting is one click and is as valuable as approving: a rejection is recorded
 * permanently, so the same question never comes back. Without that, a reviewer is
 * asked the same thing every week and stops reading the queue.
 */
import { useCallback, useEffect, useState } from "react";
import { ApiError, api, getReviewer, type Proposal } from "../lib/api";

export function Proposals() {
  const [tab, setTab] = useState<"pending" | "approved" | "rejected">("pending");
  const [rows, setRows] = useState<Proposal[] | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState<number | null>(null);

  const load = useCallback(() => {
    setRows(null);
    api.proposals(tab).then(setRows).catch((e: ApiError) => setErr(e.message));
  }, [tab]);
  useEffect(load, [load]);

  async function decide(p: Proposal, decision: "approved" | "rejected") {
    const reviewer = getReviewer();
    if (!reviewer) {
      setErr("Set your name first (top right) — an approval with no name is not auditable.");
      return;
    }
    setBusy(p.proposal_id); setErr(null);
    try {
      await api.decideProposal(p.proposal_id, decision, reviewer);
      load();
    } catch (e) {
      setErr((e as ApiError).message);
    } finally {
      setBusy(null);
    }
  }

  return (
    <>
      <h1 style={{ fontSize: "1.1rem", marginTop: 0 }}>Label proposals</h1>
      <div className="banner info">
        <i className="bi bi-robot" />
        <span>
          <strong>AI proposes · a human approves · rules execute.</strong> Nothing
          here has taken effect. An approval becomes a permanent, deterministic
          extraction rule; a rejection is recorded so the question never returns.
        </span>
      </div>

      <div className="filters">
        {(["pending", "approved", "rejected"] as const).map((t) => (
          <button key={t} className={`btn${tab === t ? " primary" : ""}`}
                  onClick={() => setTab(t)}>{t}</button>
        ))}
      </div>

      {err && <div className="banner err"><i className="bi bi-exclamation-triangle" /><span>{err}</span></div>}
      {!rows && <div className="muted"><span className="spinner" /> Loading&hellip;</div>}
      {rows?.length === 0 && <div className="card-panel muted">No {tab} proposals.</div>}

      {rows?.map((p) => (
        <div className="card-panel" key={p.proposal_id}>
          <div style={{ display: "flex", gap: ".6rem", alignItems: "center", flexWrap: "wrap" }}>
            <code className="mono" style={{ fontSize: "1rem", fontWeight: 700 }}>{p.label_raw}</code>
            <i className="bi bi-arrow-right muted" />
            <span className="tag tone-primary">{p.proposed_field ?? "NONE"}</span>
            <span className="tag tone-muted" title="Which model proposed this">
              <i className="bi bi-cpu" /> {p.proposed_by}
            </span>
            <span className="muted" style={{ fontSize: ".75rem" }}>{p.prompt_version}</span>
            {p.decided_by && (
              <span className="tag tone-muted"><i className="bi bi-person-check" /> {p.decided_by}</span>
            )}
          </div>

          <div className="muted" style={{ fontSize: ".78rem", margin: ".5rem 0 .2rem" }}>
            <i className="bi bi-file-earmark-text" /> {p.evidence_doc}
            {p.evidence_line ? ` · line ${p.evidence_line}` : ""}
          </div>
          <pre style={{
            background: "var(--bg-main)", padding: ".6rem .8rem",
            borderRadius: "var(--r)", fontSize: ".76rem", overflow: "auto", margin: 0,
          }}>{p.evidence_context}</pre>

          {tab === "pending" && (
            <div className="filters" style={{ marginTop: ".7rem" }}>
              <button className="btn primary" disabled={busy === p.proposal_id}
                      onClick={() => decide(p, "approved")}>
                <i className="bi bi-check-lg" /> Approve
              </button>
              <button className="btn danger" disabled={busy === p.proposal_id}
                      onClick={() => decide(p, "rejected")}>
                <i className="bi bi-x-lg" /> Reject
              </button>
              {busy === p.proposal_id && <span className="spinner" />}
              <span className="muted" style={{ fontSize: ".75rem" }}>
                Signed with your name, permanently.
              </span>
            </div>
          )}
        </div>
      ))}
    </>
  );
}
