"""Stage 3 gate — M07 classification and M12b the LLM client."""
import json

import pytest

from conftest import CONFIG_DIR, DATASET_DIR, ROOT
from shipdoc.classify.arbiter import classify
from shipdoc.classify.semantic import _coerce, classify_semantic, render_prompt
from shipdoc.classify.structural import classify_structural, parse_roles
from shipdoc.config import load_config
from shipdoc.errors import LLMUnavailable
from shipdoc.infra.cache import Cache, NullCache, sha256_text
from shipdoc.ingest.loader_port import LoaderInbox
from shipdoc.llm.client import CachedLLM
from shipdoc.types import Category, Record


@pytest.fixture(scope="module")
def cfg():
    return load_config(CONFIG_DIR)


@pytest.fixture(scope="module")
def emails():
    return LoaderInbox(str(DATASET_DIR)).emails()


def rec(e) -> Record:
    return Record(email_id=e["email_id"], raw=e)


class FakeLLM:
    def __init__(self, *replies):
        self.replies = list(replies)
        self.prompts = []

    def complete(self, prompt, *, choices=None, timeout_s=30.0):
        self.prompts.append(prompt)
        if not self.replies:
            raise AssertionError("called more times than it has replies")
        r = self.replies.pop(0)
        if isinstance(r, Exception):
            raise r
        return r


# --------------------------------------------------------------------------
# structural — it PARTITIONS, it does not decide
# --------------------------------------------------------------------------

def test_structural_partitions_126_and_394(cfg, emails):
    decided = [e for e in emails if classify_structural(rec(e), cfg).category is not None]
    undecided = [e for e in emails if classify_structural(rec(e), cfg).category is None]
    assert len(decided) == 126
    assert len(undecided) == 394


def test_structural_decides_only_the_comparison_category(cfg, emails):
    cats = {classify_structural(rec(e), cfg).category for e in emails}
    assert cats == {cfg.comparison_category, None}


def test_structural_never_guesses_general_for_zero_attachments(cfg, emails):
    """M07's first pitfall, and it is load-bearing here: 220 records are gold
    BL_COMPARISON but only 126 carry attachments, so ~94 comparison requests arrive
    with nothing attached. Returning GENERAL for those would lose them on all three
    weighted axes."""
    for e in emails:
        if not e["attachments"]:
            assert classify_structural(rec(e), cfg).category is None


def test_structural_handles_the_one_attachment_cases(cfg, emails):
    by_id = {e["email_id"]: e for e in emails}
    for eid in ("email_507", "email_509"):
        v = classify_structural(rec(by_id[eid]), cfg)
        assert v.category == cfg.comparison_category
        assert "only_SI" in v.evidence


def test_parse_roles_is_case_insensitive_and_anchored():
    r = Record(email_id="email_012", raw={"attachments": [
        "attachments/email_012_si.txt", "attachments/email_012_BL.TXT"]})
    assert set(parse_roles(r)) == {"SI", "BL"}


def test_parse_roles_ignores_unrecognised_names(cfg):
    r = Record(email_id="email_012", raw={"attachments": ["attachments/notes.pdf"]})
    assert parse_roles(r) == {}
    assert classify_structural(r, cfg).evidence == "attachments_unrecognised"


# --------------------------------------------------------------------------
# semantic — constrained to five exact strings
# --------------------------------------------------------------------------

@pytest.mark.parametrize("raw,expected", [
    ("BL_COMPARISON", "BL_COMPARISON"),
    ("  spam  ", "SPAM"),
    ("Label: INVOICE_QUERY", "INVOICE_QUERY"),
    ("`GENERAL`", "GENERAL"),
    ("BL comparison", "BL_COMPARISON"),
    ("si_request", "SI_REQUEST"),
])
def test_coerce_accepts_the_five(raw, expected):
    assert _coerce(raw) == expected


@pytest.mark.parametrize("raw", [
    "", "   ", "I think this is probably a shipping email of some kind",
    "Either GENERAL or SPAM", "CATEGORY_UNKNOWN", "none of the above",
])
def test_coerce_rejects_everything_else(raw):
    assert _coerce(raw) is None


def test_semantic_retries_once_then_gives_up(cfg, emails):
    llm = FakeLLM("not a label", "still not a label")
    cat, conf = classify_semantic(rec(emails[1]), cfg, llm)
    assert cat is None and conf == 0.0
    assert len(llm.prompts) == 2


def test_semantic_accepts_on_the_retry(cfg, emails):
    llm = FakeLLM("waffle", "SPAM")
    cat, conf = classify_semantic(rec(emails[1]), cfg, llm)
    assert cat == "SPAM"
    assert conf < 0.9, "a retry should carry lower confidence than a first-pass answer"


def test_semantic_is_degraded_not_fatal(cfg, emails):
    """LLMUnavailable must never propagate out of the classifier (§8)."""
    llm = FakeLLM(LLMUnavailable("ollama down"))
    assert classify_semantic(rec(emails[1]), cfg, llm) == (None, 0.0)


def test_semantic_with_no_llm_returns_none(cfg, emails):
    assert classify_semantic(rec(emails[1]), cfg, None) == (None, 0.0)


def test_prompt_truncates_the_body(cfg, emails):
    long = dict(emails[0], body="x" * 9000)
    assert len(render_prompt(Record(email_id="e", raw=long))) < 4000


def test_prompt_is_deterministic(cfg, emails):
    a = render_prompt(rec(emails[0]))
    b = render_prompt(rec(emails[0]))
    assert a == b


# --------------------------------------------------------------------------
# arbiter — structural outranks text; patch 02 §5
# --------------------------------------------------------------------------

def test_structural_decisive_blocks_the_model(cfg, emails):
    by_id = {e["email_id"]: e for e in emails}
    assert cfg.flags.structural_decisive is True
    llm = FakeLLM("SPAM")
    cat, _ = classify(rec(by_id["email_001"]), cfg, llm)
    assert cat == cfg.comparison_category
    assert llm.prompts == [], "the model must not even be consulted"


def test_non_decisive_policy_lets_the_model_overturn(cfg, emails):
    import dataclasses
    from shipdoc.types import FeatureFlags
    alt = dataclasses.replace(cfg, flags=dataclasses.replace(
        cfg.flags, structural_decisive=False))
    by_id = {e["email_id"]: e for e in emails}
    cat, _ = classify(rec(by_id["email_001"]), alt, FakeLLM("SPAM"))
    assert cat == "SPAM"


def test_non_decisive_policy_keeps_structural_when_model_undecided(cfg, emails):
    import dataclasses
    alt = dataclasses.replace(cfg, flags=dataclasses.replace(
        cfg.flags, structural_decisive=False))
    by_id = {e["email_id"]: e for e in emails}
    cat, _ = classify(rec(by_id["email_001"]), alt, FakeLLM("waffle", "waffle"))
    assert cat == cfg.comparison_category, "an undecided model must not erase a fact"


def test_arbiter_falls_back_to_rules_when_there_is_no_model(cfg, emails):
    """Review finding B9. With no model the attachment-free residue used to escalate
    en masse, which made the system unusable on a laptop with no Ollama. It now falls
    back to deterministic keyword rules, at a confidence below the model's own."""
    by_id = {e["email_id"]: e for e in emails}
    cat, conf = classify(rec(by_id["email_002"]), cfg, None)   # 0 attachments, no llm
    assert cat in {c.value for c in Category}
    assert 0.0 < conf <= 0.75, "rules must never outrank a model answer"


def test_every_record_gets_a_category_or_none(cfg, emails):
    for e in emails:
        cat, conf = classify(rec(e), cfg, None)
        assert cat is None or cat in {c.value for c in Category}
        assert 0.0 <= conf <= 1.0


# --------------------------------------------------------------------------
# M12b — cache
# --------------------------------------------------------------------------

def test_cache_key_includes_the_prompt_version(tmp_path):
    """Keying on the input alone means a prompt change silently reuses old answers."""
    a = sha256_text("v1", "same prompt", "")
    b = sha256_text("v2", "same prompt", "")
    assert a != b


def test_cached_llm_serves_a_hit_without_calling_through(tmp_path):
    inner = FakeLLM("SPAM")
    c = CachedLLM(inner, Cache(tmp_path), prompt_version="v1")
    assert c.complete("p", choices=None, timeout_s=5) == "SPAM"
    assert c.complete("p", choices=None, timeout_s=5) == "SPAM"   # no second reply queued
    assert (c.hits, c.misses) == (1, 1)


def test_cached_llm_misses_when_prompt_version_changes(tmp_path):
    cache = Cache(tmp_path)
    CachedLLM(FakeLLM("SPAM"), cache, "v1").complete("p", choices=None, timeout_s=5)
    c2 = CachedLLM(FakeLLM("GENERAL"), cache, "v2")
    assert c2.complete("p", choices=None, timeout_s=5) == "GENERAL"


def test_cache_does_not_store_failures(tmp_path):
    """Caching a failure means a fixed bug never takes effect until a manual clear."""
    cache = Cache(tmp_path)
    c = CachedLLM(FakeLLM(LLMUnavailable("down")), cache, "v1")
    with pytest.raises(LLMUnavailable):
        c.complete("p", choices=None, timeout_s=5)
    c2 = CachedLLM(FakeLLM("SPAM"), cache, "v1")
    assert c2.complete("p", choices=None, timeout_s=5) == "SPAM"


def test_cache_write_is_atomic_and_readable(tmp_path):
    cache = Cache(tmp_path)
    cache.put("a" * 64, "value")
    assert cache.get("a" * 64) == "value"
    assert cache.get("b" * 64) is None
    assert not list(tmp_path.rglob("*.tmp"))


def test_null_cache_never_serves(tmp_path):
    c = NullCache()
    c.put("k" * 64, "v")
    assert c.get("k" * 64) is None
