"""Adaptive immunity — the immunity protocol's behavioural-anomaly tier.

``protocols/immunity.md`` §Adaptive: each sucker accumulates a baseline
of its normal latency / token / cost profile; a call that deviates far
from that baseline scores high risk and is quarantined. This is the
fourth tier (Tolerance → Innate → Memory → Adaptive); Memory landed in
attack_memory.py, this completes the set.

Design, following the protocol pseudocode and invariants:

* **Sliding-window baselines** (default 200 samples, §config
  ``baseline_window_size``) of latency_ms / tokens / usd per sucker.
* **z-score composite** — how many standard deviations a call's
  predicted cost sits from the sucker's mean, squashed through a
  logistic into [0, 1] (``compute_risk``).
* **I4 cold-start is conservative** — no baseline yet ⇒ score 0.5
  (``cold_start_score``), never an early false quarantine.
* **learn()** updates the baseline AFTER execution (the protocol's
  Execute-time learning loop), so the next similar call has context.

Risk only ever *tightens*: the engine quarantines on a high score, it
never uses a low score to override Innate/Memory rejections.
"""
from __future__ import annotations

import math
import threading
from collections import deque
from dataclasses import dataclass, field

from runtime.platform.models import RiskScore

# Defaults mirror protocols/immunity.md §config adaptive.*
_DEFAULT_WINDOW = 200
_DEFAULT_THRESHOLD = 0.7
_COLD_START_SCORE = 0.5
# Need a few samples before a mean/variance is meaningful; below this
# we stay in cold-start (still I4-conservative).
_MIN_SAMPLES = 5


@dataclass
class _Baseline:
    latency: deque[float] = field(default_factory=lambda: deque(maxlen=_DEFAULT_WINDOW))
    tokens: deque[float] = field(default_factory=lambda: deque(maxlen=_DEFAULT_WINDOW))

    def add(self, latency_ms: float, tokens: float) -> None:
        self.latency.append(float(latency_ms))
        self.tokens.append(float(tokens))


def _mean_std(samples: deque[float]) -> tuple[float, float]:
    n = len(samples)
    if n == 0:
        return 0.0, 0.0
    mean = sum(samples) / n
    var = sum((x - mean) ** 2 for x in samples) / n
    return mean, math.sqrt(var)


# Floor std at this fraction of the mean. A perfectly steady skill
# (zero observed variance) shouldn't treat a 5% wobble as infinitely
# anomalous — real costs always jitter a little. 10% tolerance keeps
# cold-but-tight baselines from false-quarantining on small drift.
_REL_STD_FLOOR = 0.10
# Cap z so one wild outlier can't produce absurd composites; ~6σ is
# already "definitely anomalous" territory.
_Z_CAP = 6.0


def _abs_z(value: float, mean: float, std: float) -> float:
    eff_std = max(std, abs(mean) * _REL_STD_FLOOR)
    if eff_std <= 1e-9:
        # mean and std both ~0 (e.g. a free, instant tool): only a
        # nonzero value is surprising, and modestly so.
        return 0.0 if abs(value - mean) <= 1e-9 else 1.0
    return min(abs(value - mean) / eff_std, _Z_CAP)


def _sigmoid(x: float) -> float:
    return 1.0 / (1.0 + math.exp(-x))


class AdaptiveImmunity:
    """Per-sucker behavioural baselines + risk scoring.

    Thread-safe: ``compute_risk`` (pre-execute) and ``learn``
    (post-execute) may race across concurrent tool calls.
    """

    def __init__(
        self,
        *,
        window_size: int = _DEFAULT_WINDOW,
        quarantine_threshold: float = _DEFAULT_THRESHOLD,
        cold_start_score: float = _COLD_START_SCORE,
    ) -> None:
        self._window = max(_MIN_SAMPLES, int(window_size))
        self._cold_start = float(cold_start_score)
        # The threshold must sit ABOVE the cold-start score, or every
        # cold-start call (no baseline yet) would quarantine — and with
        # no recovery path, since a quarantined call never executes to
        # feed learn(). Floor it just above cold-start.
        self.quarantine_threshold = max(
            float(quarantine_threshold), self._cold_start + 1e-3
        )
        self._baselines: dict[str, _Baseline] = {}
        self._lock = threading.Lock()

    def _baseline_for(self, sucker_id: str) -> _Baseline:
        bl = self._baselines.get(sucker_id)
        if bl is None:
            bl = _Baseline(
                latency=deque(maxlen=self._window),
                tokens=deque(maxlen=self._window),
            )
            self._baselines[sucker_id] = bl
        return bl

    def compute_risk(
        self,
        sucker_id: str,
        *,
        predicted_latency_ms: float = 0.0,
        predicted_tokens: float = 0.0,
    ) -> RiskScore:
        """Risk in [0, 1] for an about-to-run call. Cold start ⇒
        ``cold_start_score`` (I4)."""
        # No prediction supplied (the runtime doesn't populate
        # ToolCall.predicted_cost today, so both arrive 0). A zero
        # prediction means "unknown", NOT "an instant free call" — and
        # 0 sits many sigma below any real baseline, which would flag
        # EVERY normal call as a 6σ anomaly and quarantine all traffic.
        # Treat absent prediction as cold-start (non-anomalous). The
        # tier stays inert until a real predicted cost is wired; until
        # then learn() still accumulates baselines for that future.
        if predicted_latency_ms <= 0.0 and predicted_tokens <= 0.0:
            return RiskScore(
                sucker_id=sucker_id,
                composite=self._cold_start,
                reason="no_prediction (cold_start)",
            )
        with self._lock:
            bl = self._baselines.get(sucker_id)
            n = len(bl.latency) if bl else 0
            if bl is None or n < _MIN_SAMPLES:
                return RiskScore(
                    sucker_id=sucker_id,
                    composite=self._cold_start,
                    reason=f"cold_start ({n} samples)",
                )
            lat_mean, lat_std = _mean_std(bl.latency)
            tok_mean, tok_std = _mean_std(bl.tokens)
            z_lat = _abs_z(predicted_latency_ms, lat_mean, lat_std)
            z_tok = _abs_z(predicted_tokens, tok_mean, tok_std)
        # Drive the composite off the MOST anomalous axis, not the
        # average. A tool that suddenly costs 100x tokens (a classic
        # exfil/abuse signature) or hangs (latency spike) is anomalous
        # on ONE axis; averaging two axes halved a single 6σ signal to
        # below threshold, making single-axis anomalies invisible.
        # max-of-axes with the same logistic centring: a ~3σ deviation
        # on either axis crosses 0.5, a 6σ approaches 0.95.
        z_max = max(z_lat, z_tok)
        composite = _sigmoid(z_max - 3.0)
        return RiskScore(
            sucker_id=sucker_id,
            z_score_latency=z_lat,
            z_score_tokens=z_tok,
            composite=composite,
            reason=f"z_lat={z_lat:.1f} z_tok={z_tok:.1f}",
        )

    def is_anomalous(self, score: RiskScore) -> bool:
        return score.composite >= self.quarantine_threshold

    def learn(
        self,
        sucker_id: str,
        *,
        latency_ms: float,
        tokens: float,
    ) -> None:
        """Fold an observed execution into the sucker's baseline."""
        with self._lock:
            self._baseline_for(sucker_id).add(latency_ms, tokens)

    def sample_count(self, sucker_id: str) -> int:
        with self._lock:
            bl = self._baselines.get(sucker_id)
            return len(bl.latency) if bl else 0


__all__ = ["AdaptiveImmunity"]
