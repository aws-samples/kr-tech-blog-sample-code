"""Lambda handler for retrieving module instance options.

GET /modules/{id}/instance-options

DEAD CODE — nothing calls this. `getInstanceOptions` exists in
web/user/src/api/client.ts but has ZERO call sites; the participant UI builds its instance
list from the STATIC data in web/user/src/data/pipeline-config.ts
(`recommendedInstance` + `alternatives`), rendered by InstanceOptionsPanel.

It is also wired to placeholder data. MODULE_CONFIG in shared/config.py is keyed
"module-1".."module-5" with notebooks "01-data-preparation.ipynb" etc., which are not this
lab: the real modules are M0..M12 (`M1_Data_Exploration.ipynb`, `M4_Cosmos_...`). So every
real module id 404s here, and the five ids that do resolve describe a workshop that does not
exist.

Two consequences worth knowing before touching this:
  * Do NOT "fix" MODULE_CONFIG expecting the participant dropdown to change — edit
    pipeline-config.ts, which is the only place that recommendation lives (and what
    scripts/check_quotas.py parses).
  * If you ever DO wire this endpoint up, `default_rate = INSTANCE_RATES.get(default, 0)`
    below becomes a bug: INSTANCE_RATES is now per-region, so a module whose default is not
    sold in the deploy region yields rate 0, and the `rate >= default_rate` filter then
    offers EVERY type — including the absent default.
"""

import logging
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "shared"))

from config import INSTANCE_RATES, MODULE_CONFIG
from errors import ApiError, api_handler

logger = logging.getLogger()
logger.setLevel(logging.INFO)


@api_handler
def handler(event, context):
    """Get instance options for a specific module."""
    # Extract moduleId from path
    path_params = event.get("pathParameters") or {}
    module_id = path_params.get("id")

    if not module_id:
        raise ApiError(400, "Missing moduleId in path")

    # Look up module configuration
    module = MODULE_CONFIG.get(module_id)
    if not module:
        raise ApiError(
            404,
            f"Module not found: {module_id}",
            details=f"Valid modules: {sorted(MODULE_CONFIG.keys())}",
        )

    # Build instance options with rates
    default_instance = module["instance_type"]
    default_rate = INSTANCE_RATES.get(default_instance, 0)

    # Return all instances at or above the module's minimum requirement
    available_instances = []
    for instance_type, rate in sorted(INSTANCE_RATES.items(), key=lambda x: x[1]):
        if rate >= default_rate:
            available_instances.append(
                {
                    "instanceType": instance_type,
                    "hourlyCost": rate,
                    "isDefault": instance_type == default_instance,
                }
            )

    return {
        "moduleId": module_id,
        "moduleName": module["name"],
        "defaultInstanceType": default_instance,
        "estimatedDurationMinutes": module["estimated_duration_minutes"],
        "availableInstances": available_instances,
    }
