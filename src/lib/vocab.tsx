/**
 * Vocabulary from the API, never hardcoded.
 *
 * `adapters/` owns the external spellings. A category or status string pasted into a
 * component re-implements that mapping in a second language with nothing checking
 * the two agree — and the rename that follows breaks the UI silently: no error, just
 * a filter that quietly matches nothing.
 */
import { createContext, useContext, useEffect, useState } from "react";
import { api, type Term, type Vocabulary } from "./api";

const Ctx = createContext<Vocabulary | null>(null);

export function VocabProvider({ children }: { children: React.ReactNode }) {
  const [v, setV] = useState<Vocabulary | null>(null);
  useEffect(() => { api.vocabulary().then(setV).catch(() => setV(null)); }, []);
  return <Ctx.Provider value={v}>{children}</Ctx.Provider>;
}

export function useVocab() { return useContext(Ctx); }

export function termOf(list: Term[] | undefined, value: string | null): Term {
  const hit = list?.find((t) => t.value === value);
  return hit ?? { value: value ?? "—", label: value ?? "—", tone: "muted" };
}

/** A badge carries an ICON as well as a colour.
 *  The reference design used colour alone; this is the one deliberate change to it,
 *  because a verdict that is only distinguishable by hue is unreadable to a
 *  meaningful fraction of reviewers. */
export function Badge({ term, title }: { term: Term; title?: string }) {
  return (
    <span className={`badge tone-${term.tone ?? "muted"}`} title={title ?? term.help}>
      {term.icon && <i className={`bi bi-${term.icon}`} />}
      {term.label}
    </span>
  );
}
