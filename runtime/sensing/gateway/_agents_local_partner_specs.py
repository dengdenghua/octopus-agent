"""Compatibility re-export — specs now live in the execution layer.

Kept so ``sensing.gateway`` importers keep working; new code should import
from :mod:`runtime.execution.agents.local_partner_specs` directly (the
execution layer is the correct home for subagent backend routing).
"""

from runtime.execution.agents.local_partner_specs import LOCAL_PARTNER_SPECS

__all__ = ["LOCAL_PARTNER_SPECS"]
