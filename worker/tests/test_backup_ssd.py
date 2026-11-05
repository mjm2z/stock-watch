import hashlib
import io
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

from stock_watch_worker import backup_ssd as ssd
from stock_watch_worker.backup import create_sqlite_backup


class SSDTests(unittest.TestCase):
    def database(self, path):
        with sqlite3.connect(path) as db:
            db.execute('CREATE TABLE evidence(value TEXT)')
            db.execute("INSERT INTO evidence VALUES ('recovered')")

    def test_receiver_rejects_truncation_and_wrong_checksum(self):
        with tempfile.TemporaryDirectory() as directory:
            p=Path(directory)/'copy'
            with self.assertRaisesRegex(RuntimeError,'Interrupted'):
                ssd.receive(io.BytesIO(b'abc'),p,4,'0'*64,lambda _:None)
            p.unlink()
            with self.assertRaisesRegex(RuntimeError,'checksum'):
                ssd.receive(io.BytesIO(b'abcd'),p,4,'0'*64,lambda _:None)

    def test_full_integrity_rejects_corrupt_database(self):
        with tempfile.TemporaryDirectory() as directory:
            p=Path(directory)/'bad';p.write_bytes(b'x'*4096)
            with self.assertRaises(sqlite3.DatabaseError):ssd.check_database(p)

    def test_receipt_binds_every_identity_field(self):
        receipt=dict(version=1,run_id='a'*32,bytes=4096,sha256='b'*64,status='ok',
                     verification='sqlite_integrity_check_and_reopen')
        ssd.validate_receipt(receipt,'a'*32,4096,'b'*64)
        for key in receipt:
            with self.subTest(key=key),self.assertRaises(RuntimeError):
                ssd.validate_receipt({**receipt,key:'wrong'},'a'*32,4096,'b'*64)

    def test_real_receiver_transfer_check_and_reopen(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);db=root/'source.db';self.database(db)
            lock=root/'.local/state/home-ops/ssd-verifier';lock.mkdir(parents=True)
            config=root/'config.json';config.write_text(json.dumps(dict(host='test',key='/key',known_hosts='/hosts')))
            real_popen=subprocess.Popen
            def transport(command,**kwargs):
                if command[0]=='ssh':
                    env=dict(os.environ,HOME=str(root),SSH_ORIGINAL_COMMAND=' '.join(command[-4:]))
                    return real_popen([sys.executable,ssd.__file__,'--receive'],env=env,**kwargs)
                return real_popen(command,**kwargs)
            phases=[]
            with patch.object(ssd.subprocess,'Popen',side_effect=transport):
                receipt=ssd.remote_verify(db,config,time.monotonic()+60,lambda phase,**kw:phases.append(phase))
            self.assertEqual(receipt['sha256'],hashlib.sha256(db.read_bytes()).hexdigest())
            self.assertIn('ssd_verifying',phases)
            self.assertFalse(list((root/'.local/state/stock-watch-ssd-verifier').glob('stage-*')))

    def test_client_timeout_terminates_hung_transport(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);db=root/'source.db';self.database(db)
            config=root/'config.json';config.write_text(json.dumps(dict(host='test',key='/key',known_hosts='/hosts')))
            real_popen=subprocess.Popen;children=[]
            def hung(command,**kwargs):
                child=real_popen([sys.executable,'-c','import time; time.sleep(60)'],**kwargs)
                children.append(child);return child
            with patch.object(ssd.subprocess,'Popen',side_effect=hung),self.assertRaises(TimeoutError):
                ssd.remote_verify(db,config,time.monotonic()+.1,lambda *a,**kw:None)
            self.assertTrue(all(c.poll() is not None for c in children))

    def test_receiver_refuses_competing_verifier(self):
        import fcntl
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);lock=root/'.local/state/home-ops/ssd-verifier';lock.mkdir(parents=True)
            with (lock/'worker.lock').open('a') as held:
                fcntl.flock(held,fcntl.LOCK_EX|fcntl.LOCK_NB)
                result=subprocess.run([sys.executable,ssd.__file__,'--receive'],input=b'',capture_output=True,
                    env=dict(os.environ,HOME=str(root),SSH_ORIGINAL_COMMAND='verify-stockwatch-v1 '+'a'*32+' 4096 '+'b'*64),timeout=10)
            self.assertNotEqual(result.returncode,0)
            self.assertFalse(list(root.glob('.local/state/stock-watch-ssd-verifier/receipts/*')))

    def test_timeout_and_failure_never_publish_or_prune(self):
        for failure in (TimeoutError('transfer timeout'),RuntimeError('invalid receipt')):
            with tempfile.TemporaryDirectory() as directory:
                root=Path(directory);db=root/'source.db';self.database(db)
                dest=root/'backups';dest.mkdir();old=dest/'stock-watch-20200101T000000000000Z.db';old.write_bytes(b'old')
                with patch.dict(os.environ,STOCK_WATCH_BACKUP_SSD_CONFIG='/config'),patch.object(ssd,'remote_verify',side_effect=failure):
                    with self.assertRaises(type(failure)):create_sqlite_backup(db,dest,keep=1,reserve_bytes=0)
                self.assertEqual(list(dest.glob('*.db')),[old])
                self.assertFalse(list(dest.glob('.*.tmp')))

    def test_verified_export_publishes_receipt_and_preserves_history(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);db=root/'source.db';self.database(db)
            dest=root/'backups';dest.mkdir();old=dest/'stock-watch-20200101T000000000000Z.db';old.write_bytes(b'old')
            def verify(path,*args):
                ssd.check_database(path)
                return dict(status='ok',sha256=hashlib.sha256(path.read_bytes()).hexdigest())
            with patch.dict(os.environ,STOCK_WATCH_BACKUP_SSD_CONFIG='/config',STOCK_WATCH_BACKUP_PRESERVE_HISTORY='1'),patch.object(ssd,'remote_verify',side_effect=verify):
                result=create_sqlite_backup(db,dest,keep=1,reserve_bytes=0)
            self.assertTrue(old.exists())
            receipt=json.loads(result.path.with_suffix('.db.verification.json').read_text())
            self.assertEqual(receipt['sha256'],hashlib.sha256(result.path.read_bytes()).hexdigest())


if __name__=='__main__':unittest.main()
