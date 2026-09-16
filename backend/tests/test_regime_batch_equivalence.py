"""Label-equality harness for the batched regime nowcast.

``docs/LANGUAGE_STRATEGY.md`` deferred the batched ``_regime_label`` refactor
to "its own change with its own label-equality test". This is that test. The
contract it pins: for the same standardized window, the batched fit
(``fit_viterbi_student_t_batch``) and the solo production fit
(``StudentTHMM(n_states=2, seed=0).fit(X).viterbi(X)``) return the **same
Viterbi states**, hence the same higher-variance-state regime label — not
merely similar likelihoods.

Why exact equality is the right bar here: the batch reproduces the solo
computation draw-for-draw (the seeded stream is broadcast, because every
solo fit restarts it) and step-for-step (same E/M order, same relative
convergence test with the same post-M-step freeze, same scalar ``brentq``
solve for ``nu``, same final scoring pass). Vectorising the source axis
changes the shape of the arrays, not the arithmetic per source. If that
claim ever stops holding — a numpy reduction reordering, a helper drifting
between the two paths — a regime label is the input to
``NetworkQualityGate``, which fails closed on an unseen label, so the
failure must be loud and here, not statistical and in production.

The engine-level test extends the same equality through
``RealPredictionEngine._regime_labels_batch``: the grouping by window
length, the 40-observation floor, the degenerate-seed fallback and the
wholesale per-source fallback must all land on the labels ``_regime_label``
produces.
"""

from __future__ import annotations

import numpy as np
import pytest

from backend.modules.engine.hidden_markov import (
    StudentTHMM,
    fit_viterbi_student_t_batch,
)


def _series(kind: str, length: int, seed: int) -> np.ndarray:
    rng = np.random.default_rng(seed)
    if kind == "calm":
        return rng.normal(0.0, 1.0, length)
    if kind == "stress":
        return rng.standard_t(3.0, length)
    if kind == "switch":
        half = length // 2
        return np.concatenate(
            [rng.normal(0.0, 1.0, half), rng.normal(0.0, 4.0, length - half)]
        )
    if kind == "spiky":
        values = rng.normal(0.0, 1.0, length)
        spikes = rng.choice(length, size=max(1, length // 50), replace=False)
        values[spikes] *= 12.0
        return values
    if kind == "drift":
        return np.cumsum(rng.normal(0.02, 1.0, length))
    if kind == "const":
        return np.full(length, 3.5)
    raise AssertionError(f"unknown series kind {kind!r}")


def _solo_states(series: np.ndarray) -> tuple[np.ndarray, StudentTHMM]:
    window = series.reshape(-1, 1)
    hmm = StudentTHMM(n_states=2, seed=0)
    hmm.fit(window)
    return hmm.viterbi(window), hmm


def _engine_label(standardized: np.ndarray, states: np.ndarray) -> str:
    """The label rule of ``_regime_label``: higher-variance state is stress."""
    variances = np.array(
        [
            standardized[states == k, 0].var() if (states == k).any() else 0.0
            for k in range(2)
        ]
    )
    stress_state = int(np.argmax(variances))
    return "stress" if int(states[-1]) == stress_state else "calm"


KINDS = ("calm", "stress", "switch", "spiky", "drift")


@pytest.mark.parametrize("length", [40, 63, 120, 250])
def test_batch_states_and_labels_equal_solo_fits(length):
    """Exact state-sequence equality across the deterministic corpus."""
    series = [_series(kind, length, seed=1000 + length + index)
              for index, kind in enumerate(KINDS)]
    stacked = np.stack([s.reshape(-1, 1) for s in series])

    fit = fit_viterbi_student_t_batch(stacked)
    assert fit.fallback_indices == []

    for index, one in enumerate(series):
        solo_states, solo_hmm = _solo_states(one)
        np.testing.assert_array_equal(
            fit.states[index],
            solo_states,
            err_msg=f"state sequence diverged (T={length}, kind={KINDS[index]})",
        )
        window = one.reshape(-1, 1)
        assert _engine_label(window, fit.states[index]) == _engine_label(
            window, solo_states
        )
        # The EM history is the softer artifact of the same computation:
        # same entries, same final likelihood of the returned parameters.
        np.testing.assert_allclose(
            fit.log_likelihood_histories[index],
            solo_hmm.log_likelihood_history,
            rtol=1e-8,
            atol=1e-6,
            err_msg=f"likelihood history diverged (T={length}, kind={KINDS[index]})",
        )


def test_production_shaped_windows_at_T1000():
    """The measured production shape: T=1000 windows, the 3.35 s-per-source
    case from LANGUAGE_STRATEGY. Two sources keep the solo reference leg
    inside a sane test budget; the batch leg is what the refactor is for."""
    series = [
        _series("switch", 1000, seed=7001),
        _series("calm", 1000, seed=7002),
    ]
    stacked = np.stack([s.reshape(-1, 1) for s in series])
    fit = fit_viterbi_student_t_batch(stacked)
    assert fit.fallback_indices == []
    for index, one in enumerate(series):
        solo_states, _ = _solo_states(one)
        np.testing.assert_array_equal(fit.states[index], solo_states)
        window = one.reshape(-1, 1)
        assert _engine_label(window, fit.states[index]) == _engine_label(
            window, solo_states
        )


def test_degenerate_seeding_falls_back_instead_of_desynchronising():
    """A constant series sends the solo fit down an extra rng branch; the
    batch must hand those sequences back for solo fitting rather than fit
    them on a stream their solo fit would not have seen — and the healthy
    sequences batched alongside them must be unaffected."""
    series = [
        _series("const", 80, seed=1),
        _series("calm", 80, seed=2),
        _series("const", 80, seed=3),
        _series("switch", 80, seed=4),
    ]
    stacked = np.stack([s.reshape(-1, 1) for s in series])
    fit = fit_viterbi_student_t_batch(stacked)

    assert fit.fallback_indices == [0, 2]
    for index in (1, 3):
        solo_states, _ = _solo_states(series[index])
        np.testing.assert_array_equal(fit.states[index], solo_states)


def test_batch_of_one_equals_solo():
    """n=1 is the degenerate batch: same stream, same result."""
    one = _series("switch", 150, seed=99)
    fit = fit_viterbi_student_t_batch(one.reshape(1, -1, 1))
    solo_states, _ = _solo_states(one)
    assert fit.fallback_indices == []
    np.testing.assert_array_equal(fit.states[0], solo_states)


def test_engine_batch_labels_match_per_source_regime_label(tmp_path):
    """Through the engine: grouping by window length, the 40-observation
    floor, the degenerate fallback and mixed lengths all land on exactly
    the labels ``_regime_label`` produces per source."""
    torch = pytest.importorskip("torch")
    from backend.modules.engine.model_io import safe_torch_save
    from backend.modules.engine.multi_scale_trainer import (
        MultiScaleTemporalAttentionModel,
    )
    from backend.modules.engine.prediction_engine import RealPredictionEngine

    # The engine loads its checkpoint at construction (this test never
    # scores through it — only the regime path runs), so build the minimal
    # real layout test_risk_series.py established.
    torch.manual_seed(7)
    model = MultiScaleTemporalAttentionModel(
        num_sources=1, sequence_length=4, d_model=8, nhead=2, num_layers=1, dropout=0.0
    )
    checkpoint = tmp_path / "best_model.pt"
    safe_torch_save(
        {
            "model_state_dict": model.state_dict(),
            "config": {
                "sequence_length": 4, "d_model": 8, "nhead": 2,
                "num_layers": 1, "dropout": 0.0,
            },
            "sources": ["unused"],
        },
        checkpoint,
    )
    engine = RealPredictionEngine(
        model_path=str(checkpoint),
        device=torch.device("cpu"),
        config={},
    )

    specs = [
        ("short", "calm", 25),
        ("a", "switch", 120),
        ("b", "calm", 120),
        ("c", "stress", 250),
        ("d", "spiky", 250),
        ("flat", "const", 60),
        ("e", "drift", 333),
    ]
    items = []
    for code, kind, length in specs:
        values = _series(kind, length, seed=abs(hash(code)) % 9973 + length)
        finite = values[np.isfinite(values)]
        stats = {"mean": float(finite.mean()), "std": float(finite.std())}
        items.append((code, values, stats))

    batched = engine._regime_labels_batch(items)

    assert set(batched) == {code for code, _, _ in specs}
    for code, values, stats in items:
        solo = engine._regime_label(values, stats)
        assert batched[code] == solo, (
            f"regime label for {code!r}: batched {batched[code]!r} != solo {solo!r}"
        )

    # The floor and the method strings are part of the contract, not just
    # the equality: a too-short window is an unnamed regime, never a guess.
    assert batched["short"] == (None, "insufficient_history_for_regime")
    assert batched["a"][1] == "student_t_hmm_higher_variance_state"
