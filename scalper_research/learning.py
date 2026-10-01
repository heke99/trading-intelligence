"""Causal, bounded learning for an independent offline signal-filter hypothesis.

Labels are simulated baseline trades, never expert trader executions. The
orchestrator must admit data rights, partition clocks and frozen cost context.
This module neither authenticates nor connects to a broker nor submits orders.
"""
from __future__ import annotations

from collections import Counter, deque
from decimal import Context, Decimal, InvalidOperation, localcontext
import json
import math
import re

from trading_intelligence.common import DataError, json_bytes, sha256
from .strategy import RollingBreakout, StrategyConfig

FEATURE_VERSION = 1
FEATURE_NAMES = ["side", "spread_stop", "breakout_stop", "channel_stop",
                 "signed_momentum_stop", "volatility_stop"]
FEATURE_LIMIT = 20.0
MIN_TRAIN_ROWS = 20
MIN_CLASS_ROWS = 5
MAX_TRAIN_ROWS = 10000
FIT_PARAMETERS = {"epochs": 500, "learning_rate": "0.05", "l2": "0.01",
                  "minimum_rows": MIN_TRAIN_ROWS, "minimum_class_rows": MIN_CLASS_ROWS,
                  "maximum_rows": MAX_TRAIN_ROWS,
                  "initialization": "zero_coefficients_and_bias",
                  "update": "full_batch_gradient_mean_plus_l2_on_coefficients"}
_ORIGINS = {"synthetic_fixture", "user_supplied_unverified"}
_NUMBER = re.compile(r"[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?\Z", re.ASCII)
_MODEL_FIELDS = {"schema_version", "model_type", "feature_version", "feature_names",
                 "coefficients", "bias", "fit_parameters", "fit_summary", "data_origin",
                 "provenance", "model_sha256"}


def _features(values: object) -> list[float]:
    if not isinstance(values, list) or len(values) != len(FEATURE_NAMES):
        raise DataError("LEARNING_FEATURE_DIMENSION_INVALID")
    result = []
    for value in values:
        if isinstance(value, bool) or not isinstance(value, (int, float, Decimal)):
            raise DataError("LEARNING_FEATURE_NUMBER_INVALID")
        try:
            number = float(value)
        except (OverflowError, ValueError):
            raise DataError("LEARNING_FEATURE_NUMBER_INVALID") from None
        if not math.isfinite(number) or not -FEATURE_LIMIT <= number <= FEATURE_LIMIT:
            raise DataError("LEARNING_FEATURE_RANGE_INVALID")
        result.append(number)
    if result[0] not in (-1.0, 1.0) or any(result[index] < 0 for index in (1, 2, 3, 5)):
        raise DataError("LEARNING_FEATURE_CONTRACT_INVALID")
    return result


def _coefficient(value: object) -> float:
    # Strings keep serialized models stable with the repository's Decimal JSON
    # decoder. Never stringify an arbitrary value into an accepted coefficient.
    if not isinstance(value, str) or len(value) > 80 or not _NUMBER.fullmatch(value):
        raise DataError("LEARNING_MODEL_COEFFICIENT_INVALID")
    number = float(value)
    if not math.isfinite(number) or abs(number) > 1000000:
        raise DataError("LEARNING_MODEL_COEFFICIENT_INVALID")
    return number


def _copy_provenance(value: object) -> dict:
    if not isinstance(value, dict) or not value:
        raise DataError("LEARNING_PROVENANCE_REQUIRED")
    def portable(item, depth=0):
        if depth > 20:
            raise DataError("LEARNING_PROVENANCE_INVALID")
        if isinstance(item, dict):
            if any(not isinstance(key, str) for key in item):
                raise DataError("LEARNING_PROVENANCE_INVALID")
            return {key: portable(child, depth + 1) for key, child in item.items()}
        if isinstance(item, list):
            return [portable(child, depth + 1) for child in item]
        if isinstance(item, (float, Decimal)):
            if not math.isfinite(float(item)):
                raise DataError("LEARNING_PROVENANCE_INVALID")
            return str(item)
        if item is None or type(item) in (bool, int, str):
            return item
        raise DataError("LEARNING_PROVENANCE_INVALID")
    try:
        raw = json_bytes(portable(value))
        if len(raw) > 65536:
            raise DataError("LEARNING_PROVENANCE_TOO_LARGE")
        result = json.loads(raw)
    except (TypeError, ValueError, RecursionError, UnicodeError):
        raise DataError("LEARNING_PROVENANCE_INVALID") from None
    return result


def _model_digest(model: dict) -> str:
    try:
        return sha256(json_bytes({key: value for key, value in model.items() if key != "model_sha256"}))
    except (TypeError, ValueError, RecursionError, UnicodeError):
        raise DataError("LEARNING_MODEL_SCHEMA_INVALID") from None


def validate_model(model: object) -> None:
    """Reject unknown schemas, corrupt hashes and impossible fitted summaries."""
    if (not isinstance(model, dict) or set(model) != _MODEL_FIELDS
            or type(model["schema_version"]) is not int or model["schema_version"] != 1
            or model["model_type"] != "deterministic_logistic_signal_filter_v1"
            or type(model["feature_version"]) is not int or model["feature_version"] != FEATURE_VERSION
            or model["feature_names"] != FEATURE_NAMES
            or model["fit_parameters"] != FIT_PARAMETERS
            or not isinstance(model["data_origin"], str) or model["data_origin"] not in _ORIGINS):
        raise DataError("LEARNING_MODEL_SCHEMA_INVALID")
    coefficients = model["coefficients"]
    if not isinstance(coefficients, list) or len(coefficients) != len(FEATURE_NAMES):
        raise DataError("LEARNING_MODEL_DIMENSION_INVALID")
    for coefficient in coefficients:
        _coefficient(coefficient)
    _coefficient(model["bias"])
    summary = model["fit_summary"]
    if (not isinstance(summary, dict) or set(summary) != {"row_count", "positive_count", "negative_count"}
            or any(type(value) is not int for value in summary.values())
            or not MIN_TRAIN_ROWS <= summary["row_count"] <= MAX_TRAIN_ROWS
            or summary["positive_count"] < MIN_CLASS_ROWS or summary["negative_count"] < MIN_CLASS_ROWS
            or summary["positive_count"] + summary["negative_count"] != summary["row_count"]):
        raise DataError("LEARNING_MODEL_FIT_SUMMARY_INVALID")
    # Provenance must already be a portable JSON document, not an object whose
    # serialization changes across saved-model round trips.
    if _copy_provenance(model["provenance"]) != model["provenance"]:
        raise DataError("LEARNING_MODEL_PROVENANCE_INVALID")
    if (not isinstance(model["model_sha256"], str)
            or not re.fullmatch(r"[0-9a-f]{64}", model["model_sha256"])
            or model["model_sha256"] != _model_digest(model)):
        raise DataError("LEARNING_MODEL_HASH_MISMATCH")


def _sigmoid(value: float) -> float:
    # The stable branches avoid exp overflow without modifying the score.
    if value >= 0:
        return 1.0 / (1.0 + math.exp(-value))
    exponential = math.exp(value)
    return exponential / (1.0 + exponential)


def fit(features: list[list[float]], labels: list[int], *, origin: str, provenance: dict) -> dict:
    """Fit one fixed, deterministic model on already-admitted development rows.

    Minimum row/class counts are engineering admission limits, not evidence of
    adequate statistical power. No random shuffle, normalization fitting,
    hyperparameter search, class weighting or validation/test fitting occurs.
    """
    if not isinstance(origin, str) or origin not in _ORIGINS:
        raise DataError("LEARNING_DATA_ORIGIN_INVALID")
    if not isinstance(features, list) or not isinstance(labels, list) or len(features) != len(labels):
        raise DataError("LEARNING_TRAINING_SHAPE_INVALID")
    if not MIN_TRAIN_ROWS <= len(features) <= MAX_TRAIN_ROWS:
        raise DataError("LEARNING_TRAINING_ROW_COUNT_INVALID")
    rows = [_features(row) for row in features]
    if any(type(label) is not int or label not in (0, 1) for label in labels):
        raise DataError("LEARNING_LABEL_INVALID")
    positives = sum(labels)
    negatives = len(labels) - positives
    if min(positives, negatives) < MIN_CLASS_ROWS:
        raise DataError("LEARNING_BOTH_CLASSES_REQUIRED")
    provenance_copy = _copy_provenance(provenance)
    coefficients = [0.0] * len(FEATURE_NAMES)
    bias = 0.0
    learning_rate = float(FIT_PARAMETERS["learning_rate"])
    l2 = float(FIT_PARAMETERS["l2"])
    for _ in range(FIT_PARAMETERS["epochs"]):
        gradients = [0.0] * len(FEATURE_NAMES)
        bias_gradient = 0.0
        for row, label in zip(rows, labels):
            score = bias + sum(coefficient * value for coefficient, value in zip(coefficients, row))
            error = _sigmoid(score) - label
            bias_gradient += error
            for index, value in enumerate(row):
                gradients[index] += error * value
        for index, gradient in enumerate(gradients):
            coefficients[index] -= learning_rate * (gradient / len(rows) + l2 * coefficients[index])
        bias -= learning_rate * bias_gradient / len(rows)
    model = {
        "schema_version": 1, "model_type": "deterministic_logistic_signal_filter_v1",
        "feature_version": FEATURE_VERSION, "feature_names": list(FEATURE_NAMES),
        "coefficients": [repr(coefficient) for coefficient in coefficients], "bias": repr(bias),
        "fit_parameters": dict(FIT_PARAMETERS),
        "fit_summary": {"row_count": len(rows), "positive_count": positives, "negative_count": negatives},
        "data_origin": origin, "provenance": provenance_copy,
    }
    model["model_sha256"] = _model_digest(model)
    validate_model(model)
    return model


def predict(model: dict, features: list[float]) -> float:
    validate_model(model)
    return _probability(model, _features(features))


def _probability(model: dict, features: list[float]) -> float:
    score = _coefficient(model["bias"]) + sum(
        _coefficient(coefficient) * value for coefficient, value in zip(model["coefficients"], features))
    return _sigmoid(score)


def _ratio(value: Decimal, stop: Decimal) -> float:
    ratio = min(Decimal(20), max(Decimal(-20), value / stop))
    return float(ratio)


class CaptureStrategy:
    """Collect candidate features without changing RollingBreakout decisions.

    Create a fresh instance for each replay partition. ``reset`` clears causal
    state while preserving earlier snapshots as gap/session evidence. Features
    include the current decision quote, but all channel/momentum/volatility
    values use preceding quotes only. Identical timestamp sequences are not
    admitted by the engine and therefore cannot collide in snapshot identity.
    """
    name = "captured_rolling_quote_breakout_v1"
    attribution = RollingBreakout.attribution

    def __init__(self, config: StrategyConfig):
        if not isinstance(config, StrategyConfig):
            raise DataError("LEARNING_STRATEGY_CONFIG_INVALID")
        self.config = config
        self.base = RollingBreakout(config)
        self.stop_distance = config.stop_distance
        self.target_distance = config.target_distance
        self.max_hold_ms = config.max_hold_ms
        self._history = deque(maxlen=config.lookback_quotes)
        self._day = None
        self.snapshots: dict[tuple[int, int | None, str], list[float]] = {}

    def reset(self) -> None:
        self.base.reset()
        self._history.clear()
        self._day = None

    def session_open(self, time_msc: int) -> bool:
        return self.base.session_open(time_msc)

    def on_quote(self, quote, position) -> str | None:
        with localcontext(Context(prec=1024)):
            day = quote.time_msc // 86400000
            if day != self._day:
                self._history.clear()
                self._day = day
            previous = list(self._history)
            signal = self.base.on_quote(quote, position)
            if not self.session_open(quote.time_msc):
                self._history.clear()
                return signal
            mid = (quote.bid + quote.ask) / Decimal(2)
            if signal is not None:
                if len(previous) != self.config.lookback_quotes:
                    raise DataError("LEARNING_CAUSAL_HISTORY_INCOMPLETE")
                direction = Decimal(1) if signal == "long" else Decimal(-1)
                edge = max(previous) if signal == "long" else min(previous)
                breakout = (mid - edge) * direction - self.config.breakout_buffer
                volatility = sum((abs(right - left) for left, right in zip(previous, previous[1:])), Decimal(0))
                volatility /= Decimal(len(previous) - 1)
                values = [float(direction), _ratio(quote.ask - quote.bid, self.stop_distance),
                          _ratio(breakout, self.stop_distance), _ratio(max(previous) - min(previous), self.stop_distance),
                          _ratio(direction * (previous[-1] - previous[0]), self.stop_distance),
                          _ratio(volatility, self.stop_distance)]
                key = (quote.time_msc, getattr(quote, "source_row", None), signal)
                self.snapshots[key] = _features(values)
            self._history.append(mid)
            return signal


class FilteredStrategy(CaptureStrategy):
    """Apply one frozen score threshold to candidate breakout entries.

    Rejected candidates retain the underlying candidate signal's cooldown.
    Filtering changes subsequent position availability, so evaluate the complete
    filtered engine replay; summing selected baseline outcomes is insufficient.
    """
    name = "logistic_filtered_rolling_quote_breakout_v1"

    def __init__(self, config: StrategyConfig, model: dict, threshold: float):
        super().__init__(config)
        validate_model(model)
        if type(threshold) not in (int, float) or not math.isfinite(threshold) or not 0 <= threshold <= 1:
            raise DataError("LEARNING_THRESHOLD_INVALID")
        self.model = json.loads(json_bytes(model))
        self.threshold = float(threshold)
        self.decisions: list[dict] = []

    def on_quote(self, quote, position) -> str | None:
        signal = super().on_quote(quote, position)
        if signal is None:
            return None
        key = (quote.time_msc, getattr(quote, "source_row", None), signal)
        probability = _probability(self.model, self.snapshots[key])
        # A threshold of one is the explicit reject-all control, even when
        # finite floating-point precision rounds a large score's sigmoid to 1.
        accepted = self.threshold < 1 and probability >= self.threshold
        self.decisions.append({"decision_time_msc": key[0], "source_row": key[1], "side": signal,
                               "features": list(self.snapshots[key]), "probability": probability,
                               "threshold": self.threshold, "accepted": accepted})
        return signal if accepted else None


def training_rows_with_audit(report: dict, capture: CaptureStrategy, dev_end: int) -> dict:
    """Admit only baseline closes completed strictly before the fit cutoff."""
    if type(dev_end) is not int or dev_end <= 0:
        raise DataError("LEARNING_FIT_CUTOFF_INVALID")
    if not isinstance(capture, CaptureStrategy) or isinstance(capture, FilteredStrategy):
        raise DataError("LEARNING_BASELINE_CAPTURE_REQUIRED")
    if (not isinstance(report, dict) or not isinstance(report.get("closed_trades"), list)
            or report.get("hypothetical") is not True
            or report.get("execution_model") != "delayed_quote_simulation"):
        raise DataError("LEARNING_BASELINE_REPORT_INVALID")
    rows = []
    excluded: Counter = Counter()
    seen = set()
    for trade in report["closed_trades"]:
        required = {"entry_decision_time_msc", "entry_signal_source_row", "side", "entry_time_msc",
                    "exit_time_msc", "net_pnl_currency", "quality_flags", "hypothetical"}
        if (not isinstance(trade, dict) or not required <= set(trade)
                or any(type(trade[key]) is not int for key in ("entry_decision_time_msc", "entry_time_msc", "exit_time_msc"))
                or trade["side"] not in ("long", "short") or not isinstance(trade["quality_flags"], list)
                or (trade["entry_signal_source_row"] is not None and type(trade["entry_signal_source_row"]) is not int)
                or trade["hypothetical"] is not True or not isinstance(trade["net_pnl_currency"], str)):
            raise DataError("LEARNING_BASELINE_TRADE_INVALID")
        decision, entry, exit_ = (trade[key] for key in ("entry_decision_time_msc", "entry_time_msc", "exit_time_msc"))
        if not 0 <= decision < entry < exit_:
            raise DataError("LEARNING_BASELINE_CHRONOLOGY_INVALID")
        key = (decision, trade["entry_signal_source_row"], trade["side"])
        if key in seen:
            raise DataError("LEARNING_DUPLICATE_BASELINE_LABEL")
        seen.add(key)
        if exit_ >= dev_end:
            excluded["outcome_not_before_fit_cutoff"] += 1
            continue
        if trade["quality_flags"]:
            excluded["trade_quality_flags"] += 1
            continue
        if key not in capture.snapshots:
            raise DataError("LEARNING_DECISION_SNAPSHOT_MISSING")
        try:
            if len(trade["net_pnl_currency"]) > 200:
                raise DataError("LEARNING_NET_OUTCOME_INVALID")
            net = Decimal(trade["net_pnl_currency"])
        except InvalidOperation:
            raise DataError("LEARNING_NET_OUTCOME_INVALID") from None
        if not net.is_finite():
            raise DataError("LEARNING_NET_OUTCOME_INVALID")
        rows.append({"decision_time_msc": decision, "entry_signal_source_row": trade["entry_signal_source_row"],
                     "side": trade["side"], "entry_time_msc": entry, "exit_time_msc": exit_,
                     "features": _features(capture.snapshots[key]), "label": int(net > 0),
                     "net_pnl_currency": trade["net_pnl_currency"],
                     "label_basis": "hypothetical_baseline_net_outcome_after_frozen_execution_costs"})
    if report.get("open_position") is not None:
        excluded["open_position_has_no_completed_outcome"] += 1
    labelled = set((row["decision_time_msc"], row["entry_signal_source_row"], row["side"]) for row in rows)
    # Candidates absent from closed baseline trades include engine rejections,
    # pending-entry candidates and open EOF positions; none receive fake labels.
    excluded["candidate_without_admitted_closed_label"] = len(set(capture.snapshots) - labelled)
    return {"rows": rows, "excluded": dict(sorted(excluded.items())), "candidate_count": len(capture.snapshots),
            "admitted_count": len(rows), "fit_cutoff_msc": dev_end,
            "selection_basis": "closed_baseline_trade_conditional_on_baseline_position_and_risk_state"}


def collect_training_rows(report: dict, capture: CaptureStrategy, dev_end: int) -> list[dict]:
    return training_rows_with_audit(report, capture, dev_end)["rows"]
