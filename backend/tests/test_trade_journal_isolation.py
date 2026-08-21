"""
Regression test for a HIGH finding in the 2026-08-21 audit (Finding #8):

Every full test-suite run wrote to the real, git-tracked
`backend/data/trade_journal.json` via `TradePostMortemEngine`, whose
`JOURNAL_FILE` path was a hardcoded module-level constant derived from
`__file__`. Any test exercising `SmartExecutionEngine.force_close()` /
`execute_trade()`'s SELL/COVER branches fired `record_closed_trade_async()`
in a background thread, silently polluting real production data — this
required a manual `git checkout -- backend/data/trade_journal.json` after
every single test run in this session.

Fix: `JOURNAL_FILE` now reads `TRADE_JOURNAL_PATH` from the environment
first, falling back to the original real path when unset (so production
behavior is unchanged). `backend/tests/conftest.py` sets this env var to an
isolated temp-file path before any test module is imported.
"""

import importlib
import os


def test_journal_file_honors_env_override(monkeypatch, tmp_path):
    conftest_path = os.environ["TRADE_JOURNAL_PATH"]  # set by tests/conftest.py
    override_path = str(tmp_path / "isolated_journal.json")

    import analytics.trade_postmortem as tp
    try:
        monkeypatch.setenv("TRADE_JOURNAL_PATH", override_path)
        importlib.reload(tp)
        assert tp.JOURNAL_FILE == override_path
    finally:
        # monkeypatch's own teardown restores the env var, but only AFTER
        # this function returns — the reload here must happen with the
        # conftest-set value back in place, or every later test in the
        # session picks up this test's throwaway tmp_path instead.
        monkeypatch.setenv("TRADE_JOURNAL_PATH", conftest_path)
        importlib.reload(tp)


def _real_journal_path():
    import analytics.trade_postmortem
    return os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(analytics.trade_postmortem.__file__))),
        "data", "trade_journal.json",
    )


def test_conftest_isolates_journal_path_from_real_data_dir():
    """
    conftest.py must have already set TRADE_JOURNAL_PATH by the time any
    test runs, and it must NOT point at the real backend/data/trade_journal.json.
    """
    override = os.environ.get("TRADE_JOURNAL_PATH")
    assert override, "conftest.py did not set TRADE_JOURNAL_PATH"
    assert os.path.abspath(override) != _real_journal_path(), (
        "TRADE_JOURNAL_PATH points at the real production trade_journal.json"
    )


def test_actual_engine_uses_the_overridden_path():
    from analytics.trade_postmortem import TradePostMortemEngine
    engine = TradePostMortemEngine.instance()
    assert engine.journal_path == os.environ["TRADE_JOURNAL_PATH"]
    assert os.path.abspath(engine.journal_path) != _real_journal_path()
