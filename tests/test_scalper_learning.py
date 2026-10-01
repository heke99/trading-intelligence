"""Offline learning mechanics on fictional quotes, labels and instruments only."""
from copy import deepcopy
from decimal import Decimal, localcontext
import unittest

from trading_intelligence.common import DataError, json_bytes, load_json
from scalper_research.engine import EngineConfig, replay
from scalper_research.learning import (CaptureStrategy, FEATURE_NAMES, FilteredStrategy,
                                       collect_training_rows, fit, predict,
                                       training_rows_with_audit, validate_model)
from scalper_research.market import Quote
from scalper_research.strategy import RollingBreakout, StrategyConfig


def strategy_config(**changes):
    values = dict(lookback_quotes=2, breakout_buffer=Decimal("0"),
                  stop_distance=Decimal("2"), target_distance=Decimal("2"), max_hold_ms=10000,
                  session_start_minute_utc=0, session_end_minute_utc=1440, cooldown_ms=0)
    values.update(changes)
    return StrategyConfig(**values)


def engine_config(**changes):
    values = dict(symbol="FICTIONAL", quantity=Decimal("1"), contract_multiplier=Decimal("1"),
                  price_currency="USD", commission_per_unit_per_side=Decimal("0"),
                  slippage_price=Decimal("0"), latency_ms=1, max_quote_gap_ms=1000,
                  max_entry_spread=Decimal("5"), max_loss_currency=Decimal("10000"), max_trades=100)
    values.update(changes)
    return EngineConfig(**values)


def quotes(prices, *, times=None, spread="0"):
    times = times if times is not None else range(len(prices))
    return [Quote(time, Decimal(str(price)) - Decimal(spread) / 2,
                  Decimal(str(price)) + Decimal(spread) / 2, index + 2)
            for index, (time, price) in enumerate(zip(times, prices))]


def training_fixture():
    # A fictional separation of long and short labels checks that fitting
    # learns a relationship. It represents no market or trader performance.
    features = [[1.0, .1, .5, .8, .2, .3] for _ in range(10)]
    features += [[-1.0, .1, .5, .8, .2, .3] for _ in range(10)]
    return features, [1] * 10 + [0] * 10


def fitted_model(**changes):
    features, labels = training_fixture()
    options = dict(origin="synthetic_fixture", provenance={"source_id": "fictional_learning_fixture",
                   "strategy_sha256": "0" * 64, "execution_sha256": "1" * 64})
    options.update(changes)
    return fit(features, labels, **options)


class ScalperLearningTests(unittest.TestCase):
    def test_feature_values_use_preceding_channel_and_current_decision_quote(self):
        config = strategy_config(lookback_quotes=3, breakout_buffer=Decimal(".5"))
        long_capture = CaptureStrategy(config)
        for quote in quotes([100, 101, 103, 105], spread="2"):
            long_capture.on_quote(quote, None)
        self.assertEqual(long_capture.snapshots[(3, 5, "long")], [1.0, 1.0, .75, 1.5, 1.5, .75])
        short_capture = CaptureStrategy(config)
        for quote in quotes([103, 102, 100, 98], spread="2"):
            short_capture.on_quote(quote, None)
        self.assertEqual(short_capture.snapshots[(3, 5, "short")], [-1.0, 1.0, .75, 1.5, 1.5, .75])

    def test_future_quotes_cannot_change_a_captured_decision_feature(self):
        prefix = quotes([100, 100, 101])
        snapshots = []
        for suffix in ([Quote(3, Decimal("90"), Decimal("91"), 5)],
                       [Quote(3, Decimal("1000"), Decimal("1001"), 5)]):
            capture = CaptureStrategy(strategy_config())
            for quote in prefix + suffix:
                capture.on_quote(quote, None)
            snapshots.append(capture.snapshots[(2, 4, "long")])
        self.assertEqual(snapshots[0], snapshots[1])

    def test_features_clamp_fixed_bounds_without_future_scaler_fit(self):
        capture = CaptureStrategy(strategy_config(stop_distance=Decimal(".01")))
        for quote in quotes([100, 100000, 200000], spread="2"):
            capture.on_quote(quote, None)
        values = capture.snapshots[(2, 4, "long")]
        self.assertEqual(values, [1.0, 20.0, 20.0, 20.0, 20.0, 20.0])

    def test_capture_and_unfiltered_baseline_have_identical_simulated_behavior(self):
        rows = quotes([100, 100, 101, 101, 104, 104, 100, 100, 99, 99, 96, 96])
        config = strategy_config()
        capture = CaptureStrategy(config)
        self.assertEqual(replay(rows, capture, engine_config()),
                         replay(rows, RollingBreakout(config), engine_config()))
        self.assertGreater(len(capture.snapshots), 0)

    def test_reset_and_new_day_clear_history_but_preserve_prior_snapshots(self):
        capture = CaptureStrategy(strategy_config())
        for quote in quotes([100, 100, 101]):
            capture.on_quote(quote, None)
        before = deepcopy(capture.snapshots)
        capture.reset()
        self.assertIsNone(capture.on_quote(Quote(4, Decimal("200"), Decimal("200"), 6), None))
        self.assertIsNone(capture.on_quote(Quote(86400000, Decimal("300"), Decimal("300"), 7), None))
        self.assertEqual(capture.snapshots, before)

    def test_session_closed_quotes_do_not_warm_up_signal_history(self):
        capture = CaptureStrategy(strategy_config(session_start_minute_utc=1))
        self.assertIsNone(capture.on_quote(Quote(1, Decimal("100"), Decimal("100"), 2), None))
        self.assertIsNone(capture.on_quote(Quote(60000, Decimal("110"), Decimal("110"), 3), None))
        self.assertIsNone(capture.on_quote(Quote(60001, Decimal("120"), Decimal("120"), 4), None))
        self.assertEqual(capture.snapshots, {})
        self.assertEqual(capture.on_quote(Quote(60002, Decimal("130"), Decimal("130"), 5), None), "long")

    def test_fitting_is_deterministic_and_learns_fictional_relationship(self):
        left, right = fitted_model(), fitted_model()
        self.assertEqual(left, right)
        self.assertEqual(left["feature_names"], FEATURE_NAMES)
        features, _ = training_fixture()
        self.assertGreater(predict(left, features[0]), .8)
        self.assertLess(predict(left, features[-1]), .2)
        self.assertEqual(left["data_origin"], "synthetic_fixture")
        self.assertNotIn("trading_enabled", left)

    def test_saved_models_survive_repository_decimal_json_decoder_and_detach_provenance(self):
        provenance = {"source_id": "fictional", "nested": {"ratio": .5, "price": Decimal("1.25")}}
        model = fitted_model(provenance=provenance)
        provenance["nested"]["ratio"] = 999
        loaded = load_json(json_bytes(model))
        validate_model(loaded)
        self.assertEqual(loaded, model)
        self.assertEqual(predict(loaded, [1, .1, .5, .8, .2, .3]),
                         predict(model, [1, .1, .5, .8, .2, .3]))

    def test_model_tampering_unknown_fields_and_dimensions_fail_closed(self):
        for mutate in (lambda m: m.update(extra=True),
                       lambda m: m["coefficients"].__setitem__(0, "9"),
                       lambda m: m.update(coefficients=["0"]),
                       lambda m: m.update(feature_version=True),
                       lambda m: m.update(data_origin={}),
                       lambda m: m["fit_summary"].update(positive_count=True),
                       lambda m: m.update(bias="NaN")):
            model = fitted_model()
            mutate(model)
            with self.subTest(model=model), self.assertRaises(DataError):
                validate_model(model)

    def test_training_admission_rejects_unknown_origin_insufficient_classes_and_bad_labels(self):
        features, labels = training_fixture()
        cases = [(features[:19], labels[:19], "synthetic_fixture"),
                 (features, [1] * 16 + [0] * 4, "synthetic_fixture"),
                 (features, [True] + labels[1:], "synthetic_fixture"),
                 (features, labels, "claimed_real_verified"),
                 (features, labels, {})]
        for rows, values, origin in cases:
            with self.subTest(origin=origin), self.assertRaises(DataError):
                fit(rows, values, origin=origin, provenance={"source": "fictional"})
        with self.assertRaises(DataError):
            fitted_model(provenance={})

    def test_feature_admission_rejects_nonfinite_unbounded_and_wrong_contract_values(self):
        model = fitted_model()
        for features in ([1, 2], [True, .1, .5, .8, .2, .3],
                         [0, .1, .5, .8, .2, .3], [1, float("nan"), .5, .8, .2, .3],
                         [1, 21, .5, .8, .2, .3], [1, -.1, .5, .8, .2, .3],
                         [1, Decimal("Infinity"), .5, .8, .2, .3]):
            with self.subTest(features=features), self.assertRaises(DataError):
                predict(model, features)

    def test_filter_threshold_zero_matches_baseline_and_one_rejects_all_entries(self):
        rows = quotes([100, 100, 101, 101, 104, 104, 100, 100, 99, 99, 96, 96])
        model = fitted_model()
        baseline = replay(rows, RollingBreakout(strategy_config()), engine_config())
        accepted = FilteredStrategy(strategy_config(), model, 0)
        self.assertEqual(replay(rows, accepted, engine_config()), baseline)
        rejected = FilteredStrategy(strategy_config(), model, 1)
        report = replay(rows, rejected, engine_config())
        self.assertEqual(report["entered_trade_count"], 0)
        self.assertTrue(rejected.decisions)
        self.assertTrue(all(not decision["accepted"] for decision in rejected.decisions))

    def test_rejected_candidates_keep_base_signal_cooldown(self):
        config = strategy_config(cooldown_ms=3)
        filtered = FilteredStrategy(config, fitted_model(), 1)
        baseline = CaptureStrategy(config)
        for quote in quotes([100, 100, 101, 102, 103, 104, 105]):
            filtered.on_quote(quote, None)
            baseline.on_quote(quote, None)
        self.assertEqual(set(filtered.snapshots), set(baseline.snapshots))
        self.assertEqual([decision["decision_time_msc"] for decision in filtered.decisions], [2, 5])

    def test_filter_threshold_rejects_bool_nonfinite_and_outside_range(self):
        model = fitted_model()
        for threshold in (True, None, "0.5", float("nan"), float("inf"), -.01, 1.01):
            with self.subTest(threshold=threshold), self.assertRaises(DataError):
                FilteredStrategy(strategy_config(), model, threshold)

    def test_net_labels_include_frozen_costs_and_zero_is_negative(self):
        row_labels = []
        for commission in ("0", "1.5", "2"):
            capture = CaptureStrategy(strategy_config())
            report = replay(quotes([100, 100, 101, 101, 104, 104]), capture,
                            engine_config(commission_per_unit_per_side=Decimal(commission)))
            rows = collect_training_rows(report, capture, 6)
            self.assertEqual(len(rows), 1)
            row_labels.append(rows[0]["label"])
            self.assertEqual(rows[0]["features"], capture.snapshots[(2, 4, "long")])
        self.assertEqual(row_labels, [1, 0, 0])

    def test_outcome_at_cutoff_gap_and_open_position_are_not_admitted_labels(self):
        capture = CaptureStrategy(strategy_config())
        report = replay(quotes([100, 100, 101, 101, 104, 104]), capture, engine_config())
        audit = training_rows_with_audit(report, capture, 5)
        self.assertEqual(audit["rows"], [])
        self.assertEqual(audit["excluded"]["outcome_not_before_fit_cutoff"], 1)
        gap_capture = CaptureStrategy(strategy_config())
        gap_report = replay(quotes([100, 100, 101, 101, 104, 104], times=[0, 1, 2, 3, 100, 101]),
                            gap_capture, engine_config(max_quote_gap_ms=10))
        gap_audit = training_rows_with_audit(gap_report, gap_capture, 102)
        self.assertEqual(gap_audit["rows"], [])
        self.assertEqual(gap_audit["excluded"]["trade_quality_flags"], 1)
        open_capture = CaptureStrategy(strategy_config())
        open_report = replay(quotes([100, 100, 101, 101]), open_capture, engine_config())
        open_audit = training_rows_with_audit(open_report, open_capture, 5)
        self.assertEqual(open_audit["rows"], [])
        self.assertEqual(open_audit["excluded"]["open_position_has_no_completed_outcome"], 1)

    def test_missing_duplicate_and_invalid_chronology_labels_cannot_silently_fit(self):
        capture = CaptureStrategy(strategy_config())
        report = replay(quotes([100, 100, 101, 101, 104, 104]), capture, engine_config())
        duplicate = deepcopy(report)
        duplicate["closed_trades"].append(deepcopy(duplicate["closed_trades"][0]))
        invalid = deepcopy(report)
        invalid["closed_trades"][0]["entry_time_msc"] = 2
        missing = CaptureStrategy(strategy_config())
        for candidate, strategy in ((duplicate, capture), (invalid, capture), (report, missing)):
            with self.assertRaises(DataError):
                collect_training_rows(candidate, strategy, 6)
        with self.assertRaises(DataError):
            collect_training_rows(report, FilteredStrategy(strategy_config(), fitted_model(), 0), 6)

    def test_labels_require_hypothetical_engine_outputs_not_reported_expert_executions(self):
        capture = CaptureStrategy(strategy_config())
        report = replay(quotes([100, 100, 101, 101, 104, 104]), capture, engine_config())
        for index, mutate in enumerate((lambda r: r.update(hypothetical=False),
                       lambda r: r.update(execution_model="broker_reported_fills"),
                       lambda r: r["closed_trades"][0].update(hypothetical=False))):
            altered = deepcopy(report)
            mutate(altered)
            with self.subTest(index=index), self.assertRaises(DataError):
                collect_training_rows(altered, capture, 6)

    def test_feature_decimal_arithmetic_does_not_depend_on_callers_context(self):
        rows = quotes([100, 100, 101])
        snapshots = []
        for unusual in (False, True):
            capture = CaptureStrategy(strategy_config())
            with localcontext() as context:
                if unusual:
                    context.prec = 2
                    context.Emax = 2
                    context.Emin = -2
                for quote in rows:
                    capture.on_quote(quote, None)
                snapshots.append(capture.snapshots)
                if unusual:
                    self.assertEqual(context.prec, 2)
                    self.assertEqual(context.Emax, 2)
        self.assertEqual(snapshots[0], snapshots[1])


if __name__ == "__main__":
    unittest.main()
