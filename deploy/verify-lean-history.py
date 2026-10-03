"""Queue one fixed historical research comparison; never authorizes trading.

Run as stock-watch through systemd with its existing EnvironmentFile. Default is
preview-only; --apply fetches hourly data and persists a research comparison.
"""
import argparse,fcntl,json,os,pathlib,pwd,socket,tempfile,uuid
from datetime import datetime,timezone
from stock_watch_worker.database import connect
from stock_watch_worker.lean_contract import canonical,validate
from stock_watch_worker.systems.datasets import bitcoin_dataset
from stock_watch_worker.systems.research import register_dataset,now_iso

VERSION='e664521e08effecaea9a67e44b54ccf858675184860ad186493eb0e8f4a5856d'
START='2026-09-01T00:00:00Z';END='2026-10-01T00:00:00Z'
JOB=str(uuid.uuid5(uuid.NAMESPACE_URL,'stockwatch-lean-history-v1/'+VERSION+'/'+START+'/'+END))
DATABASE=pathlib.Path('/var/lib/stock-watch/stock-watch.db')

def queue(db,dataset):
    db.execute('BEGIN IMMEDIATE')
    try:
        existing=db.execute('SELECT dataset_id FROM lean_comparisons WHERE id=?',(JOB,)).fetchone()
        if existing:
            if existing['dataset_id']!=dataset:raise ValueError('Verification identity conflict')
        else:
            count=db.execute("SELECT count(*) FROM lean_comparisons WHERE status NOT IN ('complete','failed','canceled')").fetchone()[0]
            if count>=5:raise ValueError('Research comparison queue is full')
            now=now_iso()
            db.execute("INSERT INTO lean_comparisons(id,version_id,dataset_id,status,created_at,updated_at) VALUES (?,?,?,'queued',?,?)",(JOB,VERSION,dataset,now,now))
            db.execute('INSERT INTO system_audit(at,action,entity_id,payload_json) VALUES (?,?,?,?)',(now,'lean_create',JOB,canonical({'source':'operator historical verification','version':VERSION,'dataset':dataset,'start':START,'end':END})))
        db.commit()
    except Exception:
        db.rollback();raise

def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--apply',action='store_true');args=parser.parse_args()
    preview={'job':JOB,'version':VERSION,'start':START,'end_exclusive':END,'timeframe':'1Hour','starting_cash':300,'allocation':.5,'fast_sma':20,'slow_sma':100,'execution':'synthetic next-bar open plus dataset costs','authority':'research only; no qualification, activation or broker orders'}
    print(json.dumps(preview,indent=2),flush=True)
    if not args.apply:return
    if socket.gethostname().split('.')[0]!='a1347-m' or pwd.getpwuid(os.geteuid()).pw_name!='stock-watch':raise SystemExit('Run as the stock-watch service user on a1347-m')
    with open(str(DATABASE)+'.lean-history-verification.lock','a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        with connect(DATABASE) as db:
            existing=db.execute('SELECT id,status FROM lean_comparisons WHERE id=?',(JOB,)).fetchone()
            if existing:print(json.dumps(dict(existing)),flush=True);return
            row=db.execute('SELECT config_json FROM system_versions WHERE id=?',(VERSION,)).fetchone()
            if not row:raise ValueError('Expected immutable original trend version is missing')
            health=db.execute('SELECT * FROM lean_runner_health WHERE id=1').fetchone()
            state=json.loads(health['payload_json']) if health else {}
            if not state.get('healthy') or not health or (datetime.now(timezone.utc)-datetime.fromisoformat(health['updated_at'])).total_seconds()>60:raise ValueError('LEAN bridge is unavailable or stale')
            print('Fetching and validating hourly research data...',flush=True)
            data=bitcoin_dataset(START,END,timeframe='1Hour');validate(json.loads(row['config_json']),data)
            storage=pathlib.Path(str(DATABASE)+'.systems-data');storage.mkdir(exist_ok=True)
            with tempfile.NamedTemporaryFile(mode='w',dir=storage,prefix='lean-import-',suffix='.json',delete=False) as stream:
                stream.write(canonical(data));temporary=pathlib.Path(stream.name)
            try:dataset=register_dataset(db,temporary,storage)
            finally:temporary.unlink()
            queue(db,dataset)
            print(json.dumps({'job':JOB,'dataset':dataset,'bars':len(data['bars']),'status':'queued','limitations':data['manifest']['limitations']}),flush=True)
if __name__=='__main__':main()
