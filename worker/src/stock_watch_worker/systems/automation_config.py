"""Version-two Bitcoin configurations leave v1 strategy hashes unchanged."""
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from .engine import SystemConfig, digest
from .timeframes import TIMEFRAMES, deadline, months

PROTOCOL = 'bitcoin-automation-v2'

@dataclass(frozen=True)
class BitcoinConfig(SystemConfig):
    timeframe: str = '1Hour'
    holding_count: int = 7
    holding_unit: str = 'days'
    protocol: str = PROTOCOL

    def __post_init__(self):
        super().__post_init__()
        if self.asset!='bitcoin' or self.protocol!=PROTOCOL or self.timeframe not in TIMEFRAMES:
            raise ValueError('Invalid automated Bitcoin configuration')
        if not .05<=self.allocation<=.5: raise ValueError('Bitcoin exposure must be 5–50% of its allocation')
        if isinstance(self.holding_count,bool) or not isinstance(self.holding_count,int) or self.holding_count<1:
            raise ValueError('Holding count must be a positive integer')
        # A non-leap anchor keeps fixed-duration units within twelve calendar
        # months for every possible entry date. Calendar months retain clamping.
        anchor=datetime(2023,1,1,tzinfo=timezone.utc)
        if deadline(anchor,self.holding_count,self.holding_unit)>months(anchor,12):
            raise ValueError('Maximum holding period is 12 calendar months')

    @property
    def sha256(self): return digest({'engine':PROTOCOL,**asdict(self)})


def load_config(document):
    if document.get('protocol')=='visual-rules-v1':
        from .rules import RuleConfig
        return RuleConfig(**document)
    return BitcoinConfig(**document) if document.get('protocol')==PROTOCOL else SystemConfig(**document)
