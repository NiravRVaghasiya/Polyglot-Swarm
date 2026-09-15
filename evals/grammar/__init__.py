"""Grammar evaluation suite: precision, recall, F1, false-correction rate, and
calibration of the grammar agent's classification/abstention policy
(:func:`src.agents.grammar._select_errors`).

This exercises the same decision logic as ``benchmarks/grammar_bench.py`` (kept
unchanged as the fast CI smoke check) against a larger, versioned dataset with
explicit confidence bands, so it can also report calibration — which the
smoke benchmark does not.
"""
