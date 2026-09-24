#!/usr/bin/env python3
"""Serve a disposable HomeOps database copy on loopback, with no background jobs."""
import json
from pathlib import Path
import sys
from http.server import ThreadingHTTPServer

root, database, source_config = map(Path, sys.argv[1:])
if database.name != 'homeops-working.db' or not database.is_file():
    raise SystemExit('Use the dedicated homeops-working.db rehearsal copy')
sys.path.insert(0, str(root.resolve()))
from home_ops.store import Store
from home_ops.server import handler

config = json.loads(source_config.read_text())
config.update(database=str(database.resolve()), bind='127.0.0.1', port=19100,
              allowed_networks=['127.0.0.0/8'], allowed_hosts=['127.0.0.1', 'localhost'],
              collector_tokens={}, notification_token='')
store = Store(database, config)
# No retention, monitoring, network discovery, collectors, or notifier threads.
server = ThreadingHTTPServer(('127.0.0.1', 19100), handler(store, config, root/'web/dist'))
server.serve_forever()
