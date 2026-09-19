"""Phase 5 containment — `port_resolution_enabled` must be a true off switch.

Phase 5 wired UN/LOCODE resolution into two places, not one:
  * `compare/comparators.cmp_port` — the obvious one
  * `normalise.PortResolver.identity()` — which returns a LOCODE when the table is
    loaded, changing `FieldValue.normalised` for every resolvable port

Gating only the first left the second leaking, and the pre-Phase-5 hash would not
come back. These tests pin both halves so the flag cannot half-work again.
"""
import dataclasses

import pytest

from conftest import CONFIG_DIR, DATASET_DIR, TEST_CACHE
from shipdoc.config import load_config
from shipdoc.ingest.loader_port import LoaderInbox
from shipdoc.normalise import Normaliser
from shipdoc.types import Verdict


@pytest.fixture(scope="module")
def cfg_off():
    return load_config(CONFIG_DIR)


@pytest.fixture(scope="module")
def cfg_on(cfg_off):
    return dataclasses.replace(
        cfg_off, flags=dataclasses.replace(cfg_off.flags, port_resolution_enabled=True))


def test_flag_is_off_by_default(cfg_off):
    """Phase 5 ships dark until it has been measured against the answer key."""
    assert cfg_off.flags.port_resolution_enabled is False


def test_flag_off_means_no_table_is_loaded(cfg_off):
    """The second leak. Loading the table while the flag is off changes normalised
    port values even though the resolver never reaches the comparator."""
    assert Normaliser(cfg_off).ports.loaded is False


def test_flag_on_loads_the_table(cfg_on):
    n = Normaliser(cfg_on)
    assert n.ports.loaded is True
    assert n.ports.rows > 100_000


def test_flag_off_port_identity_is_the_name_not_a_locode(cfg_off):
    """Pre-Phase-5 behaviour: identity is the normalised place name."""
    ports = Normaliser(cfg_off).ports
    assert ports.identity("CALLAO, PERU (PECLL)")[0] == "CALLAO"


def test_flag_on_port_identity_is_a_locode(cfg_on):
    ports = Normaliser(cfg_on).ports
    assert ports.identity("CALLAO, PERU (PECLL)")[0] == "PECLL"


def test_flag_off_comparator_never_uses_the_locode_strategy(cfg_off):
    """With the flag off no comparison may be attributed to `port_locode` — that
    strategy label is the fingerprint of the Phase 5 path."""
    from shipdoc.pipeline import run_corpus
    r = run_corpus(LoaderInbox(str(DATASET_DIR)), cfg_off, llm=None, decisions={},
                   cache_dir=TEST_CACHE)
    strategies = {c.strategy
                  for rec in r["records"] for c in rec.comparisons.values()}
    assert "port_locode" not in strategies


def test_flag_on_comparator_does_use_it(cfg_on):
    from shipdoc.pipeline import run_corpus
    r = run_corpus(LoaderInbox(str(DATASET_DIR)), cfg_on, llm=None, decisions={},
                   cache_dir=TEST_CACHE)
    strategies = {c.strategy
                  for rec in r["records"] for c in rec.comparisons.values()}
    assert "port_locode" in strategies


def test_the_two_settings_actually_differ(cfg_off, cfg_on):
    """If these ever stop differing the flag has become decorative and the
    measurement it exists to enable is meaningless."""
    from shipdoc.pipeline import run_corpus
    ib = LoaderInbox(str(DATASET_DIR))
    a = run_corpus(ib, cfg_off, llm=None, decisions={}, cache_dir=TEST_CACHE)["submission"]
    b = run_corpus(ib, cfg_on, llm=None, decisions={}, cache_dir=TEST_CACHE)["submission"]
    assert a != b
