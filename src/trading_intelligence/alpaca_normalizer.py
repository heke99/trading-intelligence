"""Strict normalization of documented Alpaca fields, without trading admission."""

from collections import Counter
from decimal import Decimal, InvalidOperation
import json
from uuid import UUID

from .brokers import BrokerAccount, Environment
from .contracts import ContractError, currency, required
from .futures import number


NORMALIZER_VERSION = "alpaca-reference-1"


class NormalizationError(ContractError):
    pass


def _pairs(values):
    result = {}
    for key, value in values:
        if key in result:
            raise NormalizationError("duplicate_json_key")
        result[key] = value
    return result


def _constant(_value):
    raise NormalizationError("nonfinite_json_number")


def decode(payload: bytes):
    try:
        return json.loads(payload.decode("utf-8"), object_pairs_hook=_pairs,
                          parse_float=Decimal, parse_constant=_constant)
    except NormalizationError:
        raise
    except (ValueError, UnicodeError, RecursionError):
        raise NormalizationError("invalid_json") from None


def _text(value) -> str:
    try:
        return required(value, "field")
    except ContractError:
        raise NormalizationError("invalid_required_text") from None


def _uuid(value) -> str:
    try:
        return str(UUID(_text(value)))
    except (ValueError, AttributeError):
        raise NormalizationError("invalid_native_uuid") from None


def _boolean(value):
    if value is not None and type(value) is not bool:
        raise NormalizationError("invalid_boolean")
    return value


def _amount(value, *, string_only=False):
    if value is None:
        return None
    if isinstance(value, (bool, float)) or (string_only and not isinstance(value, str)):
        raise NormalizationError("invalid_decimal")
    try:
        result = Decimal(value)
        number(result, "amount")
        return str(result)
    except (ValueError, TypeError, InvalidOperation, ContractError):
        raise NormalizationError("invalid_decimal") from None


def normalize_account(value, route: BrokerAccount, expected_native_id: str) -> dict:
    if route.broker_id != "alpaca" or route.environment != Environment.PAPER:
        raise NormalizationError("unsupported_broker_route")
    if not isinstance(value, dict):
        raise NormalizationError("account_object_required")
    native_id = _uuid(value.get("id"))
    account_number = _text(value.get("account_number"))
    if native_id != _uuid(expected_native_id) or account_number != route.account_id:
        raise NormalizationError("account_identity_mismatch")
    denomination = value.get("currency")
    if denomination is not None:
        try:
            _text(denomination)
            currency(denomination)
        except ContractError:
            raise NormalizationError("invalid_currency") from None
    flags = {name: _boolean(value.get(name)) for name in (
        "trading_blocked", "account_blocked", "trade_suspended_by_user", "shorting_enabled")}
    status = _text(value.get("status"))
    reasons = []
    if status != "ACTIVE":
        reasons.append("account_not_active")
    for name in ("trading_blocked", "account_blocked", "trade_suspended_by_user"):
        if flags[name] is not False:
            reasons.append(name + ("_unknown" if flags[name] is None else "_reported"))
    if denomination is None:
        reasons.append("currency_unknown")
    return dict(native_id=native_id, account_number=account_number, status=status,
                currency=denomination, reported_cash=_amount(value.get("cash"), string_only=True),
                reported_buying_power=_amount(value.get("buying_power"), string_only=True),
                reported_equity=_amount(value.get("equity"), string_only=True), flags=flags,
                review_reasons=reasons, trading_authorized=False)


def _asset(value) -> dict:
    if not isinstance(value, dict):
        raise NormalizationError("asset_object_required")
    wire_class = value.get("class", value.get("asset_class"))
    if "class" in value and "asset_class" in value and value["class"] != value["asset_class"]:
        raise NormalizationError("conflicting_asset_class")
    wire_class = _text(wire_class)
    if wire_class != "us_equity":
        raise NormalizationError("unsupported_asset_class")
    result = dict(native_id=_uuid(value.get("id")), provider_asset_class=wire_class,
                  exchange=_text(value.get("exchange")), symbol=_text(value.get("symbol")),
                  status=_text(value.get("status")))
    result.update({name: _boolean(value.get(name)) for name in (
        "tradable", "marginable", "shortable", "easy_to_borrow", "fractionable")})
    for name in ("min_order_size", "min_trade_increment", "price_increment"):
        result[name] = _amount(value.get(name))
        if result[name] is not None and Decimal(result[name]) <= 0:
            raise NormalizationError("nonpositive_increment")
    result["canonical_target"] = None
    result["state"] = "unmapped_reference" if result["status"] == "active" and result["tradable"] is True else "restricted_reference"
    # us_equity does not establish stock vs ETF, a MIC, fixed tick or account rights.
    return result


def normalize_bundle(account_payload: bytes, assets_payload: bytes, route: BrokerAccount,
                     expected_native_id: str) -> dict:
    quarantined = []
    try:
        account = normalize_account(decode(account_payload), route, expected_native_id)
    except NormalizationError as error:
        return dict(state="quarantined", account=None, assets=[],
                    quarantined=[dict(resource="account", index=None, reason=str(error))],
                    training_ready=False, trading_authorized=False)
    try:
        values = decode(assets_payload)
        if not isinstance(values, list):
            raise NormalizationError("assets_array_required")
    except NormalizationError as error:
        return dict(state="quarantined", account=account, assets=[],
                    quarantined=[dict(resource="assets", index=None, reason=str(error))],
                    training_ready=False, trading_authorized=False)
    parsed = []
    for index, value in enumerate(values):
        try:
            parsed.append((index, _asset(value)))
        except NormalizationError as error:
            quarantined.append(dict(resource="assets", index=index, reason=str(error)))
    ids = Counter(row["native_id"] for _, row in parsed)
    symbols = Counter((row["symbol"], row["exchange"]) for _, row in parsed)
    accepted = []
    for index, row in parsed:
        if ids[row["native_id"]] > 1 or symbols[(row["symbol"], row["exchange"])] > 1:
            quarantined.append(dict(resource="assets", index=index, reason="ambiguous_asset_identity"))
        else:
            accepted.append(row)
    return dict(state="review_required" if quarantined or account["review_reasons"] else "normalized_reference",
                account=account, assets=accepted, quarantined=quarantined,
                training_ready=False, trading_authorized=False)
