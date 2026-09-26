"""Public watch-only monitoring. No private keys, wallets, or transfers."""
from datetime import datetime, timedelta, timezone
import hashlib
import json
from urllib.parse import quote

from ..http import UrllibTransport, require_success
from .engine import canonical


def validate_address(value):
    # Verify Base58Check and BIP173/BIP350 checksums, not just address shape.
    if not isinstance(value, str) or len(value) > 90:
        raise ValueError('Enter a Bitcoin mainnet address')
    if value.startswith(('1','3')):
        alphabet = '123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz'
        try:
            number = 0
            for char in value:
                number = number*58 + alphabet.index(char)
            raw = b'\0'*(len(value)-len(value.lstrip('1'))) + number.to_bytes((number.bit_length()+7)//8,'big')
        except ValueError:
            raise ValueError('Invalid Base58 address') from None
        if len(raw) != 25 or raw[0] not in (0,5) or hashlib.sha256(hashlib.sha256(raw[:-4]).digest()).digest()[:4] != raw[-4:]:
            raise ValueError('Invalid address checksum')
        return value
    if value.lower() != value and value.upper() != value:
        raise ValueError('Mixed-case Bitcoin address')
    value = value.lower()
    if not value.startswith('bc1'):
        raise ValueError('Only Bitcoin mainnet addresses are supported')
    alphabet = 'qpzry9x8gf2tvdw0s3jn54khce6mua7l'
    try:
        data = [alphabet.index(c) for c in value[3:]]
    except ValueError:
        raise ValueError('Invalid bech32 address') from None
    chk = 1
    for v in [3,3,0,2,3] + data:  # HRP expansion for "bc"
        top = chk >> 25
        chk = (chk & 0x1ffffff) << 5 ^ v
        for i, generator in enumerate((0x3b6a57b2,0x26508e6d,0x1ea119fa,0x3d4233dd,0x2a1462b3)):
            if (top >> i) & 1:
                chk ^= generator
    if len(data) < 7 or data[0] > 16 or chk != (1 if data[0] == 0 else 0x2bc830a3):
        raise ValueError('Invalid bech32 checksum')
    bits, acc, program = 0, 0, []
    for v in data[1:-6]:
        acc = (acc << 5) | v
        bits += 5
        while bits >= 8:
            bits -= 8
            program.append((acc >> bits) & 255)
    if bits >= 5 or ((acc << (8-bits)) & 255) or not 2 <= len(program) <= 40 or (data[0] == 0 and len(program) not in (20,32)):
        raise ValueError('Invalid witness program')
    return value


class BitcoinMonitor:
    def __init__(self, transport=None):
        self.transport = transport or UrllibTransport()

    def get(self, path, text=False):
        response = self.transport.request('GET', 'https://mempool.space/api/' + path, timeout=10)
        if text and 200 <= response.status < 300:
            return response.body.decode().strip()
        return require_success('mempool.space', response)

    def collect(self, db, now=None):
        now = now or datetime.now(timezone.utc)
        at = now.isoformat()
        def record(kind, subject, payload):
            with db:
                db.execute('INSERT OR REPLACE INTO bitcoin_observations(observed_at,kind,subject,payload_json) VALUES (?,?,?,?)',
                           (at, kind, subject, canonical(payload)))
        for request in db.execute("SELECT * FROM bitcoin_watch_requests WHERE status='queued' ORDER BY created_at").fetchall():
            try:
                address = validate_address(request['address'])
                with db:
                    if db.execute('SELECT COUNT(*) FROM bitcoin_watch_addresses').fetchone()[0] >= 20:
                        raise ValueError('Maximum 20 watched addresses')
                    db.execute('INSERT INTO bitcoin_watch_addresses(address,label,added_at) VALUES (?,?,?) ON CONFLICT(address) DO UPDATE SET label=excluded.label',
                               (address,request['label'],at))
                    db.execute("UPDATE bitcoin_watch_requests SET status='succeeded' WHERE id=?",(request['id'],))
            except Exception as error:
                with db:
                    db.execute("UPDATE bitcoin_watch_requests SET status='failed',error=? WHERE id=?",(str(error)[:200],request['id']))
        # Respect a persistent network backoff; stale successful observations remain visible.
        recent=db.execute("SELECT payload_json FROM bitcoin_observations WHERE kind='error' AND subject='network' ORDER BY observed_at DESC LIMIT 1").fetchone()
        if recent:
            retry=json.loads(recent[0]).get('retry_after')
            if retry and datetime.fromisoformat(retry)>now: return
        previous=db.execute("SELECT payload_json FROM bitcoin_observations WHERE kind='network' ORDER BY observed_at DESC LIMIT 1").fetchone()
        reorg=False
        try:
            tip = self.get('blocks/tip/hash', text=True)
            block = self.get('block/' + tip)
            if previous:
                old=json.loads(previous[0])['block']
                if old['id']!=tip:
                    if block['height']<old['height']:
                        reorg=True
                    else:
                        canonical_hash=self.get('block-height/'+str(old['height']),text=True)
                        reorg=canonical_hash!=old['id']
            if reorg:
                with db:
                    db.execute("UPDATE bitcoin_transactions SET payload_json=json_set(payload_json,'$.status.confirmed',json('false'),'$.status.recheck_required',json('true')) WHERE json_extract(payload_json,'$.status.confirmed')=1")
            record('network','',{'provider':'mempool.space','reorg_detected':reorg, 'block':block, 'mempool':self.get('mempool'),
                                 'fees':self.get('v1/fees/recommended')})
        except Exception as error:
            record('error','network',{'message':str(error)[:300],'retry_after':(now+timedelta(minutes=5)).isoformat()})
            return
        for row in db.execute('SELECT * FROM bitcoin_watch_addresses WHERE next_check_at IS NULL OR next_check_at<=? ORDER BY added_at LIMIT 20',(at,)).fetchall():
            address = row['address']
            try:
                stats = self.get('address/' + quote(address, safe=''))
                transactions = self.get('address/' + address + '/txs')
                # Bounded work per tick. Resume older history from the last saved confirmed tx.
                existing = db.execute('SELECT payload_json FROM bitcoin_observations WHERE kind=\'address\' AND subject=? ORDER BY observed_at DESC LIMIT 1',(address,)).fetchone()
                prior = json.loads(existing[0]) if existing else {}
                cursor = prior.get('history_cursor')
                complete = prior.get('history_complete', False)
                head=transactions[0]['txid'] if transactions else None
                if reorg or (prior.get('head_txid') and prior['head_txid'] not in {tx['txid'] for tx in transactions}):
                    complete=False
                    cursor=None
                if not complete:
                    confirmed = [tx for tx in transactions if tx.get('status',{}).get('confirmed')]
                    cursor = cursor or (confirmed[-1]['txid'] if confirmed else None)
                    if cursor:
                        older = self.get('address/' + address + '/txs/chain/' + cursor)
                        transactions += older
                        complete = len(older) < 25
                        cursor = older[-1]['txid'] if older else cursor
                    else:
                        complete = stats['chain_stats']['tx_count'] == 0
                with db:
                    for tx in transactions:
                        db.execute('INSERT INTO bitcoin_transactions VALUES (?,?,?,?) ON CONFLICT(address,txid) DO UPDATE SET observed_at=excluded.observed_at,payload_json=excluded.payload_json',
                                   (address,tx['txid'],at,canonical(tx)))
                # Recheck recent confirmed/unconfirmed observations; a reorg can reverse confirmation.
                candidates = db.execute("SELECT txid,payload_json FROM bitcoin_transactions WHERE address=? AND (json_extract(payload_json,'$.status.confirmed')=0 OR json_extract(payload_json,'$.status.block_height')>?) ORDER BY observed_at ASC LIMIT 3",(address,block['height']-6)).fetchall()
                for txrow in candidates:
                    tx = json.loads(txrow['payload_json'])
                    status = tx.get('status',{})
                    if not status.get('confirmed') or block['height'] - status.get('block_height',0) < 6:
                        tx['status'] = self.get('tx/' + txrow['txid'] + '/status')
                        with db:
                            db.execute('UPDATE bitcoin_transactions SET payload_json=?,observed_at=? WHERE address=? AND txid=?',(canonical(tx),at,address,txrow['txid']))
                record('address',address,{'provider':'mempool.space','stats':stats,'history_complete':complete,
                                         'history_cursor':cursor,'head_txid':head,'reorg_detected':reorg,'tip_height':block['height']})
                with db:
                    db.execute('UPDATE bitcoin_watch_addresses SET last_checked_at=?,next_check_at=?,failure_count=0 WHERE address=?',
                               (at,(now+timedelta(minutes=5)).isoformat(),address))
            except Exception as error:
                record('error',address,{'message':str(error)[:300]})
                with db:
                    db.execute('UPDATE bitcoin_watch_addresses SET next_check_at=?,failure_count=failure_count+1 WHERE address=?',
                               ((now+timedelta(minutes=min(60,5*2**min(row['failure_count'],4)))).isoformat(),address))
