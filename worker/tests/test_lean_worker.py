import json,sqlite3,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from stock_watch_worker.lean_worker import tick
from stock_watch_worker.systems.engine import SystemConfig,canonical,digest
class LeanWorkerTests(unittest.TestCase):
    def test_uncertain_submission_reconciles_stable_id(self):
        with tempfile.TemporaryDirectory() as temp:
            folder=Path(temp);db=sqlite3.connect(':memory:');db.row_factory=sqlite3.Row
            migrations=Path(__file__).resolve().parents[1]/'migrations'
            for name in ('016_systems.sql','027_lean_comparisons.sql'):db.executescript((migrations/name).read_text())
            config={'asset':'bitcoin','template':'trend','fast':5,'slow':8,'entry':10,'exit':5,'allocation':.5}
            data={'schema_version':1,'asset':'bitcoin','manifest':{'provider':'fixture','venue':'fixture','timeframe':'1Hour','fidelity':'bar_approximation'},'bars':[{'symbol':'BTC/USD','at':'2020-01-01T01:00:00Z','available_at':'2020-01-01T01:00:00Z','open':100,'high':101,'low':99,'close':100,'volume':1}]}
            source=folder/'dataset.json';source.write_text(canonical(data))
            db.execute('INSERT INTO system_versions VALUES (?,?,?,?,?,?,?)',('v','bitcoin','trend',canonical(config),SystemConfig(**config).sha256,'now',''))
            db.execute('INSERT INTO system_datasets VALUES (?,?,?,?,?,?)',('d','bitcoin',str(source),digest(data),canonical(data['manifest']),'now'))
            job='11111111-1111-4111-8111-111111111111';db.execute("INSERT INTO lean_comparisons(id,version_id,dataset_id,status,created_at,updated_at) VALUES (?, 'v','d','queued','now','now')",(job,));db.commit()
            submissions=[];exists=False
            def remote(config,message):
                nonlocal exists
                if message['action']=='health':return {'configured':True,'healthy':True}
                if message['action']=='status':return {'status':'running' if exists else 'missing'}
                submissions.append(message['id']);exists=True;raise ConnectionError('Uncertain acknowledgement')
            with patch('stock_watch_worker.lean_worker.remote',side_effect=remote):
                tick(db,folder,{'host':'fixture'});tick(db,folder,{'host':'fixture'})
            self.assertEqual(submissions,[job]);self.assertEqual(db.execute('SELECT status FROM lean_comparisons').fetchone()[0],'lean')
            db.close()
