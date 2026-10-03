"""Background LEAN bridge; no broker credentials are sent to the research runner."""
import argparse,fcntl,hashlib,json,os,subprocess,time,shutil
from pathlib import Path
from datetime import datetime,timezone
from .database import connect
from .lean_contract import CONTRACT,MAX_INPUT,canonical,compare,validate
from .systems.engine import replay,SystemConfig

def now():return datetime.now(timezone.utc).isoformat()
def settings():
    path=Path('/etc/stock-watch-lean/lean-runner.json')
    if not path.is_file():return None
    value=json.loads(path.read_text())
    if value.get('host')!='lean-submit@192.168.4.33':raise ValueError('Unexpected LEAN runner host')
    return value

def remote(config,message):
    process=subprocess.run(['ssh','-T','-o','BatchMode=yes','-o','ConnectTimeout=5','-o','StrictHostKeyChecking=yes','-o','UserKnownHostsFile=/etc/stock-watch-lean/lean_known_hosts','-i','/etc/stock-watch-lean/lean_runner_ed25519',config['host'],'stockwatch-lean'],input=canonical(message).encode(),stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,timeout=60)
    if process.returncode:raise ConnectionError('LEAN runner connection unavailable')
    if len(process.stdout)>MAX_INPUT+1048576:raise ValueError('Runner response exceeds limit')
    response=json.loads(process.stdout)
    if response.get('error'):raise ValueError(response['error'])
    return response

def save(path,value):
    temporary=path.with_suffix('.tmp');temporary.write_text(canonical(value));temporary.replace(path)

def tick(db,folder,config):
    if not config:
        health={'configured':False,'healthy':False,'error':'LEAN runner is not configured'}
    else:
        try:
            health=remote(config,{'action':'health'})
            if config.get('expected_image') and health.get('image')!=config['expected_image']:health={'configured':True,'healthy':False,'error':'Runner image differs from the reviewed pin'}
        except Exception:health={'configured':True,'healthy':False,'error':'LEAN runner unreachable; queued work retained'}
    with db:db.execute('INSERT OR REPLACE INTO lean_runner_health VALUES (1,?,?)',(now(),canonical(health)))
    row=db.execute("SELECT * FROM lean_comparisons WHERE status NOT IN ('complete','failed','canceled') ORDER BY created_at LIMIT 1").fetchone()
    if not row:return
    job=row['id']
    def change(status,**fields):
        with db:db.execute('UPDATE lean_comparisons SET status=?,updated_at=?'+''.join(','+key+'=?' for key in fields)+' WHERE id=?',(status,now(),*fields.values(),job))
    def canceled():return bool(db.execute('SELECT cancel_requested FROM lean_comparisons WHERE id=?',(job,)).fetchone()[0])
    if canceled() and row['status'] in ('queued','baseline'):
        change('canceled',finished_at=now());return
    if not health.get('healthy'):return
    try:
        directory=folder/job;directory.mkdir(parents=True,exist_ok=True,mode=0o700)
        baseline_path=directory/'baseline.json';bundle_path=directory/'bundle.json'
        if row['status'] in ('queued','baseline'):
            retained=sum(p.stat().st_size for p in folder.rglob('*') if p.is_file())
            if retained+512*1024**2>10*1024**3:raise ValueError('Comparison artifact storage full; retain or remove completed evidence before retrying')
            version=db.execute('SELECT * FROM system_versions WHERE id=?',(row['version_id'],)).fetchone()
            dataset=db.execute('SELECT * FROM system_datasets WHERE id=?',(row['dataset_id'],)).fetchone()
            source=Path(dataset['path'])
            if source.stat().st_size>MAX_INPUT:raise ValueError('Dataset exceeds LEAN input bound')
            raw=source.read_bytes()
            if hashlib.sha256(raw).hexdigest()!=dataset['sha256']:raise ValueError('Dataset checksum mismatch')
            data=json.loads(raw);params=json.loads(version['config_json']);validate(params,data)
            strategy=SystemConfig(**params)
            if strategy.sha256!=version['config_sha256']:raise ValueError('Version checksum mismatch')
            change('baseline',started_at=row['started_at'] or now())
            decisions=[]
            started=time.monotonic()
            def stop():
                if time.monotonic()-started>1800:raise ValueError('Baseline time limit exceeded')
                return canceled()
            baseline=replay(strategy,data,starting_cash=300,canceled=stop,inspect_decision=lambda symbol,history,action,reason:decisions.append({'at':history[-1]['at'],'action':action}))
            baseline['decisions']=decisions
            bundle={'contract':CONTRACT,'config':params,'data':data,'dataset_sha256':dataset['sha256'],'config_sha256':strategy.sha256,'starting_cash':300}
            save(baseline_path,baseline);save(bundle_path,bundle)
            change('transferring',baseline_path=str(baseline_path),request_sha256=hashlib.sha256(canonical(bundle).encode()).hexdigest())
        if canceled():
            status=remote(config,{'action':'status','id':job})
            if status['status']!='missing':remote(config,{'action':'cancel','id':job})
            if status['status'] in ('missing','canceled','failed','complete'):change('canceled',finished_at=now())
            return
        status=remote(config,{'action':'status','id':job})
        if status['status']=='missing':
            if row['status'] in ('lean','comparing'):raise ValueError('Remote evidence expired or was lost; create a new comparison')
            status=remote(config,{'action':'submit','id':job,'bundle':json.loads(bundle_path.read_text())})
        if status['status'] in ('failed','canceled'):change(status['status'],error=status.get('error'),finished_at=now());return
        if status['status']!='complete':change('lean');return
        change('comparing')
        response=remote(config,{'action':'result','id':job});lean=response['result']
        if config.get('expected_image') and response.get('image')!=config['expected_image']:raise ValueError('Result image differs from reviewed pin')
        bundle=json.loads(bundle_path.read_text());baseline=json.loads(baseline_path.read_text())
        for key in ('dataset_sha256','config_sha256'):
            if lean.get(key)!=bundle[key]:raise ValueError('LEAN result provenance mismatch')
        if response.get('sha256')!=hashlib.sha256(canonical(bundle).encode()).hexdigest():raise ValueError('Remote request checksum mismatch')
        report=compare(baseline,lean,bundle['data'].get('quantity_increment',1e-9))
        report.update({'id':job,'image':response['image'],'dataset_sha256':bundle['dataset_sha256'],'config_sha256':bundle['config_sha256'],'baseline':baseline,'lean':lean,'limitations':list(dict.fromkeys(bundle['data']['manifest'].get('limitations',[])+baseline.get('warnings',[]))),'promotion_ready':False})
        result_path=directory/'report.json';save(result_path,report)
        for offset in range(0,len(report['differences']),100):save(directory/f'differences-{offset//100}.json',report['differences'][offset:offset+100])
        summary={k:v for k,v in report.items() if k not in ('baseline','lean','differences')}
        summary['differences']=report['differences'][:100]
        summary['stored_difference_count']=len(report['differences'])
        for key in ('baseline','lean'):
            result=report[key];curve=result['equity_curve'];stride=max(1,(len(curve)+499)//500)
            summary[key]={k:result.get(k) for k in ('ending_equity','fees','maximum_drawdown','risk_paused')}
            summary[key]['fills_count']=len(result['fills']);summary[key]['equity_curve']=curve[::stride]
        change('complete',summary_json=canonical(summary),result_path=str(result_path),finished_at=now(),error=None)
    except (ConnectionError,subprocess.TimeoutExpired):
        # Stable remote id is reconciled on the next tick; never duplicate uncertain submissions.
        return
    except Exception as error:
        change('canceled' if isinstance(error,InterruptedError) else 'failed',error=str(error)[:500],finished_at=now())

def prune(db,folder):
    total=sum(p.stat().st_size for p in folder.rglob('*') if p.is_file())
    for row in db.execute("SELECT id,finished_at FROM lean_comparisons WHERE status IN ('complete','failed','canceled') ORDER BY finished_at").fetchall():
        old=row['finished_at'] and time.time()-datetime.fromisoformat(row['finished_at']).timestamp()>30*86400
        if not old and total<9*1024**3:break
        path=folder/row['id']
        if path.is_dir():
            size=sum(p.stat().st_size for p in path.rglob('*') if p.is_file())
            shutil.rmtree(path);total-=size
            with db:db.execute('UPDATE lean_comparisons SET result_path=NULL,baseline_path=NULL WHERE id=?',(row['id'],))

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--database',required=True);args=parser.parse_args()
    folder=Path(args.database+'.lean-data');folder.mkdir(mode=0o700,exist_ok=True)
    with open(args.database+'.lean-owner.lock','a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        with connect(args.database) as db:
            while True:
                try:
                    prune(db,folder)
                    tick(db,folder,settings())
                except Exception as error:print('LEAN bridge error:',type(error).__name__,flush=True)
                time.sleep(10)
if __name__=='__main__':main()
