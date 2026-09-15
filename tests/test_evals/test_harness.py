"""Phase 18 tests: the eval runner (EvalResult, run_evals, format_results,
isolated_storage) — mirrors tests one would write for benchmarks/harness.py."""

from __future__ import annotations

from evals.harness import (
    EvalResult,
    all_evals,
    format_results,
    isolated_storage,
    main,
    run_evals,
)


async def _ok(name: str = "ok") -> EvalResult:
    return EvalResult(suite="s", name=name, passed=True, duration_ms=1.0)


async def _fail(name: str = "bad") -> EvalResult:
    return EvalResult(suite="s", name=name, passed=False, duration_ms=1.0, detail="nope")


async def _boom() -> EvalResult:
    raise RuntimeError("kaboom")


class TestAllEvals:
    def test_returns_every_suite(self):
        evals = all_evals()
        # grammar(2) + vocabulary(2) + assessment(3) + curriculum(3) + regression(1)
        assert len(evals) == 11

    def test_every_eval_is_a_coroutine_function(self):
        import inspect

        for one in all_evals():
            assert inspect.iscoroutinefunction(one)


class TestRunEvals:
    async def test_runs_selected_evals_in_order(self):
        results = await run_evals([_ok, _fail])
        assert [r.passed for r in results] == [True, False]

    async def test_exception_becomes_failing_result_not_a_crash(self):
        results = await run_evals([_ok, _boom])
        assert results[0].passed is True
        assert results[1].passed is False
        assert "kaboom" in results[1].detail

    async def test_default_selection_runs_the_full_registry(self):
        results = await run_evals()
        assert len(results) == len(all_evals())


class TestFormatResults:
    def test_includes_suite_headers_and_status(self):
        text = format_results([EvalResult(suite="grammar", name="x", passed=True, duration_ms=1.0)])
        assert "grammar" in text
        assert "[PASS]" in text
        assert "1/1 evals passed" in text

    def test_ascii_safe(self):
        results = [
            EvalResult(suite="s", name="a", passed=True, duration_ms=1.0, metrics={"x": 1}),
            EvalResult(suite="s", name="b", passed=False, duration_ms=1.0, detail="oops"),
        ]
        format_results(results).encode("ascii")

    def test_groups_consecutive_same_suite_under_one_header(self):
        results = [
            EvalResult(suite="a", name="1", passed=True, duration_ms=0.0),
            EvalResult(suite="a", name="2", passed=True, duration_ms=0.0),
            EvalResult(suite="b", name="3", passed=True, duration_ms=0.0),
        ]
        text = format_results(results)
        assert text.count("-- a --") == 1
        assert text.count("-- b --") == 1


class TestMain:
    def test_main_returns_0_when_all_pass(self, monkeypatch):
        import evals.harness as harness_module

        monkeypatch.setattr(harness_module, "run_evals", lambda evals=None: _all_pass())
        assert main() == 0

    def test_main_returns_1_when_any_fail(self, monkeypatch):
        import evals.harness as harness_module

        monkeypatch.setattr(harness_module, "run_evals", lambda evals=None: _one_fails())
        assert main() == 1


async def _all_pass() -> list[EvalResult]:
    return [await _ok()]


async def _one_fails() -> list[EvalResult]:
    return [await _ok(), await _fail()]


class TestIsolatedStorage:
    async def test_redirects_and_restores_settings(self):
        from src.config import settings

        original_db_path = settings.db_path
        async with isolated_storage() as tmp_dir:
            assert settings.db_path != original_db_path
            assert str(tmp_dir) in settings.db_path
        assert settings.db_path == original_db_path

    async def test_restores_on_exception(self):
        from src.config import settings

        original_data_dir = settings.data_dir
        try:
            async with isolated_storage():
                raise ValueError("boom")
        except ValueError:
            pass
        assert settings.data_dir == original_data_dir

    async def test_writes_inside_the_temp_dir_are_isolated(self):
        # A DB write during the scope must not touch the real ./data database.
        async with isolated_storage():
            from src.memory import vocabulary_db

            vocabulary_db.upsert_word("eval-isolation-user", "Spanish", "aislado")
            from src.config import settings

            assert vocabulary_db.get_all_for_user("eval-isolation-user", "Spanish")
            assert "polyglot-eval-" in settings.db_path
