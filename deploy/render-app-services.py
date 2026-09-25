#!/usr/bin/env python3
"""Render disabled Linux migration units; never install or start them.

Radar's source Debian cron uses the host's UTC timezone, ignoring CRON_TZ.
Explicit UTC calendars preserve observed execution times across the host move.
Activation requires a separate cutover marker after final data verification.
"""
import argparse
from pathlib import Path


# name, actual source schedule (UTC), npm script, script arguments, environment
RADAR_JOBS = (
    ('health', '*-*-* *:05,35:00 UTC', 'check_system_health', '',
     'APP_DEMAND_HEALTH_URL=http://127.0.0.1:5210/api/system/status'),
    ('retention', 'Sun *-*-* 03:20:00 UTC', 'cleanup_retention', '', ''),
    ('reddit', '*-*-* *:15:00 UTC', 'scrape_reddit', '', 'REDDIT_POST_LIMIT=25'),
    ('reviews', '*-*-* 07,19:25:00 UTC', 'scrape_app_store_reviews', '', ''),
    ('keywords', '*-*-* 00/4:35:00 UTC', 'scrape_keyword_watchlist', '', ''),
    ('process', '*-*-* *:45:00 UTC', 'process_pain_points', '', ''),
    ('categories', '*-*-* *:47:00 UTC', 'repair_pain_categories', '--apply', ''),
    ('quality', '*-*-* *:48:00 UTC', 'review_pain_quality', '--apply', ''),
    ('cluster', '*-*-* *:50:00 UTC', 'cluster_ideas', '', ''),
    ('score', '*-*-* *:55:00 UTC', 'score_ideas', '', ''),
    ('audit', '*-*-* *:57:00 UTC', 'audit_data_quality', '', ''),
    ('report', '*-*-* 10,18:00:00 UTC', 'generate_daily_report', '--notify --ai', ''),
    ('trend', '*-*-* 08:05:00 UTC', 'trend_radar_daily', '', ''),
)


def service(description, app, command, *, oneshot=False, environment=()):
    return f'''[Unit]
Description={description}
ConditionPathExists=%h/.config/app-migration/{app}.cutover-ready
StartLimitIntervalSec=300
StartLimitBurst=5

[Service]
Type={'oneshot' if oneshot else 'simple'}
WorkingDirectory=%h/{app}{'/backend' if app == 'app-demand-radar' else ''}
Environment=PATH=/usr/local/bin:/usr/bin:/bin
Environment=NODE_ENV=production
''' + ''.join(f'Environment={value}\n' for value in environment) + f'''ExecStart=/usr/local/bin/node --env-file=%h/.config/{app}/runtime.env {command}
UMask=0077
NoNewPrivileges=true
TimeoutStartSec={'infinity' if oneshot else '90'}
TimeoutStopSec=infinity
KillSignal=SIGTERM
''' + ('' if oneshot else '''Restart=on-failure
RestartSec=15

[Install]
WantedBy=default.target
''')


def render():
    units = {
        'job-watch-web.service': service('JobWatch web', 'job-watch', 'scripts/native-server.mjs',
            environment=('JOBWATCH_LAN_ADDRESS=192.168.4.35',
                         'JOBWATCH_TRUSTED_HOSTNAMES=jobwatch.home.arpa')),
        'job-watch-worker.service': service('JobWatch worker', 'job-watch', '--import tsx src/worker.ts'),
        'app-demand-radar.service': service('App Demand Radar API', 'app-demand-radar', 'src/server.js',
            environment=('HOST=0.0.0.0', 'PORT=5210')),
    }
    for name, calendar, script, arguments, env in RADAR_JOBS:
        stem = f'app-demand-radar-{name}'
        units[stem + '.service'] = service(f'App Demand Radar {name}', 'app-demand-radar',
            f'scripts/{script}.js' + (f' {arguments}' if arguments else ''),
            oneshot=True, environment=(env,) if env else ())
        log = ({'health': 'health', 'retention': 'retention',
                'reddit': 'collectors', 'reviews': 'collectors', 'keywords': 'collectors',
                'report': 'reports', 'trend': 'trend-radar'}.get(name, 'processors'))
        units[stem + '.service'] += (
            f'StandardOutput=append:%h/.local/state/app-demand-radar/logs/{log}.log\n'
            f'StandardError=append:%h/.local/state/app-demand-radar/logs/{log}.log\n')
        units[stem + '.timer'] = f'''[Unit]
Description=App Demand Radar {name} schedule (source UTC)
ConditionPathExists=%h/.config/app-migration/app-demand-radar.cutover-ready

[Timer]
OnCalendar={calendar}
Persistent=false
AccuracySec=1s
RandomizedDelaySec=0
Unit={stem}.service

[Install]
WantedBy=timers.target
'''
    return units


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    args.output.mkdir(mode=0o700)  # Refuse replacing an earlier reviewed bundle.
    for name, content in render().items():
        (args.output / name).write_text(content)
    print(f'Rendered {len(render())} units; nothing installed or started: {args.output}')


if __name__ == '__main__':
    main()
