"""Independent LEAN availability monitor; shares transport, never incident state."""
import fcntl
import json
import os
from pathlib import Path
import sys
import time
from urllib.request import urlopen
from zoneinfo import ZoneInfo
from datetime import datetime

ENDPOINT = 'http://192.168.4.35:3001/api/health/lean'
STATE = Path('/home/mjm2z/.local/state/stockwatch-lean-watchdog/state.json')
CONFIG = Path('/home/mjm2z/.config/home-ops/watchdog-migration.json')


def save(path, state):
    temporary = path.with_suffix('.tmp')
    with temporary.open('w') as stream:
        json.dump(state, stream, indent=2)
        stream.flush()
        os.fsync(stream.fileno())
    temporary.chmod(0o600)
    os.replace(temporary, path)


def advance(state, healthy, at):
    if at - state.get('observed_at', at) > 180:
        state['failures'] = state['successes'] = 0
    state.update(observed_at=at, healthy=healthy)
    state['failures'] = 0 if healthy else state.get('failures', 0) + 1
    state['successes'] = state.get('successes', 0) + 1 if healthy else 0
    events = state.setdefault('events', [])
    if not healthy and state['failures'] >= 3 and not state.get('incident'):
        state['incident'] = str(at)
        events.append(dict(id=str(at), kind='outage', at=at, delivery='queued'))
    if healthy and state['successes'] >= 2 and state.get('incident'):
        events.append(dict(id=state.pop('incident'), kind='recovery', at=at, delivery='queued'))
    # Bound retained receipts, but do not discard unsent/uncertain evidence.
    sent = [e for e in events if e['delivery'] == 'sent']
    keep = {id(e) for e in sent[-100:]}
    state['events'] = [e for e in events if e['delivery'] != 'sent' or id(e) in keep]


def probe():
    try:
        with urlopen(ENDPOINT, timeout=8) as response:
            body = json.load(response)
            return (response.status == 200 and body.get('healthy') is True
                    and body.get('configured') is True and body.get('stale') is False)
    except Exception:
        return False


def tick(path, config, sender, at=None):
    at = time.time() if at is None else at
    state = json.loads(path.read_text()) if path.exists() else {}
    for event in state.get('events', []):
        if event['delivery'] == 'sending':
            event['delivery'] = 'uncertain'
    advance(state, probe(), at)
    save(path, state)
    hour = datetime.fromtimestamp(at, ZoneInfo('America/New_York')).hour
    if hour < 11 or hour >= 22 or not config.get('delivery_enabled', True):
        return state
    for event in state['events']:
        if event['delivery'] != 'queued':
            continue
        event['delivery'] = 'sending'
        save(path, state)
        stamp = datetime.fromtimestamp(event['at'], ZoneInfo('America/New_York')).isoformat()
        text = ('StockWatch LEAN research ' + ('unavailable' if event['kind'] == 'outage' else 'recovered')
                + '\nObserved by a1347-j: ' + stamp
                + '\nThis check covers research availability, not trading health.'
                + '\nhttp://stockwatch.home.arpa/systems?asset=bitcoin')
        try:
            receipt = sender(config, text)
        except Exception:
            receipt = {'status': 'uncertain'}
        event.update(delivery='sent' if receipt.get('status') == 'sent' else 'uncertain',
                     message_id=receipt.get('message_id'), delivered_at=at)
        save(path, state)
        break
    return state


def main():
    sys.path.insert(0, '/home/mjm2z/home-ops-watchdog')
    from home_ops.watchdog_transport import send_telegram
    STATE.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    with (STATE.parent / 'owner.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        config = json.loads(CONFIG.read_text())
        if config.get('delivery_transport') != 'telegram':
            raise RuntimeError('Expected existing independent Telegram transport')
        while True:
            try:
                tick(STATE, config, send_telegram)
            except Exception:
                print('LEAN monitoring could not persist evidence', flush=True)
            time.sleep(60)


if __name__ == '__main__':
    main()
