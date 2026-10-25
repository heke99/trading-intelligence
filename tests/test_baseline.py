"""Synthetic frozen baseline/protocol tests; no LEAN or performance claim."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime,timedelta,timezone
from decimal import localcontext,ROUND_DOWN
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from trading_intelligence.baseline import BaselineStore,baseline_demo
from trading_intelligence.contracts import ContractError,EvidenceIntegrityError,RecordConflict
from trading_intelligence.market_data import MarketDataStore
from trading_intelligence.lean_export import export_bundle,verify_bundle,encoded,sha

NOW=datetime(2026,1,20,tzinfo=timezone.utc)
DAYS=['2026-01-05','2026-01-06','2026-01-07','2026-01-08','2026-01-09','2026-01-12','2026-01-13']
PARTITIONS={'train':{'start':DAYS[0],'end':DAYS[1]},'validation':{'start':DAYS[2],'end':DAYS[4]},'final_test':{'start':DAYS[5],'end':DAYS[6]}}
COSTS={'commission_per_order':'1','spread_bps':'2','slippage_bps':'1','latency_seconds':1}

class BaselineTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.path=Path(self.tmp.name);self.fixture=self.path/'fixture'
        baseline_demo(self.fixture);self.bundle=self.fixture/'bundle'
        self.database=self.path/'protocol.sqlite';self.now=NOW
        self.s=BaselineStore(self.database,clock=lambda:self.now);self.addCleanup(self.s.close)
        self.freeze();self.experiment();self.s.register_trial(trial_id='trial',experiment_id='experiment',candidate_id='candidate')

    def freeze(self,**changes):
        args=dict(baseline_id='baseline',universe=['baseline-listing'],lookback=2,costs=COSTS)
        args.update(changes);return self.s.freeze_baseline(**args)

    def experiment(self,**changes):
        args=dict(experiment_id='experiment',baseline_id='baseline',bundle_directory=self.bundle,partitions=PARTITIONS,primary_metric='future_net_return')
        args.update(changes);return self.s.register_experiment(**args)

    def evaluate(self,**changes):
        args=dict(trial_id='trial',bundle_directory=self.bundle,partition='validation')
        args.update(changes);return self.s.evaluate_trial(**args)

    def reexport(self,directory):
        with MarketDataStore(self.fixture/'market.sqlite') as store:
            export_bundle(store,'baseline-fixture','baseline-listing',DAYS,as_of=NOW,directory=directory,clock=lambda:NOW)
        return directory

    def test_frozen_rule_produces_targets_and_explicit_abstentions_not_fills(self):
        r=self.evaluate()
        self.assertEqual(len(r['decisions']),3)
        self.assertEqual(r['decisions'][0]['target_weight'],'1')
        self.assertEqual(r['decisions'][-1]['reason'],'outside_evaluation_partition')
        intent=r['decisions'][0]['intent']
        self.assertEqual(intent['session_date'],DAYS[3]);self.assertFalse(intent['is_fill'])
        self.assertFalse(r['performance_computed']);self.assertFalse(r['costs_applied']);self.assertFalse(r['lean_runtime_verified'])

    def test_baseline_and_experiment_are_immutable(self):
        with self.assertRaises(RecordConflict):self.freeze(lookback=3)
        with self.assertRaises(RecordConflict):self.experiment(primary_metric='changed after outcomes')
        with self.assertRaises(ContractError):self.freeze(baseline_id='bad',universe=['another'],lookback=0)
        with self.assertRaises(ContractError):self.freeze(baseline_id='bad',costs=dict(COSTS,commission_per_order=1.0))

    def test_chronology_and_label_overlap_are_rejected(self):
        p=json.loads(json.dumps(PARTITIONS));p['train']['end']=DAYS[2]
        with self.assertRaises(ContractError):self.experiment(experiment_id='overlap',partitions=p)
        with self.assertRaises(ContractError):self.experiment(experiment_id='labels',label_horizon_days=1)
        with self.assertRaises(ContractError):self.s.register_trial(trial_id='missing',experiment_id='not-registered',candidate_id='c')

    def test_register_and_evaluate_cannot_backdate_operational_clock(self):
        self.now=NOW-timedelta(seconds=1)
        with self.assertRaises(ContractError):self.evaluate()
        with self.assertRaises(ContractError):self.s.register_trial(trial_id='backdated',experiment_id='experiment',candidate_id='c')

    def test_final_period_consumption_survives_new_ids_and_registry_restart(self):
        first=self.evaluate(partition='final_test')
        self.assertEqual(first,self.evaluate(partition='final_test'))
        self.experiment(experiment_id='renamed')
        self.s.register_trial(trial_id='renamed',experiment_id='renamed',candidate_id='different')
        with self.assertRaises(ContractError):self.evaluate(trial_id='renamed',partition='final_test')
        with BaselineStore(self.database,clock=lambda:NOW) as reopened:
            with self.assertRaises(ContractError):reopened.evaluate_trial(trial_id='renamed',bundle_directory=self.bundle,partition='final_test')

    def test_overlapping_final_period_is_consumed_even_when_bounds_change(self):
        self.evaluate(partition='final_test')
        p=json.loads(json.dumps(PARTITIONS));p['final_test']['start']=DAYS[4];p['validation']['end']=DAYS[3]
        self.experiment(experiment_id='overlap',partitions=p)
        self.s.register_trial(trial_id='overlap',experiment_id='overlap',candidate_id='c')
        with self.assertRaises(ContractError):self.evaluate(trial_id='overlap',partition='final_test')

    def test_failed_final_evaluation_does_not_restore_untouched_status(self):
        with patch.object(self.s,'_decisions',side_effect=ContractError('invented failed evaluation')):
            with self.assertRaises(ContractError):self.evaluate(partition='final_test')
        self.s.register_trial(trial_id='retry-new-id',experiment_id='experiment',candidate_id='new')
        with self.assertRaises(ContractError):self.evaluate(trial_id='retry-new-id',partition='final_test')

    def test_concurrent_distinct_trials_cannot_both_consume_final_period(self):
        self.s.register_trial(trial_id='second',experiment_id='experiment',candidate_id='second')
        barrier=threading.Barrier(2)
        def work(trial):
            with BaselineStore(self.database,clock=lambda:NOW) as store:
                barrier.wait(timeout=5)
                try:store.evaluate_trial(trial_id=trial,bundle_directory=self.bundle,partition='final_test');return 'ok'
                except ContractError:return 'blocked'
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures=[pool.submit(work,x) for x in ('trial','second')]
            self.assertEqual(sorted(x.result(timeout=10) for x in futures),['blocked','ok'])

    def test_record_integrity_and_registered_dataset_binding(self):
        self.s.db.execute("UPDATE baseline_experiments SET payload='{}'");self.s.db.commit()
        with self.assertRaises(EvidenceIntegrityError):self.evaluate()

    def test_modified_but_internally_rehashed_bundle_cannot_replace_trial_data(self):
        manifest_path=self.bundle/'manifest.json'
        manifest=json.loads(manifest_path.read_text());manifest['listing']['mic']='XNAS'
        manifest_path.write_bytes(encoded(manifest));verify_bundle(self.bundle)
        with self.assertRaises(RecordConflict):self.evaluate()

    def test_missed_next_open_cannot_skip_forward_to_later_open(self):
        with MarketDataStore(self.fixture/'market.sqlite') as store:
            row=store.db.execute("SELECT e.evidence_id,r.payload FROM evidence_versions e JOIN raw_objects r USING(sha256) WHERE e.record_id=?",('bar-'+DAYS[2],)).fetchone()
            late=datetime(2026,1,8,15,tzinfo=timezone.utc)
            store.import_record(source_id='baseline-fixture',record_id='bar-'+DAYS[2],revision_id='2',payload=row['payload'],
                published_at=datetime(2026,1,7,21,tzinfo=timezone.utc),received_at=late,processed_at=late+timedelta(seconds=1),correction_of=row['evidence_id'])
        directory=self.reexport(self.path/'late')
        self.experiment(experiment_id='late',bundle_directory=directory)
        self.s.register_trial(trial_id='late',experiment_id='late',candidate_id='late')
        r=self.evaluate(trial_id='late',bundle_directory=directory)
        self.assertEqual(r['decisions'][0]['reason'],'missed_next_session_open')
        self.assertIsNone(r['decisions'][0]['intent'])

    def test_latency_that_misses_next_open_abstains(self):
        self.freeze(baseline_id='slow',costs=dict(COSTS,latency_seconds=86400))
        self.experiment(experiment_id='slow',baseline_id='slow')
        self.s.register_trial(trial_id='slow',experiment_id='slow',candidate_id='slow')
        r=self.evaluate(trial_id='slow')
        self.assertEqual(r['decisions'][0]['reason'],'missed_next_session_open')
        self.assertTrue(all(x['intent'] is None for x in r['decisions']))

    def test_late_known_split_resets_crossing_lookback(self):
        with MarketDataStore(self.fixture/'market.sqlite') as store:
            body=dict(kind='split',listing_id='baseline-listing',date=DAYS[1],start=DAYS[1]+'T14:30:00Z',end=DAYS[1]+'T21:00:00Z',
                currency='USD',values={'new_shares':'2','old_shares':'1'})
            late=datetime(2026,1,7,21,tzinfo=timezone.utc)
            store.import_record(source_id='baseline-fixture',record_id='late-split',revision_id='1',payload=json.dumps(body).encode(),
                published_at=late,received_at=late,processed_at=late+timedelta(seconds=1))
        directory=self.reexport(self.path/'action')
        self.freeze(baseline_id='lookback3',lookback=3)
        self.experiment(experiment_id='action',baseline_id='lookback3',bundle_directory=directory)
        self.s.register_trial(trial_id='action',experiment_id='action',candidate_id='action')
        r=self.evaluate(trial_id='action',bundle_directory=directory)
        self.assertEqual(r['decisions'][0]['reason'],'warmup')
        self.assertEqual(r['decisions'][1]['action'],'target')

    def test_decimal_context_does_not_change_rule_decisions(self):
        first=self.evaluate()
        self.s.register_trial(trial_id='other',experiment_id='experiment',candidate_id='same-rule')
        with localcontext() as ctx:
            ctx.prec=2;ctx.rounding=ROUND_DOWN
            second=self.evaluate(trial_id='other')
        self.assertEqual(first['decisions'],second['decisions'])

    def test_repeatable_demo_and_no_order_engine_claim(self):
        first=baseline_demo(self.fixture);self.assertEqual(first,baseline_demo(self.fixture))
        self.assertTrue(first['renamed_trial_cannot_reset_final_test'])
        self.assertGreater(first['validation_intents'],0)
        self.assertFalse(first['lean_runtime_verified']);self.assertFalse(first['performance_computed'])

    def test_future_close_cannot_change_earlier_validation_targets(self):
        before=self.evaluate()['decisions']
        with MarketDataStore(self.fixture/'market.sqlite') as store:
            row=store.db.execute("SELECT e.evidence_id,r.payload FROM evidence_versions e JOIN raw_objects r USING(sha256) WHERE e.record_id=?",('bar-'+DAYS[-1],)).fetchone()
            body=json.loads(row['payload'])
            body['values'].update(open='999',high='999',low='999',close='999')
            late=datetime(2026,1,14,tzinfo=timezone.utc)
            store.import_record(source_id='baseline-fixture',record_id='bar-'+DAYS[-1],revision_id='2',payload=json.dumps(body).encode(),
                published_at=late,received_at=late,processed_at=late,correction_of=row['evidence_id'])
        directory=self.reexport(self.path/'future')
        self.experiment(experiment_id='future',bundle_directory=directory)
        self.s.register_trial(trial_id='future',experiment_id='future',candidate_id='future')
        self.assertEqual(before,self.evaluate(trial_id='future',bundle_directory=directory)['decisions'])
