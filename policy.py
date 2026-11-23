"""Pure scaling decisions, separate from measurement and Railway I/O."""
from dataclasses import dataclass
import math


@dataclass(frozen=True)
class Policy:
    minimum: int = 1
    maximum: int = 3
    target_inflight: float = 4
    up_window: float = 10
    down_window: float = 60
    cooldown: float = 30

    def __post_init__(self):
        if not 1 <= self.minimum <= self.maximum <= 50:
            raise ValueError('Require 1 <= MIN_REPLICAS <= MAX_REPLICAS <= 50; check your plan too')
        if not math.isfinite(self.target_inflight) or self.target_inflight <= 0:
            raise ValueError('TARGET_INFLIGHT must be finite and positive')
        if any(not math.isfinite(v) or v < 0 for v in (self.up_window, self.down_window, self.cooldown)):
            raise ValueError('Time windows must be finite and nonnegative')


class Decision:
    def __init__(self, policy: Policy):
        self.policy = policy
        self.direction = None
        self.since = 0.0
        self.last_change = float('-inf')

    def reset(self):
        self.direction = None

    def changed(self, now):
        self.last_change = now
        self.reset()

    def evaluate(self, current, mean_inflight, now, *, complete=True):
        p = self.policy
        if (not isinstance(current, int) or not p.minimum <= current <= p.maximum
                or not complete or not math.isfinite(mean_inflight) or mean_inflight < 0):
            self.reset()
            return current, 'hold: incomplete or invalid observation'
        # The load endpoint is sampled across randomly routed replicas.
        desired = max(p.minimum, min(p.maximum, math.ceil(current * mean_inflight / p.target_inflight)))
        if desired == current:
            self.reset()
            return current, 'hold: within target or bounds'
        direction = 'up' if desired > current else 'down'
        if direction != self.direction:
            self.direction, self.since = direction, now
        window = p.up_window if direction == 'up' else p.down_window
        if now - self.last_change < p.cooldown:
            return current, 'hold: cooldown'
        if now - self.since < window:
            return current, 'hold: sustained-demand window'
        # One replica per decision makes changes and their cost easy to inspect.
        return current + (1 if direction == 'up' else -1), 'scale ' + direction
