"""High-Vol Dip strategy package.

`run_hv_dip_cycle` is exposed lazily (PEP 562): importing it eagerly would pull
`engine`, which imports `app.services.orders`. Since `orders` now depends on
`hv_dip.sizing`, an eager re-export would make any `hv_dip.*` submodule import
circular. Lazy access keeps `from app.services.hv_dip import run_hv_dip_cycle`
working for the worker and scripts while letting light submodules stand alone.
"""

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # pragma: no cover - typing only
    from app.services.hv_dip.engine import run_hv_dip_cycle

__all__ = ["run_hv_dip_cycle"]


def __getattr__(name: str) -> Any:
    if name == "run_hv_dip_cycle":
        from app.services.hv_dip.engine import run_hv_dip_cycle as _run

        return _run
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
