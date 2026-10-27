"""Reproducible invented-data integration of actual open-source statistics.

Run: PYTHONPATH=src python -m trading_intelligence.quant_research_demo
"""
import json
import math
from datetime import datetime, timedelta, timezone
from .quant_research import risk_snapshot, cost_stress, paired_block_interval, superior_predictive_ability


def run():
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    rows = [[.01*math.sin(i*.7), .008*math.cos(i*.4)] for i in range(80)]
    risk = risk_snapshot(rows, available_at=[start+timedelta(days=i) for i in range(80)],
                         cutoff=start+timedelta(days=60), asset_ids=['invented-A','invented-B'],
                         weights=[.5,.5])
    # Evaluation rows are distinct from covariance fitting rows.
    gross = [(x+y)/2 for x,y in rows[60:]]
    stress = {str(cost): cost_stress(gross, [.2]*len(gross), cost_bps=cost)
              for cost in (0, 5, 20, 50)}
    comparison = paired_block_interval(stress['20']['net_returns'], [0]*len(gross),
                    block_size=4, repetitions=500, seed=27, confidence=.95)
    # All variants shown; these invented trials are NOT registered strategies.
    losses = [[-stress[str(cost)]['net_returns'][i] for cost in (5,20,50)]
              for i in range(len(gross))]
    spa = superior_predictive_ability([0]*len(gross), losses,
                    model_ids=['invented-cost-5','invented-cost-20','invented-cost-50'],
                    block_size=4, repetitions=500, seed=27)
    return dict(synthetic=True, admitted_data=False, orders=0, pilot_modified=False,
                risk=risk, cost_stress=stress, paired_interval=comparison, spa=spa,
                performance_established=False)


if __name__ == '__main__':
    print(json.dumps(run(), sort_keys=True, indent=2))
