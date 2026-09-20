/**
 * THE EVIDENCE VIEWER — the trust feature.
 *
 * A reviewer is being asked to believe that this system read `MOMBASA, KENYA` off
 * line 10 of a bill of lading. The only thing that earns that belief is being able
 * to click the value and SEE line 10. Everything else on the screen is an assertion;
 * this is the proof.
 *
 * It shows the EXTRACTED text, not the original bytes, and that is deliberate. The
 * line numbers in the evidence refer to what the extractor produced — for a PDF
 * rebuilt from word coordinates, or an xlsx flattened to `label | value`, those
 * lines do not exist in the source file at all. Highlighting line 10 of the original
 * PDF would point at the wrong thing, confidently. A link to the original document
 * is offered alongside, clearly labelled as the raw file.
 *
 * CROSSING THE ORIGIN: the text and the raw file both come from the API on a
 * different host. That is the thing most likely to work locally and fail in the
 * cloud, so both paths surface a readable error rather than an empty panel.
 */
import { useEffect, useRef, useState } from "react";
import { ApiError, api, type Evidence as Ev } from "../lib/api";

export interface EvidenceTarget {
  emailId: string;
  role: "SI" | "BL";
  field: string;
  value: string | null;
  evidence: Ev | null;
  attachmentId?: number | string;
  filename?: string;
}

/** `locator` is "line 21", or a spreadsheet cell like "B7". Only the first is a
 *  line to highlight; a cell reference is shown as-is rather than guessed at. */
function lineNumber(locator: string | null | undefined): number | null {
  if (!locator) return null;
  const m = /line\s+(\d+)/i.exec(locator);
  return m ? Number(m[1]) : null;
}

export function EvidenceDrawer(
  { target, onClose }: { target: EvidenceTarget; onClose: () => void },
) {
  const [lines, setLines] = useState<string[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const hit = lineNumber(target.evidence?.locator);
  const hitRef = useRef<HTMLDivElement | null>(null);
  const closeRef = useRef<HTMLButtonElement | null>(null);

  useEffect(() => {
    let alive = true;
    setLines(null); setError(null);
    api.sourceText(target.emailId, target.role)
      .then((r) => { if (alive) setLines(r.lines); })
      .catch((e: ApiError) => { if (alive) setError(e.message); });
    return () => { alive = false; };
  }, [target.emailId, target.role]);

  // Scroll the highlighted line into view, and move focus to the drawer so Esc
  // works without the reviewer having to click inside it first.
  useEffect(() => {
    closeRef.current?.focus();
    if (lines && hitRef.current) {
      hitRef.current.scrollIntoView({ block: "center" });
    }
  }, [lines]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const rawUrl = target.attachmentId !== undefined
    ? api.sourceUrl(target.emailId, String(target.attachmentId))
    : null;

  return (
    <>
      <div className="drawer-backdrop" onClick={onClose} />
      <aside className="drawer" role="dialog" aria-label="Source document">
        <header>
          <div style={{ minWidth: 0 }}>
            <div style={{ fontWeight: 700 }}>
              {target.role} · {target.field}
            </div>
            <div className="muted" style={{ fontSize: ".75rem" }}>
              {target.evidence?.file ?? target.filename ?? "source document"}
              {target.evidence?.locator ? ` · ${target.evidence.locator}` : ""}
              {target.evidence?.method ? ` · ${target.evidence.method}` : ""}
            </div>
          </div>
          <div style={{ display: "flex", gap: ".4rem", flexShrink: 0 }}>
            {rawUrl && (
              <a className="btn" href={rawUrl} target="_blank" rel="noreferrer"
                 title="Open the original file as it was attached">
                <i className="bi bi-box-arrow-up-right" /> Raw file
              </a>
            )}
            <button className="btn" ref={closeRef} onClick={onClose}>
              Close <kbd>Esc</kbd>
            </button>
          </div>
        </header>

        {target.evidence?.resolved_from && (
          <div className="banner warn" style={{ margin: ".75rem 1rem 0" }}>
            <i className="bi bi-signpost-split" />
            <span>
              This value was <strong>not read from its own line</strong>. The document
              said <span className="mono">{target.evidence.reference_text}</span> and
              the value was taken from this document&rsquo;s{" "}
              <strong>{target.evidence.resolved_from}</strong>.
            </span>
          </div>
        )}
        {target.evidence?.method === "ocr" && (
          <div className="banner warn" style={{ margin: ".75rem 1rem 0" }}>
            <i className="bi bi-eye" />
            <span>Read by <strong>OCR</strong>. Treat as pre-fill to be checked,
              not as evidence.</span>
          </div>
        )}

        <div className="body">
          {error && (
            <div className="banner err" style={{ margin: "1rem" }}>
              <i className="bi bi-exclamation-triangle" />
              <span>{error}</span>
            </div>
          )}
          {!lines && !error && (
            <div style={{ padding: "1rem" }} className="muted">
              <span className="spinner" /> Loading the extracted text&hellip;
            </div>
          )}
          {lines?.map((text, i) => {
            const n = i + 1;
            const isHit = hit === n;
            return (
              <div key={n} className={`src-line${isHit ? " hit" : ""}`}
                   ref={isHit ? hitRef : undefined}>
                <span className="n">{n}</span>
                <span>{text || " "}</span>
              </div>
            );
          })}
          {lines && hit === null && target.evidence?.locator && (
            <div className="banner info" style={{ margin: "1rem" }}>
              <i className="bi bi-info-circle" />
              <span>
                This value came from <strong>{target.evidence.locator}</strong>, which
                is a cell reference rather than a line — the whole extraction is shown
                above.
              </span>
            </div>
          )}
        </div>
      </aside>
    </>
  );
}
