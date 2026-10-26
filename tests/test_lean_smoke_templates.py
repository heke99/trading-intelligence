"""Structural/offline template checks, never a LEAN runtime assertion."""
import ast
from pathlib import Path
import unittest
from trading_intelligence.lean_smoke_templates import make_config

class TemplateTests(unittest.TestCase):
    def test_config_is_backtest_local_and_keyless(self):
        config=make_config()
        self.assertFalse(config['live-mode']);self.assertEqual(config['environment'],'backtesting')
        self.assertEqual(config['algorithm-language'],'Python');self.assertEqual(config['api-access-token'],'')
        self.assertNotIn('live-mode-brokerage',config)
        self.assertEqual(config['parameters']['observer_output'],'/Smoke/output/observer-evidence.json')
    def test_paths_are_explicit_absolute(self):
        for path in ['relative','/work/../etc']:
            with self.assertRaises(ValueError):make_config(path)
    def test_template_compiles_and_has_no_order_calls(self):
        import trading_intelligence.lean_smoke_templates as package
        text=(Path(package.__file__).parent/'observer_algorithm.py').read_text();tree=ast.parse(text)
        forbidden={'market_order','limit_order','set_holdings','liquidate','add_equity','add_forex','add_future'}
        for node in ast.walk(tree):
            if isinstance(node,ast.Call) and isinstance(node.func,ast.Attribute):self.assertNotIn(node.func.attr,forbidden)
        self.assertIn('point.end_time=point.time',text)
        self.assertIn('security.is_tradable=False',text)
        self.assertIn('exact_observations_match',text)

    def test_config_parameter_names_match_algorithm(self):
        import trading_intelligence.lean_smoke_templates as package
        tree=ast.parse((Path(package.__file__).parent/'observer_algorithm.py').read_text())
        names={node.args[0].value for node in ast.walk(tree) if isinstance(node,ast.Call) and isinstance(node.func,ast.Attribute) and node.func.attr=='get_parameter'}
        self.assertEqual(names,set(make_config()['parameters']))

    def test_config_keeps_image_reference_data_and_output_local(self):
        config=make_config()
        self.assertEqual(config['data-folder'],'/Lean/Data')
        self.assertEqual(config['composer-dll-directory'],'/Lean/Launcher/bin/Debug')
        self.assertEqual(config['object-store-root'],'/Smoke/output/storage')
        self.assertTrue(config['close-automatically'])
        self.assertNotIn('python-dll',config)
