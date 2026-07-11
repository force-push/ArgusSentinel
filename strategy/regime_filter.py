# strategy/regime_filter.py
from collections import deque

class RegimeFilter:
    """
    Returns True only when:
      • ATR-normalized volatility is low  (≤ atr_max)
      • ADX indicates a trending market (≥ adx_min)
    """
    def __init__(self, atr_period=14, atr_max=0.001, adx_period=14, adx_min=20):
        self.atr_period = atr_period
        self.atr_max = atr_max
        self.adx_period = adx_period
        self.adx_min = adx_min
        self._high = deque(maxlen=atr_period+2)
        self._low = deque(maxlen=atr_period+2)
        self._close = deque(maxlen=atr_period+2)

    def update(self, high, low, close):
        self._high.append(high)
        self._low.append(low)
        self._close.append(close)

        if len(self._close) < self.atr_period:
            return None   # not enough data yet

        # ----- ATR -----
        tr = [max(h-l, abs(h-pc), abs(l-pc))
              for h,l,pc in zip(list(self._high)[1:],
                                list(self._low)[1:],
                                list(self._close)[:-1])]
        atr = sum(tr[-self.atr_period:]) / self.atr_period
        atr_norm = atr / self._close[-1]

        # ----- ADX (Wilder smoothing, simplified) -----
        up = [self._high[i] - self._high[i-1] for i in range(1, len(self._high))]
        down = [self._low[i-1] - self._low[i] for i in range(1, len(self._low))]
        plus_dm = [u if u>d and u>0 else 0 for u,d in zip(up, down)]
        minus_dm = [d if d>u and d>0 else 0 for u,d in zip(up, down)]
        tr14 = sum(tr[-self.atr_period:])
        plus_di = 100 * (sum(plus_dm[-self.atr_period:]) / tr14) if tr14 else 0
        minus_di = 100 * (sum(minus_dm[-self.atr_period:]) / tr14) if tr14 else 0
        dx = (abs(plus_di - minus_di) / (plus_di + minus_di) * 100) if (plus_di+minus_di) else 0
        adx = dx   # one‑period smoothing is enough for a gate

        ok = (atr_norm <= self.atr_max) and (adx >= self.adx_min)
        return {"atr_norm": atr_norm, "adx": adx, "ok": ok}