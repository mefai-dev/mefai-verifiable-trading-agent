"""
MEFAI BNB HACK · Omni-Signal Fusion Core (pure math)

This is the Track 1 overarching feature: ONE conviction score that is the union
of every MEFAI capability. Each source (the MEFAI signal pipeline, the Brain, the
multi-agent debate, the deep whale/flow/AI composite, Kronos forecasts, cross
signals, the CMC regime and per-asset technicals, derivatives risk, ...) reports
a directional reading plus its OWN historical hit-rate. The core fuses them,
weighting each source by how much skill it has demonstrated above a coin flip, so
sources that have actually been right get more say.

This module is PURE: no I/O, no network, no DB. It takes a list of SourceReading
and returns a FusionResult. The data adapters live in fusion_providers.py so the
math can be reviewed and unit-tested in isolation.

Direction convention: +1 long, -1 short, 0 neutral.
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass, field
from typing import List, Optional


# A directional source earns full skill weight at this edge above a coin flip.
# Real trading edges sit around 0.52-0.62, so we reference a 0.15 edge (a 65
# percent hit rate) as "fully skilled" rather than the unreachable 100 percent.
SKILL_EDGE_REF = 0.15


def _now() -> float:
    return time.time()


def _clamp(x: float, lo: float, hi: float) -> float:
    # NaN fails every comparison; collapse it to the low bound so a corrupt
    # upstream value can never poison the fusion (inf saturates to hi/lo).
    if x != x:
        return lo
    return lo if x < lo else hi if x > hi else x


def _finite(x: float, default: float = 0.0) -> float:
    """Coerce NaN/inf to a safe default before it can enter the math."""
    try:
        v = float(x)
    except (TypeError, ValueError):
        return default
    return v if math.isfinite(v) else default


@dataclass
class SourceReading:
    """One source's view of a single (symbol, timeframe) decision.

    name        human label for the transcript / cockpit
    direction   -1 short, 0 neutral, +1 long
    strength    [0,1] how strong this source's conviction is
    hit_rate    [0,1] this source's own historical accuracy, or None for a
                gate-type source (regime, derivatives) that has no win/loss
                track record; gate sources are weighted by prior only
    prior       static importance multiplier (MEFAI signal is primary => higher)
    available   False means the source could not be read; it is ignored
    detail      short human explanation for the transcript
    """

    name: str
    direction: int = 0
    strength: float = 0.0
    hit_rate: Optional[float] = None
    prior: float = 1.0
    available: bool = True
    detail: str = ""

    def skill_weight(self) -> float:
        """Effective fusion weight. Directional sources earn weight only for
        skill ABOVE a coin flip: a 50 percent source contributes nothing, a
        100 percent source contributes its full prior. Gate sources (hit_rate
        None) use their prior directly."""
        if not self.available:
            return 0.0
        prior = max(0.0, _finite(self.prior, 0.0))
        if self.hit_rate is None:
            skill = 1.0
        else:
            hr = _clamp(_finite(self.hit_rate, 0.0), 0.0, 1.0)
            # Normalize edge above a coin flip against a realistic reference edge
            # so a 0.55-0.62 hit-rate carries real weight instead of being
            # crushed to near zero (the old (hr-0.5)*2 curve let gate sources,
            # which keep full prior, dominate the directional fusion).
            skill = _clamp((hr - 0.5) / SKILL_EDGE_REF, 0.0, 1.0)
        return prior * skill

    def vote(self) -> float:
        """Signed conviction in [-1, 1]."""
        d = 1 if self.direction > 0 else -1 if self.direction < 0 else 0
        return d * _clamp(_finite(self.strength, 0.0), 0.0, 1.0)


@dataclass
class SourceContribution:
    name: str
    direction: int
    strength: float
    hit_rate: Optional[float]
    weight: float
    weight_pct: float
    contribution: float   # signed share of net this source supplied
    available: bool
    detail: str


@dataclass
class FusionResult:
    direction: int           # -1 / 0 / +1
    label: str               # SHORT / NEUTRAL / LONG
    conviction: float        # [0,100]
    net: float               # [-1,1] weighted directional consensus
    agreement: float         # [0,1] weighted share agreeing with net sign
    coverage: float          # [0,1] available weight / total possible weight
    n_sources: int           # available sources that carried weight
    sources: List[SourceContribution] = field(default_factory=list)
    transcript: List[str] = field(default_factory=list)
    ts: float = field(default_factory=_now)


def _label(direction: int) -> str:
    return "LONG" if direction > 0 else "SHORT" if direction < 0 else "NEUTRAL"


def fuse(readings: List[SourceReading]) -> FusionResult:
    """Fuse all source readings into one conviction.

    net        = sum(weight * vote) / sum(directional weight)   in [-1, 1]
    direction  = sign(net)
    conviction = |net| * 100   (0 = no edge or conflict, 100 = unanimous skilled)
    agreement  = directional-weighted fraction voting the same sign as net
    coverage   = available skill-weight / total prior weight of all sources

    A source that votes NEUTRAL (direction 0) abstains: it still lowers coverage
    (it carries weight but expresses no view) but it is NOT placed in the
    conviction denominator, so a high-skill source saying "no edge" cannot
    silently dilute a real directional consensus toward zero.
    """
    # Total possible prior weight (used for coverage, includes unavailable).
    total_prior = sum(max(0.0, _finite(r.prior, 0.0)) for r in readings) or 1.0

    weighted = [(r, r.skill_weight()) for r in readings]
    active = [(r, w) for r, w in weighted if w > 0 and r.available]
    sum_w_active = sum(w for _r, w in active)
    # Only sources that actually express a direction drive the conviction.
    directional = [(r, w) for r, w in active if r.vote() != 0.0]
    sum_w_dir = sum(w for _r, w in directional)

    contributions: List[SourceContribution] = []
    transcript: List[str] = []

    if sum_w_active <= 0:
        for r in readings:
            contributions.append(
                SourceContribution(
                    name=r.name, direction=r.direction, strength=r.strength,
                    hit_rate=r.hit_rate, weight=0.0, weight_pct=0.0,
                    contribution=0.0, available=r.available, detail=r.detail,
                )
            )
        transcript.append("no source carried weight (all unavailable or no skill)")
        return FusionResult(
            direction=0, label="NEUTRAL", conviction=0.0, net=0.0,
            agreement=0.0, coverage=0.0, n_sources=0,
            sources=contributions, transcript=transcript,
        )

    coverage = _clamp(sum_w_active / total_prior, 0.0, 1.0)

    if sum_w_dir <= 0:
        # Weight exists but every voter is neutral: no directional edge.
        net = 0.0
        direction = 0
        conviction = 0.0
        agreement = 0.0
    else:
        net = sum(w * r.vote() for r, w in directional) / sum_w_dir
        direction = 1 if net > 1e-9 else -1 if net < -1e-9 else 0
        conviction = _clamp(abs(net) * 100.0, 0.0, 100.0)
        if direction != 0:
            agree_w = sum(
                w for r, w in directional
                if (r.vote() > 0) == (direction > 0)
            )
            agreement = _clamp(agree_w / sum_w_dir, 0.0, 1.0)
        else:
            agreement = 0.0

    dir_set = {id(r) for r, _w in directional}
    for r in readings:
        w = next((w for rr, w in active if rr is r), 0.0)
        is_dir = id(r) in dir_set and sum_w_dir > 0
        wpct = (w / sum_w_dir) if is_dir else 0.0
        contrib = (w * r.vote() / sum_w_dir) if is_dir else 0.0
        contributions.append(
            SourceContribution(
                name=r.name, direction=r.direction, strength=r.strength,
                hit_rate=r.hit_rate, weight=w, weight_pct=wpct,
                contribution=contrib, available=r.available, detail=r.detail,
            )
        )

    contributions.sort(key=lambda c: abs(c.contribution), reverse=True)
    transcript.append(
        f"fused {len(directional)} directional of {len(active)} weighted sources "
        f"-> {_label(direction)} conviction {conviction:.1f} (net {net:+.3f}, "
        f"agreement {agreement:.2f}, coverage {coverage:.2f})"
    )
    for c in contributions:
        if not c.available:
            transcript.append(f"  {c.name}: unavailable")
            continue
        if c.weight <= 0:
            transcript.append(
                f"  {c.name}: no skill weight (hit_rate<=0.5), ignored"
            )
            continue
        hr = f"hit {c.hit_rate:.2f}" if c.hit_rate is not None else "gate"
        if c.direction == 0:
            transcript.append(
                f"  {c.name}: NEUTRAL {hr} -> abstains (no directional view)"
                + (f" ({c.detail})" if c.detail else "")
            )
            continue
        d = _label(c.direction)
        transcript.append(
            f"  {c.name}: {d} str {c.strength:.2f} {hr} -> "
            f"w {c.weight_pct*100:.0f}% contrib {c.contribution:+.3f}"
            + (f" ({c.detail})" if c.detail else "")
        )

    return FusionResult(
        direction=direction, label=_label(direction), conviction=conviction,
        net=net, agreement=agreement, coverage=coverage,
        n_sources=len(directional),
        sources=contributions, transcript=transcript,
    )
