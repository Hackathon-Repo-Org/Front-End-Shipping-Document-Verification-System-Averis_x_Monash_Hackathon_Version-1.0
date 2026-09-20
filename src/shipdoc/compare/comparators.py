"""M10 — two canonical field maps to exactly len(cfg.fields) Comparisons.

`compare_all` iterates the REGISTRY, never the input maps. Iterating the SI keys, or
the intersection of SI and BL keys, means a field absent from both is never passed to
a comparator at all — and the None guard cannot help, because it protects against a
present-but-empty value, not an absent key. That was v1.0 defect C2.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Callable

from shipdoc.normalise import AMBIGUOUS, UNRESOLVED_REFERENCE
from shipdoc.types import (
    Comparison,
    Config,
    FieldSpec,
    FieldValue,
    Thresholds,
    Verdict,
)


def _thresholds(spec: FieldSpec, th: Thresholds) -> tuple[float, float]:
    """M10 P-ADDRESS: per-field thresholds are mandatory, not optional. Party fields
    carry a wrapped address continuation, so comparing 120-char blobs with `ratio`
    sits in the grey band on a large fraction of records unless they are loosened."""
    if spec.threshold is not None and spec.grey_low is not None:
        return spec.threshold, spec.grey_low
    pair = th.name_address if spec.address_bearing else th.name_strict
    return pair.threshold, pair.grey_low


def _ambiguous(v: FieldValue | None) -> bool:
    return v is not None and v.label_seen == AMBIGUOUS


def _missing(si, bl, spec, strategy) -> Comparison | None:
    """The asymmetric-presence rules (M10 verdict table).

    The SI is the authoritative reference, so a field the shipper specified and the
    carrier omitted is a DEFECT, not an uncertainty. v1.0 treated si=None and bl=None
    identically, which scored a real omission as `NEEDS_REVIEW`.

    PHASE 10 — THREE STATES, NOT TWO. "We could not find the label" is not "the
    carrier omitted the value", and conflating them fabricates a defect out of our
    own incomplete synonym list. email_999's BL reads `Containers: 3 x 40'HC`, which
    is character-identical to the SI; `Containers:` was simply not in the synonym
    list, and the system reported a defect on two values that agree.

      key present, normalised set   -> compare normally (this returns None)
      key present, normalised None  -> the label WAS found and the value is blank or
                                       a sentinel: the BL genuinely omits it, and the
                                       SI is authoritative -> MISMATCH
      key ABSENT                    -> no label for this field was found in the
                                       document at all, or the harvested value failed
                                       T3 verification. Either way this is an
                                       EXTRACTION MISS, a fact about us and not about
                                       the carrier -> CANNOT_DETERMINE -> NEEDS_REVIEW

    The synonym list will always be incomplete. The point of the third state is that
    an incomplete list now produces caution instead of a confident lie.

    `leaning` stays None on every branch here: nothing was obtained, so there is no
    view to commit to (patch 02 §3). In particular the extraction-miss branch must
    NOT lean MISMATCH — we have no evidence of a discrepancy, only of our own silence.
    """
    # Phase 10 Fix 2. A pointer we could not follow is an uncertainty, and it must be
    # read BEFORE the asymmetric-presence rules — otherwise it falls through to
    # `normalised is None` and is reported as a confident omission.
    for side, fv in (("SI", si), ("BL", bl)):
        if fv is not None and fv.label_seen == UNRESOLVED_REFERENCE:
            return Comparison(spec.name, Verdict.CANNOT_DETERMINE, si, bl, strategy,
                              f"{side} value refers to another field "
                              f"({fv.raw_text.strip()[:40]!r}) that could not be "
                              f"resolved on that document", leaning=None)

    si_has = si is not None and si.normalised is not None
    bl_has = bl is not None and bl.normalised is not None
    if si_has and bl_has:
        return None
    if si_has and bl is None:
        return Comparison(spec.name, Verdict.CANNOT_DETERMINE, si, bl, strategy,
                          f"no {spec.name} label found in the BL — extraction miss, "
                          f"not a confirmed omission", leaning=None)
    if si_has and not bl_has:
        return Comparison(spec.name, Verdict.MISMATCH, si, bl, strategy,
                          "SI present, BL sentinel — SI is authoritative", leaning=None)
    return Comparison(spec.name, Verdict.CANNOT_DETERMINE, si, bl, strategy,
                      "no SI reference to compare against", leaning=None)


def cmp_text(si: FieldValue | None, bl: FieldValue | None,
             spec: FieldSpec, th: Thresholds) -> Comparison:
    early = _missing(si, bl, spec, "text")
    if early is not None:
        return early
    if _ambiguous(si) or _ambiguous(bl):
        return Comparison(spec.name, Verdict.CANNOT_DETERMINE, si, bl, "text",
                          "two candidate values found for one field",
                          leaning=Verdict.MISMATCH)

    if spec.address_bearing:
        return _cmp_party(si, bl, spec, th)

    a, b = str(si.normalised), str(bl.normalised)
    hi, lo = _thresholds(spec, th)
    # `ratio` on normalised strings, never token_set_ratio: it scores
    # "ABC Trading" against "ABC Trading Sdn Bhd Malaysia Branch" at 100, ignoring
    # extra tokens entirely, which is exactly the difference that matters here.
    from rapidfuzz import fuzz

    score = fuzz.ratio(a, b) / 100.0
    detail = f"similarity {score:.3f}, threshold {hi:.2f}, grey_low {lo:.2f}"
    if score >= hi:
        return Comparison(spec.name, Verdict.MATCH, si, bl, "text", detail)
    if score < lo:
        return Comparison(spec.name, Verdict.MISMATCH, si, bl, "text", detail)
    # Grey band. v1.0 said "decide + log" and never said which way; it is
    # CANNOT_DETERMINE, but the direction of the signal is preserved.
    return Comparison(spec.name, Verdict.CANNOT_DETERMINE, si, bl, "text",
                      detail + " (grey band)", leaning=Verdict.MISMATCH)


def _cmp_party(si: FieldValue, bl: FieldValue,
               spec: FieldSpec, th: Thresholds) -> Comparison:
    """Company name decides; address is advisory.

    The name is compared strictly because it is short — a changed legal suffix is a
    large fraction of it, which is the point of review item B7. The address may raise
    a SUSPICION but can never on its own produce MATCH or MISMATCH, because the
    formats disagree about whether it is even present: a .docx table carries the name
    only, while an .xlsx cell carries name and address together.
    """
    from rapidfuzz import fuzz

    from shipdoc.normalise.party import normalise_party_name, split_party

    si_name, si_addr = split_party(si.raw_text)
    bl_name, bl_addr = split_party(bl.raw_text)
    a, b = normalise_party_name(si_name), normalise_party_name(bl_name)

    if not a or not b:
        return Comparison(spec.name, Verdict.CANNOT_DETERMINE, si, bl, "party",
                          "could not isolate a company name", leaning=None)

    hi, lo = th.name_strict.threshold, th.name_strict.grey_low
    score = fuzz.ratio(a, b) / 100.0
    addr_note = ""
    if si_addr and bl_addr:
        addr_score = fuzz.ratio(normalise_party_name(si_addr),
                                normalise_party_name(bl_addr)) / 100.0
        addr_note = f"; address similarity {addr_score:.2f} (advisory)"
    elif si_addr or bl_addr:
        addr_note = "; address on one side only (advisory, ignored)"

    detail = f"name {a!r} vs {b!r}, similarity {score:.3f}{addr_note}"

    if score >= hi:
        return Comparison(spec.name, Verdict.MATCH, si, bl, "party", detail)
    if score < lo:
        return Comparison(spec.name, Verdict.MISMATCH, si, bl, "party", detail)
    return Comparison(spec.name, Verdict.CANNOT_DETERMINE, si, bl, "party",
                      detail + " (grey band)", leaning=Verdict.MISMATCH)


def cmp_port(si: FieldValue | None, bl: FieldValue | None,
             spec: FieldSpec, th: Thresholds,
             resolver=None) -> Comparison:
    """Patch 02 §3 verdict table, with UN/LOCODE resolution when a table is loaded.

        both resolve, codes equal      -> MATCH
        both resolve, codes differ     -> MISMATCH
        either unresolvable, names differ -> CANNOT_DETERMINE, leaning MISMATCH
        either unresolvable, names equal  -> CANNOT_DETERMINE, leaning MATCH
        a side missing / unreadable    -> CANNOT_DETERMINE, leaning None

    The table is an ENRICHMENT. With no resolver — or no table loaded — this falls
    through to exactly the string comparison that existed before it shipped.
    """
    early = _missing(si, bl, spec, "port")
    if early is not None:
        return early
    if _ambiguous(si) or _ambiguous(bl):
        return Comparison(spec.name, Verdict.CANNOT_DETERMINE, si, bl, "port",
                          "two candidate values found for one field",
                          leaning=Verdict.MISMATCH)

    a, b = str(si.normalised), str(bl.normalised)

    if resolver is not None and getattr(resolver, "loaded", False):
        si_code, si_why = resolver.resolve(si.raw_text)
        bl_code, bl_why = resolver.resolve(bl.raw_text)
        if si_code is not None and bl_code is not None:
            verdict = Verdict.MATCH if si_code == bl_code else Verdict.MISMATCH
            return Comparison(spec.name, verdict, si, bl, "port_locode",
                              f"{si_code} vs {bl_code} (UN/LOCODE)")
        # One or both unresolvable. NEVER compare the codes now — a None here means
        # "I could not resolve this", and treating it as a value is the silent-pass
        # this module exists to prevent. Fall back to the normalised names, and say
        # which way they point without claiming to know.
        leaning = Verdict.MATCH if a == b else Verdict.MISMATCH
        return Comparison(
            spec.name, Verdict.CANNOT_DETERMINE, si, bl, "port_locode",
            f"unresolved (SI: {si_why}; BL: {bl_why}); "
            f"normalised names {'equal' if a == b else 'differ'}",
            leaning=leaning)

    if a == b:
        return Comparison(spec.name, Verdict.MATCH, si, bl, "port", f"identity {a}")
    from rapidfuzz import fuzz

    score = fuzz.ratio(a, b) / 100.0
    hi, lo = _thresholds(spec, th)
    detail = f"{a!r} vs {b!r}, similarity {score:.3f}"
    if score >= hi:
        return Comparison(spec.name, Verdict.MATCH, si, bl, "port", detail)
    if score < lo:
        return Comparison(spec.name, Verdict.MISMATCH, si, bl, "port", detail)
    return Comparison(spec.name, Verdict.CANNOT_DETERMINE, si, bl, "port",
                      detail + " (grey band)", leaning=Verdict.MISMATCH)


def cmp_numeric(si: FieldValue | None, bl: FieldValue | None,
                spec: FieldSpec, th: Thresholds) -> Comparison:
    early = _missing(si, bl, spec, "numeric")
    if early is not None:
        return early
    if _ambiguous(si) or _ambiguous(bl):
        return Comparison(spec.name, Verdict.CANNOT_DETERMINE, si, bl, "numeric",
                          "two candidate values found for one field",
                          leaning=Verdict.MISMATCH)

    a, b = si.normalised, bl.normalised
    # Never fuzzy-match numbers: 3 and 4 are similar as strings and completely
    # different as containers.
    if isinstance(a, int) and isinstance(b, int):
        verdict = Verdict.MATCH if a == b else Verdict.MISMATCH
        return Comparison(spec.name, verdict, si, bl, "numeric", f"{a} vs {b} (exact)")

    da, db = Decimal(str(a)), Decimal(str(b))
    eps = th.quantity_epsilon
    delta = abs(da - db)
    verdict = Verdict.MATCH if delta <= eps else Verdict.MISMATCH
    return Comparison(spec.name, verdict, si, bl, "numeric",
                      f"{da} vs {db}, |delta|={delta} epsilon={eps}")


COMPARATORS: dict[str, Callable[..., Comparison]] = {
    "text":     cmp_text,
    "port":     cmp_port,
    "integer":  cmp_numeric,
    "quantity": cmp_numeric,
}

# The stage-4 half of the FIELD_TYPES contract recorded in types.py: config validates
# against the vocabulary, and the implementation asserts it satisfies it.
from shipdoc.types import FIELD_TYPES  # noqa: E402

assert set(COMPARATORS) == FIELD_TYPES, (
    f"comparator registry {sorted(COMPARATORS)} does not match the declared field "
    f"types {sorted(FIELD_TYPES)}; config validation would permit a type nothing "
    f"implements")


def compare_all(si: dict[str, FieldValue], bl: dict[str, FieldValue],
                cfg: Config, resolver=None) -> dict[str, Comparison]:
    """CONTRACT: returns exactly len(cfg.fields) entries, keyed by the registry.

    Never an identity short-circuit (`if si.raw == bl.raw: return MATCH`). It is the
    most tempting optimisation in this module and it re-opens the sentinel hole
    completely: two documents both carrying `N/A` are equal as strings.
    """
    out: dict[str, Comparison] = {}
    for name, spec in cfg.fields.items():
        fn = COMPARATORS[spec.type]
        if spec.type == "port":
            out[name] = fn(si.get(name), bl.get(name), spec, cfg.thresholds, resolver)
        else:
            out[name] = fn(si.get(name), bl.get(name), spec, cfg.thresholds)
    return out
