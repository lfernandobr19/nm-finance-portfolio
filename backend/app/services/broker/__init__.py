from __future__ import annotations

from app.domain.models import ExecutionMode, InvestmentAccount
from app.services.broker.base import BrokerAdapter
from app.services.broker.inter_manual import InterManualBrokerAdapter
from app.services.broker.simulated import SimulatedBrokerAdapter
from app.services.broker.tastytrade_paper import TastytradeBrokerAdapter


def get_broker_adapter(account: InvestmentAccount) -> BrokerAdapter:
    mode = account.execution_mode
    if hasattr(mode, "value"):
        mode_val = mode.value
    else:
        mode_val = str(mode)

    broker = (account.broker_code or "inter").lower()

    # Tastytrade USD accounts (live or sandbox) route to the Tastytrade adapter.
    # `live` is derived from execution_mode, and the adapter selects the matching
    # credential set (production vs sandbox) and base URL.
    if broker == "tastytrade":
        return TastytradeBrokerAdapter(live=(mode_val == ExecutionMode.live.value or mode_val == "live"))

    if mode_val == ExecutionMode.live.value or mode_val == "live":
        return InterManualBrokerAdapter()
    return SimulatedBrokerAdapter()
