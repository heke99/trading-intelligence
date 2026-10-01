"""Evidence and data requirements, not executable replicas of named traders."""
from __future__ import annotations


def strategy_requirements() -> dict:
    """Explain why a quote-only hypothesis cannot claim expert imitation.

    The lists identify necessary evidence, not sufficient algorithm definitions.
    Discretionary descriptions have not supplied validated numerical triggers.
    Sources are references for human review; their content is not training data.
    """
    return {
        "schema_version": 1, "training_ready": False, "trading_enabled": False,
        "expert_trader_imitation_verified": False,
        "implemented_hypothesis": {
            "name": "logistic_filtered_rolling_quote_breakout_v1",
            "attribution": "independent research hypothesis",
            "input_fields": ["time_msc", "bid", "ask"],
            "label_basis": "hypothetical closed baseline trades after assumed execution costs",
            "implements_named_trader_strategy": False,
        },
        "traders": [
            {
                "name": "Fabio Valentini", "evidence_type": "publisher_teaching_description",
                "source": "https://www.chartfanatics.com/strategies/auction-market-strategy",
                "described_setups": ["trend continuation outside balance", "failed breakout returning toward balance POC"],
                "required_market_data": ["matched futures contract and tick size", "timestamped bid/ask",
                                         "volume by price and session", "trade tape with aggressor classification",
                                         "orderflow and profile observations available at each decision"],
                "missing_rule_definitions": ["objective balance boundary", "profile construction and LVN thresholds",
                                             "aggression threshold", "entry/exit invalidation details", "position scaling rules"],
                "required_expert_labels": ["complete entry/exit/partial fills with clock and costs",
                                           "decision annotations and reasons", "no-trade observations and rule version"],
                "complete_fill_history_verified": False, "quote_only_input_sufficient": False,
            },
            {
                "name": "Sivakumar Jayachandran", "alias": "Scalper Siva",
                "evidence_type": "instructor_catalog_and_course_partner_description",
                "sources": ["https://www.elearnmarkets.com/expert/sivakumar-jayachandran",
                            "https://newsletter.upsurge.club/p/2-candle-theory-options-strategies"],
                "described_setups": ["separate OI and options teaching variants; exact versions must be reconciled"],
                "required_market_data": ["underlying and exact option contract/strike/expiry", "timestamped option bid/ask",
                                         "historical option chain and OI observation/publication times",
                                         "source-defined price/volume candles and RSI", "contract multiplier and all costs"],
                "missing_rule_definitions": ["selected strategy and dated version", "OI source and update delay",
                                             "candle/volume units", "exact long/short confirmation and sizing rules"],
                "required_expert_labels": ["complete personal fills with verified timezone",
                                           "decision annotations and no-trade observations", "partials and all fees"],
                "complete_fill_history_verified": False, "quote_only_input_sufficient": False,
            },
        ],
        "acceptance_boundary": "a fitted independent quote filter is not proof of an expert strategy or market edge",
    }
