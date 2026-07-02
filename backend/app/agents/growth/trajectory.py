"""Baseline por conta + trajetória/velocidade — o núcleo preditivo.

O preditor central NÃO é o valor de um sinal num dia, e sim a sua *trajetória*
medida contra a linha de base histórica DAQUELA conta (cada conta tem o seu
"normal" de silêncio, frequência e tom). Este módulo só faz a matemática; a
extração dos sinais (de WhatsApp/ClickUp) vive nos coletores do agente.
"""
from __future__ import annotations

import datetime as dt
import statistics
from dataclasses import dataclass

Point = tuple[dt.date, float]


@dataclass
class SignalTrajectory:
    baseline: float       # normal histórico da conta (mediana robusta da parte antiga)
    current: float        # nível recente
    deviation: float      # (current - baseline) / (|baseline| + eps); sinal importa
    velocity: float       # variação por dia no trecho recente (mínimos quadrados)
    n_points: int         # quantos pontos sustentam a medida (entra na confiança)
    span_days: int        # alcance temporal disponível (entra na confiança)


_EPS = 1e-9


def analyze_series(points: list[Point], recent_frac: float = 0.3) -> SignalTrajectory:
    """Deriva baseline (parte antiga), nível recente, desvio e velocidade.

    points: série cronológica (data, valor) de UM sinal de UMA conta.
    recent_frac: fração final da série tratada como "recente".
    """
    pts = sorted(points, key=lambda p: p[0])
    n = len(pts)
    if n == 0:
        return SignalTrajectory(0.0, 0.0, 0.0, 0.0, 0, 0)
    if n == 1:
        v = pts[0][1]
        return SignalTrajectory(v, v, 0.0, 0.0, 1, 0)

    cut = max(1, int(n * (1 - recent_frac)))
    older = [v for _, v in pts[:cut]] or [v for _, v in pts]
    recent = [v for _, v in pts[cut:]] or [v for _, v in pts]

    baseline = statistics.median(older)
    current = statistics.fmean(recent)
    deviation = (current - baseline) / (abs(baseline) + _EPS)

    velocity = _slope_per_day(pts[cut - 1 :] if cut >= 1 else pts)
    span = (pts[-1][0] - pts[0][0]).days
    return SignalTrajectory(baseline, current, deviation, velocity, n, span)


def _slope_per_day(pts: list[Point]) -> float:
    """Inclinação (valor/dia) por mínimos quadrados sobre os pontos recentes."""
    if len(pts) < 2:
        return 0.0
    t0 = pts[0][0]
    xs = [(d - t0).days for d, _ in pts]
    ys = [v for _, v in pts]
    mx = statistics.fmean(xs)
    my = statistics.fmean(ys)
    num = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    den = sum((x - mx) ** 2 for x in xs)
    return num / den if den > _EPS else 0.0
