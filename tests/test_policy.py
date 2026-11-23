import math
import unittest
from policy import Decision, Policy


class ScalingPolicyTests(unittest.TestCase):
    def setUp(self):
        self.p = Policy(minimum=1, maximum=3, target_inflight=4,
                        up_window=10, down_window=60, cooldown=30)
        self.d = Decision(self.p)

    def test_sustained_scale_up_is_one_replica(self):
        self.assertEqual(self.d.evaluate(1, 12, 0)[0], 1)
        self.assertEqual(self.d.evaluate(1, 12, 9)[0], 1)
        self.assertEqual(self.d.evaluate(1, 12, 10)[0], 2)

    def test_scale_down_waits_longer_and_moves_one_at_a_time(self):
        self.assertEqual(self.d.evaluate(3, 0, 0)[0], 3)
        self.assertEqual(self.d.evaluate(3, 0, 59)[0], 3)
        self.assertEqual(self.d.evaluate(3, 0, 60)[0], 2)

    def test_cooldown_after_confirmed_change(self):
        self.d.changed(0)
        self.d.evaluate(2, 10, 1)
        self.assertEqual(self.d.evaluate(2, 10, 29)[0], 2)
        self.assertEqual(self.d.evaluate(2, 10, 30)[0], 3)

    def test_load_recovery_resets_scale_down_window(self):
        self.d.evaluate(3, 0, 0)
        self.d.evaluate(3, 4, 40)
        self.assertEqual(self.d.evaluate(3, 0, 60)[0], 3)
        self.assertEqual(self.d.evaluate(3, 0, 119)[0], 3)
        self.assertEqual(self.d.evaluate(3, 0, 120)[0], 2)

    def test_minimum_and_maximum_are_preserved(self):
        for now in (0, 100, 200):
            self.assertEqual(self.d.evaluate(1, 0, now)[0], 1)
            self.assertEqual(self.d.evaluate(3, 100, now)[0], 3)

    def test_missing_replicas_hold_and_reset_window(self):
        self.d.evaluate(3, 0, 0)
        self.assertEqual(self.d.evaluate(3, 0, 80, complete=False)[0], 3)
        self.assertEqual(self.d.evaluate(3, 0, 81)[0], 3)
        self.assertEqual(self.d.evaluate(3, 0, 141)[0], 2)

    def test_bad_measurements_cannot_reduce_capacity(self):
        for value in (math.nan, math.inf, -1):
            self.assertEqual(self.d.evaluate(3, value, 100)[0], 3)

    def test_bounds_violation_requires_operator(self):
        self.assertEqual(self.d.evaluate(5, 0, 100)[0], 5)

    def test_invalid_configuration_rejected(self):
        for kwargs in ({'minimum':0}, {'maximum':51}, {'target_inflight':0},
                       {'target_inflight':math.nan}, {'cooldown':-1}):
            with self.assertRaises(ValueError):
                Policy(**kwargs)
