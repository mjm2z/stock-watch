import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from stock_watch_worker.database import connect, apply_migrations
from stock_watch_worker.systems.discovery import require_assessment_inputs, run, templates
from stock_watch_worker.systems.research import register_dataset, register_version


class StockAssessmentTests(unittest.TestCase):
    def data(self):
        return {'asset': 'stocks', 'schema_version': 1,
                'manifest': {'provider': 'fixture', 'venue': 'fixture',
                             'corporate_actions_verified': True,
                             'point_in_time_membership': True, 'point_in_time_sectors': True},
                'bars': [{'symbol': 'ABC', 'at': '2026-01-02T21:00:00Z',
                          'available_at': '2026-01-02T21:00:00Z', 'eligible': True,
                          'sector': 'Technology', 'open': 10, 'high': 10, 'low': 10, 'close': 10}]}

    def test_assertions_must_be_boolean_and_membership_is_per_bar(self):
        require_assessment_inputs(self.data())
        for field in ('corporate_actions_verified', 'point_in_time_membership', 'point_in_time_sectors'):
            for value in (None, False, 'true', 1):
                with self.subTest(field=field, value=value):
                    data=self.data();data['manifest'][field]=value
                    with self.assertRaisesRegex(ValueError, 'Stock assessment blocked'):
                        require_assessment_inputs(data)
        for value in (None, 'false', 1):
            data=self.data();data['bars'][0]['eligible']=value
            with self.assertRaisesRegex(ValueError, 'per-bar'):
                require_assessment_inputs(data)
        data=self.data();data['bars'][0]['eligible']=False
        require_assessment_inputs(data)

    def test_bitcoin_does_not_require_stock_evidence(self):
        require_assessment_inputs({'asset': 'bitcoin'})

    def test_ineligible_frozen_stock_evidence_cannot_reuse_previous_pass(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);db=connect(root/'db');apply_migrations(db)
            try:
                version=register_version(db,next(templates('stocks'))[1])
                data=self.data();data['manifest']['corporate_actions_verified']=False
                source=root/'source.json';source.write_text(json.dumps(data))
                dataset=register_dataset(db,source,root/'datasets')
                now=datetime(2026,9,27,tzinfo=timezone.utc)
                with db:
                    db.execute("INSERT INTO discovery_batches(id,created_at,updated_at) VALUES ('batch',?,?)",(now.isoformat(),now.isoformat()))
                    for identifier,status in (('prior','completed'),('pending','queued')):
                        db.execute("INSERT INTO discovery_trials(id,batch_id,version_id,asset,policy_id,budget,status,created_at,dataset_id,result_json) VALUES (?,'batch',?,'stocks',1,'300',?,?,?,?)",
                                   (identifier,version,status,now.isoformat(),dataset if status=='completed' else None,'{"passed":true}'))
                with patch('stock_watch_worker.systems.discovery.schedule',return_value='batch'), \
                     patch('stock_watch_worker.systems.discovery.backfill'), \
                     patch('stock_watch_worker.systems.discovery.prepare_data',return_value=dataset), \
                     patch('stock_watch_worker.systems.discovery.scenario') as replay:
                    run(db,root/'db',seconds=5,now=now)
                    replay.assert_not_called()
                row=db.execute("SELECT status,error FROM discovery_trials WHERE id='pending'").fetchone()
                self.assertEqual(row['status'],'blocked')
                self.assertIn('corporate-action',row['error'])
                self.assertEqual(db.execute('SELECT COUNT(*) FROM discovery_scenarios').fetchone()[0],0)
                self.assertEqual(db.execute('SELECT COUNT(*) FROM system_deployments').fetchone()[0],0)
                self.assertEqual(db.execute("SELECT result_json FROM discovery_trials WHERE id='prior'").fetchone()[0],'{"passed":true}')
            finally:
                db.close()
