"""Restart only the LEAN bridge during a separately audited historical replay."""
import argparse,json,os,pathlib,pwd,socket,sqlite3,subprocess,sys,time,uuid
DB='/var/lib/stock-watch/stock-watch.db'
REFERENCE='f88ac8db-ae06-549e-af58-5ba17958366f'
STATE=pathlib.Path('/var/lib/stock-watch/lean-verification')

def worker(action,job):
    if pwd.getpwuid(os.geteuid()).pw_name!='stock-watch':raise SystemExit('Worker requires stock-watch identity')
    db=sqlite3.connect(DB,timeout=10);db.row_factory=sqlite3.Row
    if action=='queue':
        from datetime import datetime,timezone
        now=datetime.now(timezone.utc).isoformat();db.execute('BEGIN IMMEDIATE')
        if db.execute("SELECT count(*) FROM lean_comparisons WHERE status NOT IN ('complete','failed','canceled')").fetchone()[0]:raise RuntimeError('Research queue must be empty')
        original=db.execute('SELECT * FROM lean_comparisons WHERE id=?',(REFERENCE,)).fetchone()
        if not original or original['status']!='complete':raise RuntimeError('Verified historical reference missing')
        db.execute("INSERT INTO lean_comparisons(id,version_id,dataset_id,status,created_at,updated_at) VALUES (?,?,?,'queued',?,?)",(job,original['version_id'],original['dataset_id'],now,now))
        db.execute('INSERT INTO system_audit(at,action,entity_id,payload_json) VALUES (?,?,?,?)',(now,'lean_create',job,json.dumps({'source':'bridge restart verification','reference':REFERENCE})));db.commit()
    row=db.execute('SELECT id,status,summary_json,error FROM lean_comparisons WHERE id=?',(job,)).fetchone()
    print(json.dumps(dict(row)));db.close()

def main():
    p=argparse.ArgumentParser();p.add_argument('--worker',choices=('queue','status'));p.add_argument('--job');p.add_argument('--run',action='store_true');a=p.parse_args()
    if a.worker:return worker(a.worker,a.job)
    if os.geteuid()!=0 or socket.gethostname().split('.')[0]!='a1347-m':raise SystemExit('Run with sudo on a1347-m')
    from urllib.request import urlopen
    with urlopen('http://127.0.0.1:3001/api/health/lean',timeout=10) as response:health=json.load(response)
    if not health.get('healthy') or health.get('queued')!=0:raise SystemExit('Healthy empty runner required')
    STATE.mkdir(mode=0o750,exist_ok=True);os.chown(STATE,0,pwd.getpwnam('stock-watch').pw_gid);STATE.chmod(0o750);target=STATE/'verify-bridge.py'
    if not a.run:
        target.write_bytes(pathlib.Path(__file__).read_bytes());os.chown(target,0,pwd.getpwnam('stock-watch').pw_gid);target.chmod(0o640)
        unit='stock-watch-lean-bridge-verification-'+str(int(time.time()))
        subprocess.run(['systemd-run','--no-block','--unit='+unit,'--property=Type=oneshot','--property=TimeoutStartSec=5min','/usr/bin/python3',str(target),'--run'],check=True)
        print('Started '+unit+'.service');return
    job=str(uuid.uuid4())
    def call(action):
        result=subprocess.run(['runuser','-u','stock-watch','--','/usr/bin/python3',str(target),'--worker',action,'--job',job],check=True,capture_output=True,text=True,timeout=15)
        return json.loads(result.stdout)
    call('queue');print('Research restart verification job: '+job,flush=True)
    restarted=False
    for _ in range(180):
        row=call('status')
        if row['status']=='lean' and not restarted:
            subprocess.run(['systemctl','restart','stock-watch-lean.service'],check=True,timeout=45);restarted=True
            print('Bridge restarted during remote research; stable job ID '+job,flush=True)
        if row['status']=='complete':
            if not restarted:raise RuntimeError('Job completed before restart; test inconclusive')
            if json.loads(row['summary_json'])['difference_count']!=0:raise RuntimeError('Comparison diverged')
            print(json.dumps({'passed':True,'job':job,'difference_count':0}),flush=True);return
        if row['status'] in ('failed','canceled'):raise RuntimeError(str(row))
        time.sleep(1)
    raise RuntimeError('Bridge verification deadline exceeded; inspect job '+job)
if __name__=='__main__':main()
