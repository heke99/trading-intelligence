import importlib.util
import unittest
from datetime import datetime, timedelta, timezone
from trading_intelligence.contracts import ContractError
from trading_intelligence.quant_research import risk_snapshot, paired_block_interval, cost_stress


class StatisticalChecks(unittest.TestCase):
    def test_pairing_determinism_and_constant_difference(self):
        config = dict(block_size=2, repetitions=200, seed=7, confidence=.95)
        report = paired_block_interval([.03]*8, [.01]*8, **config)
        self.assertEqual(report, paired_block_interval([.03]*8, [.01]*8, **config))
        self.assertAlmostEqual(report['lower'], .02)
        self.assertAlmostEqual(report['upper'], .02)
        self.assertFalse(report['multiple_testing_corrected'])

    def test_null_and_losing_candidate(self):
        config = dict(block_size=2, repetitions=200, seed=7, confidence=.95)
        x = [.01, -.02, .03, -.01]*3
        self.assertEqual(paired_block_interval(x, x, **config)['upper'], 0)
        self.assertLess(paired_block_interval([v-.1 for v in x], x, **config)['upper'], 0)

    def test_invalid_bootstrap(self):
        for changes in ({'block_size': 4}, {'seed': True}, {'confidence': float('nan')}):
            args = dict(block_size=2, repetitions=100, seed=1, confidence=.95)
            with self.assertRaises(ContractError):
                paired_block_interval([0]*4, [0]*4, **{**args, **changes})

    def test_costs_and_drawdown(self):
        zero = cost_stress([.1, -.1], [1, 1], cost_bps=0)
        stressed = cost_stress([.1, -.1], [1, 1], cost_bps=100)
        self.assertAlmostEqual(zero['compounded_return'], -.01)
        self.assertAlmostEqual(zero['max_drawdown'], .1)
        self.assertLess(stressed['compounded_return'], zero['compounded_return'])
        self.assertGreater(stressed['max_drawdown'], zero['max_drawdown'])
        with self.assertRaises(ContractError):
            cost_stress([0], [-1], cost_bps=0)

    @unittest.skipUnless(importlib.util.find_spec('sklearn') and importlib.util.find_spec('numpy'),
                         'Install requirements-quant.txt for optional integration')
    def test_shrinkage_cutoff_and_risk_attribution(self):
        t = datetime(2026, 1, 1, tzinfo=timezone.utc)
        rows = [[.01, .02], [-.01, -.01], [.03, .01], [-.02, .01], [99, 99]]
        args = dict(available_at=[t+timedelta(days=i) for i in range(5)],
                    cutoff=t+timedelta(days=4), asset_ids=['A','B'], weights=[.5,.5])
        report = risk_snapshot(rows, **args)
        changed = risk_snapshot(rows[:-1]+[[-999,999]], **args)
        self.assertEqual(report, changed)
        self.assertEqual(report['observations'], 4)
        self.assertAlmostEqual(sum(report['component_volatility']), report['period_volatility'])
        self.assertTrue(0 <= report['shrinkage'] <= 1)
        with self.assertRaises(ContractError):
            risk_snapshot(rows, **{**args, 'weights': [1, 1]})
        with self.assertRaises(ContractError):
            risk_snapshot(rows, **{**args, 'cutoff': t+timedelta(days=2)})

    @unittest.skipUnless(importlib.util.find_spec('arch'), 'Install requirements-quant.txt')
    def test_actual_arch_spa_deterministic(self):
        from trading_intelligence.quant_research import superior_predictive_ability
        base = [float(i % 7)/100 for i in range(80)]
        models = [[v + .001*(i % 3-1), v + .002*(i % 5-2)] for i,v in enumerate(base)]
        args = dict(model_ids=['trial-1','trial-2'], block_size=4, repetitions=200, seed=9)
        report = superior_predictive_ability(base, models, **args)
        self.assertEqual(report, superior_predictive_ability(base, models, **args))
        self.assertTrue(all(0 <= x <= 1 for x in report['pvalues'].values()))
        self.assertFalse(report['family_completeness_verified'])
        with self.assertRaises(ContractError):
            superior_predictive_ability(base, [[v,v] for v in base], **args)
