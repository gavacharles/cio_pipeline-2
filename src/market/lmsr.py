"""
lmsr.py — logarithmic market scoring rule (Hanson) automated market maker.

Thin markets are the usual way small prediction markets fail: nobody is on the
other side of a trade. An LMSR market maker always quotes a price, so a single
contractor can trade from day one. Each market opens at the nowcast's
probabilities (q0 = b * ln p0, so prices(q0) = p0 and C(q0) = 0), which means
participants are paid for knowing something the model does not.

    C(q)     = b * ln(sum_i exp(q_i / b))
    price_i  = exp(q_i / b) / sum_j exp(q_j / b)
    cost of buying d shares of i = C(q + d e_i) - C(q); a winning share pays 1 point.
    operator's worst-case loss   = b * ln(1 / p0_i) if outcome i occurs  (bounded)
"""
from __future__ import annotations

import numpy as np


def _cost(q: np.ndarray, b: float) -> float:
    z = q / b
    m = z.max()
    return float(b * (m + np.log(np.exp(z - m).sum())))


class LMSR:
    def __init__(self, prior, b: float = 100.0, q=None):
        prior = np.asarray(prior, dtype=float)
        if (prior <= 0).any():
            raise ValueError("prior probabilities must be > 0 (apply a floor first)")
        self.b = float(b)
        self.prior = prior / prior.sum()
        self.q = np.asarray(q, dtype=float) if q is not None else self.b * np.log(self.prior)

    def prices(self) -> np.ndarray:
        z = self.q / self.b
        e = np.exp(z - z.max())
        return e / e.sum()

    def quote(self, outcome: int, shares: float) -> float:
        """Points charged (negative = received) to buy `shares` of `outcome`."""
        q2 = self.q.copy()
        q2[outcome] += shares
        return _cost(q2, self.b) - _cost(self.q, self.b)

    def trade(self, outcome: int, shares: float) -> float:
        c = self.quote(outcome, shares)
        self.q[outcome] += shares
        return c

    def max_loss(self) -> float:
        return float(self.b * np.log(1 / self.prior.min()))
