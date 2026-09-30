#!/usr/bin/env python3
"""Provision service credentials after the operator saves manual paper broker keys.

GET-only broker/chat validation. Never confirms setup, submits orders, resets
accounts, or sends Telegram messages. Run as root on a1347-m.
"""
import argparse
from datetime import datetime, timezone
from decimal import Decimal
import json
import os
from pathlib import Path
import pwd
import re
import secrets
import shlex
import socket
import subprocess
import tempfile
import time
from urllib.parse import urlencode
from urllib.request import HTTPRedirectHandler, Request, build_opener


class ConfigurationError(Exception):
    pass


# Only interpret fields consumed by this helper. Other environment settings may
# use systemd/dotenv syntax (including unquoted spaces) and remain untouched.
CONFIG_KEYS = frozenset({
    'ALPACA_API_KEY_ID', 'ALPACA_API_SECRET_KEY',
    'BITCOIN_ALPACA_API_KEY_ID', 'BITCOIN_ALPACA_API_SECRET_KEY',
    'MANUAL_ALPACA_API_KEY_ID', 'MANUAL_ALPACA_API_SECRET_KEY',
    'STOCK_WATCH_AUTOBOT_TOKEN', 'STOCK_WATCH_BROWSER_SERVICE_TOKEN',
    'STOCK_WATCH_TELEGRAM_USER_ID', 'STOCK_WATCH_TELEGRAM_CHAT_ID',
    'STOCK_WATCH_DIGEST_TIME', 'TELEGRAM_CHAT_ID', 'TELEGRAM_BOT_TOKEN',
})


def read_env(text):
    values = {}
    for line in text.splitlines():
        match = re.match(r'^\s*(?:export\s+)?([A-Z][A-Z0-9_]*)\s*=(.*)$', line)
        if not match:
            continue
        key, raw = match.groups()
        if key not in CONFIG_KEYS:
            continue
        if key in values:
            raise ConfigurationError('Duplicate configuration variable: ' + key)
        try:
            words = shlex.split(raw, comments=True)
        except ValueError:
            raise ConfigurationError('Invalid quoting for configuration variable: ' + key) from None
        if len(words) > 1:
            raise ConfigurationError('Unquoted spaces in configuration variable: ' + key)
        values[key] = words[0] if words else ''
    return values


def update_env(text, updates):
    lines = [line for line in text.splitlines() if not any(
        re.match(r'^\s*(?:export\s+)?' + re.escape(key) + r'\s*=', line) for key in updates)]
    for key, value in updates.items():
        if not re.fullmatch(r'[A-Za-z0-9_:/.-]+', value):
            raise ConfigurationError('Unsafe generated value for ' + key)
        lines.append(key + '=' + value)
    return '\n'.join(lines) + '\n'


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def get_json(url, headers=None):
    try:
        with build_opener(NoRedirect).open(Request(url, headers=headers or {}, method='GET'), timeout=10) as response:
            raw = response.read(2_000_001)
            if len(raw) > 2_000_000:
                raise ValueError('Oversized response')
            return json.loads(raw)
    except Exception:
        # HTTP errors and URLs may contain secrets. Never copy their text.
        raise ConfigurationError('Read-only endpoint check failed; check credentials and connectivity.') from None


def broker_get(values, prefix, route):
    key, secret = values.get(prefix + '_API_KEY_ID'), values.get(prefix + '_API_SECRET_KEY')
    if not key or not secret:
        raise ConfigurationError('Missing credentials for ' + prefix)
    return get_json('https://paper-api.alpaca.markets/v2/' + route,
                    {'APCA-API-KEY-ID': key, 'APCA-API-SECRET-KEY': secret})


def validate_accounts(manual, stocks, bitcoin, positions, orders):
    ids = [account.get('id') for account in (manual, stocks, bitcoin)]
    if not all(ids):
        raise ConfigurationError('A paper account response is missing its account identity.')
    labels = ['manual', 'automated stocks', 'automated Bitcoin']
    collisions = [labels[i] + ' and ' + labels[j]
                  for i in range(3) for j in range(i + 1, 3) if ids[i] == ids[j]]
    if collisions:
        raise ConfigurationError('Paper account identity conflict: ' + '; '.join(collisions)
                                 + ' resolve to the same account. No configuration was changed.')
    try:
        cash = Decimal(str(manual['cash']))
    except Exception:
        raise ConfigurationError('Manual paper cash could not be verified.') from None
    if not cash.is_finite() or abs(cash - Decimal('1000000')) > Decimal('.01') or positions or orders:
        raise ConfigurationError('Manual setup requires an empty $1,000,000 paper account; no reset was performed.')
    if manual.get('status') != 'ACTIVE' or manual.get('trading_blocked') or manual.get('account_blocked'):
        raise ConfigurationError('The manual paper account is not active and available.')


def select_token(*existing):
    tokens = {value for value in existing if value}
    if len(tokens) > 1:
        raise ConfigurationError('Existing service tokens differ; review before changing configuration.')
    token = next(iter(tokens), None) or secrets.token_urlsafe(48)
    if not re.fullmatch(r'[A-Za-z0-9_-]{32,}', token):
        raise ConfigurationError('Existing service token is invalid; explicit review required.')
    return token


def atomic_write(path, content, uid, gid):
    fd, temporary = tempfile.mkstemp(prefix=path.name + '.new-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, 0o600)
        os.chown(temporary, uid, gid)
        os.replace(temporary, path)
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def install_configs(updates, backup_directory):
    # Verify all originals before the first mutation and retain protected backups.
    for path, original, content, uid, gid in updates:
        if path.read_bytes() != original:
            raise ConfigurationError('Configuration changed during validation; rerun after review.')
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ') + '-' + secrets.token_hex(3)
    backup_directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    if backup_directory.is_symlink() or not backup_directory.is_dir():
        raise ConfigurationError('Unexpected backup directory.')
    run_backup = backup_directory / stamp
    run_backup.mkdir(mode=0o700)
    for index, (path, original, content, uid, gid) in enumerate(updates):
        backup = run_backup / (str(index) + '-' + path.name.lstrip('.'))
        with backup.open('xb') as stream:
            os.fchmod(stream.fileno(), 0o600)
            stream.write(original)
            stream.flush()
            os.fsync(stream.fileno())
    written = []
    try:
        for path, original, content, uid, gid in updates:
            if path.read_bytes() != original:
                raise ConfigurationError('Concurrent configuration change; installation stopped.')
            atomic_write(path, content, uid, gid)
            written.append((path, original, uid, gid))
    except Exception:
        for path, original, uid, gid in reversed(written):
            atomic_write(path, original, uid, gid)
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--use-existing-private-chat', action='store_true', required=True,
                        help='Operator explicitly authorizes the existing private Autobot chat')
    args = parser.parse_args()
    if os.geteuid() != 0 or socket.gethostname().split('.')[0] != 'a1347-m':
        raise ConfigurationError('Run as root on a1347-m.')
    systems = Path('/etc/stock-watch/systems.env')
    bot = Path('/home/mjm2z/autobot/.env')
    for path in (systems, bot):
        if not path.is_file() or path.is_symlink():
            raise ConfigurationError('Expected ordinary protected configuration file: ' + str(path))
    original_systems, original_bot = systems.read_bytes(), bot.read_bytes()
    stock = read_env(Path('/etc/stock-watch/stock-watch.env').read_text())
    current = read_env(original_systems.decode())
    stock.update(current)
    bot_values = read_env(original_bot.decode())
    chat_id = bot_values.get('TELEGRAM_CHAT_ID', '')
    telegram_token = bot_values.get('TELEGRAM_BOT_TOKEN', '')
    if not chat_id.isdigit() or int(chat_id) <= 0 or not telegram_token:
        raise ConfigurationError('Existing private Telegram chat configuration is unavailable.')
    print('Verifying the existing private Telegram chat and paper account identities...', flush=True)
    chat = get_json('https://api.telegram.org/bot' + telegram_token + '/getChat?' + urlencode({'chat_id': chat_id}))
    if not chat.get('ok') or chat['result'].get('type') != 'private' or str(chat['result'].get('id')) != chat_id:
        raise ConfigurationError('Existing Telegram chat is not the verified private conversation.')
    for name, values in [('STOCK_WATCH_TELEGRAM_USER_ID', current), ('STOCK_WATCH_TELEGRAM_CHAT_ID', current), ('STOCK_WATCH_TELEGRAM_USER_ID', bot_values)]:
        if values.get(name) and values[name] != chat_id:
            raise ConfigurationError('Existing StockWatch authorization differs; review before changing it.')
    manual = broker_get(stock, 'MANUAL_ALPACA', 'account')
    automated_stocks = broker_get(stock, 'ALPACA', 'account')
    automated_bitcoin = broker_get(stock, 'BITCOIN_ALPACA', 'account')
    positions = broker_get(stock, 'MANUAL_ALPACA', 'positions')
    orders = broker_get(stock, 'MANUAL_ALPACA', 'orders?status=open')
    validate_accounts(manual, automated_stocks, automated_bitcoin, positions, orders)
    autobot_token = select_token(current.get('STOCK_WATCH_AUTOBOT_TOKEN'), bot_values.get('STOCK_WATCH_AUTOBOT_TOKEN'))
    browser_token = select_token(current.get('STOCK_WATCH_BROWSER_SERVICE_TOKEN'))
    if browser_token == autobot_token:
        raise ConfigurationError('Browser and Autobot service credentials must differ.')
    updates = {'STOCK_WATCH_AUTOBOT_TOKEN': autobot_token, 'STOCK_WATCH_BROWSER_SERVICE_TOKEN': browser_token,
               'STOCK_WATCH_TELEGRAM_USER_ID': chat_id, 'STOCK_WATCH_TELEGRAM_CHAT_ID': chat_id}
    if not current.get('STOCK_WATCH_DIGEST_TIME'):
        updates['STOCK_WATCH_DIGEST_TIME'] = '20:00'
    bot_updates = {'STOCK_WATCH_URL': 'http://127.0.0.1:3013', 'STOCK_WATCH_AUTOBOT_TOKEN': autobot_token,
                   'STOCK_WATCH_TELEGRAM_USER_ID': chat_id}
    bot_stat = bot.stat()
    bot_uid = pwd.getpwnam('mjm2z').pw_uid
    if bot_stat.st_uid != bot_uid:
        raise ConfigurationError('Autobot environment owner differs; review permissions before changing it.')
    install_configs([(systems, original_systems, update_env(original_systems.decode(), updates).encode(), 0, 0),
                     (bot, original_bot, update_env(original_bot.decode(), bot_updates).encode(), bot_stat.st_uid, bot_stat.st_gid)],
                    Path('/etc/stock-watch/manual-service-backups'))
    subprocess.run(['systemctl', 'restart', 'stock-watch-manual-paper.service', 'stock-watch-web.service'], check=True)
    subprocess.run(['runuser', '-u', 'mjm2z', '--', 'env', 'XDG_RUNTIME_DIR=/run/user/' + str(bot_uid),
                    'systemctl', '--user', 'restart', 'note-bot.service'], check=True)
    for attempt in range(5):
        try:
            status = get_json('http://127.0.0.1:3013/status', {'Authorization': 'Bearer ' + browser_token})
            break
        except ConfigurationError:
            if attempt == 4:
                raise
            time.sleep(1)
    print('Verified three distinct paper accounts and an empty $1,000,000 manual account.')
    print('Private Telegram authorization and separate service credentials installed; protected backups retained.')
    print('Manual account state: ' + status['manual'])
    print('Next: preview combined setup in StockWatch or Telegram and confirm the exact allocation draft.')


if __name__ == '__main__':
    try:
        main()
    except ConfigurationError as error:
        raise SystemExit(str(error)) from None
    except Exception as error:
        raise SystemExit('Configuration did not complete (' + type(error).__name__ + '). Review service state; no order or account reset was requested.') from None
