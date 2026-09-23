"""Install an immutable paper execution policy; ranking stays at baseline."""
import json
from .config import load_strategy_document
from .database import register_strategy

STRATEGY_ID = 'sp500-long-paper-v2'

def install_policy(connection):
    row = connection.execute("SELECT config_json,config_sha256 FROM strategy_versions WHERE id='sp500-long-paper-v1'").fetchone()
    if row is None:
        raise ValueError('The reviewed paper-v1 strategy is required')
    source = load_strategy_document(json.loads(row['config_json']))
    if source.sha256 != row['config_sha256']:
        raise ValueError('Source strategy hash does not match')
    config = json.loads(source.canonical_json)
    config.update(id=STRATEGY_ID, name='S&P 500 baseline with verified paper entries v2', status='paper')
    config['portfolio'] = {'maximum_notional_usd':300, 'maximum_sector_notional_usd':60}
    config['sizing']['maximum_open_notional_per_ticker_usd'] = 30
    config['execution']['horizon_priority'] = [21,5,63,105]
    config['entry_policy'] = {'enabled':True, 'maximum_quote_age_seconds':120,
        'maximum_spread_fraction':.01, 'maximum_price_change_fraction':.05,
        'maximum_initial_signal_age_minutes':30, 'earnings_buffer_hours':24,
        'require_earnings_calendar':False}
    loaded = load_strategy_document(config)
    with connection:
        created = register_strategy(connection, loaded)
        if created:
            connection.execute("UPDATE strategy_versions SET promoted_at=CURRENT_TIMESTAMP WHERE id=?",(STRATEGY_ID,))
            connection.execute("INSERT INTO audit_events(event_type,entity_type,entity_id,payload_json) VALUES ('assessment_policy_installed','strategy_version',?,?)",
                (STRATEGY_ID,json.dumps({'source':source.id,'sha256':loaded.sha256,'portfolio':config['portfolio'],'observation_variants_cannot_trade':True})))
    return STRATEGY_ID
