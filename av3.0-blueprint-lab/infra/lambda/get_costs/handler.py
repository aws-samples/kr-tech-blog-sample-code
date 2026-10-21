"""Lambda handler for retrieving daily cost data.

GET /costs/daily
Queries AWS Cost Explorer for the last 14 days of account spend, broken out by
service.

WHY THERE IS NO TAG FILTER. This used to filter on Tags Project=av30-blueprint-lab
and returned $0.00 for every single day while the account was really billing up to
$269/day — so the admin dashboard was blind to cost, which is how four abandoned
notebook apps in other regions ran for ~85 days unnoticed. Measured, same window:

    no filter                          -> 269.01, 268.90, 268.89
    Tags Project=av30-blueprint-lab     -> 0, 0, 0
    Tags Workshop=av3-blueprint-lab     -> 0, 0, 0

Three independent reasons, all of which had to be true at once for the filter to
work, and none of which were:

1. Cost-allocation tags are not activated, and cannot be activated from here:
   ce:ListCostAllocationTags returns AccessDeniedException "Linked account doesn't
   have access to cost allocation tags." Only the Organization's management account
   can activate a tag key, and activation is NOT retroactive — it applies to usage
   going forward only. So even doing it correctly cannot recover past spend.
2. The key and value did not match reality anyway: participant profiles and spaces
   are tagged Workshop=av3-blueprint-lab (create_user), not
   Project=av30-blueprint-lab (note av3 vs av30).
3. A cdk.Tags stack tag only reaches CloudFormation-created resources. The GPU apps
   — where essentially all the money goes — are created at RUNTIME by create_user
   and change_instance, so they never carried the stack tag at all.

Unfiltered account spend is the honest number here because this account is
dedicated to the lab. GroupBy=SERVICE is included so an admin can see which service
the spend is in (and therefore spot non-lab spend) without a tag.
"""

import logging
import os
import sys
from datetime import datetime, timedelta, timezone

import boto3

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "shared"))

from errors import api_handler

logger = logging.getLogger()
logger.setLevel(logging.INFO)

# Boto3 clients — created at module level for connection reuse
ce = boto3.client("ce")

# Number of days to look back
LOOKBACK_DAYS = 14


@api_handler
def handler(event, context):
    """Get daily costs for the workshop project."""
    now = datetime.now(timezone.utc)
    end_date = now.strftime("%Y-%m-%d")
    start_date = (now - timedelta(days=LOOKBACK_DAYS)).strftime("%Y-%m-%d")

    logger.info(f"Querying costs from {start_date} to {end_date}")

    response = ce.get_cost_and_usage(
        TimePeriod={
            "Start": start_date,
            "End": end_date,
        },
        Granularity="DAILY",
        Metrics=["UnblendedCost"],
        GroupBy=[{"Type": "DIMENSION", "Key": "SERVICE"}],
    )

    costs = []
    service_totals: dict[str, float] = {}
    for result in response.get("ResultsByTime", []):
        date = result["TimePeriod"]["Start"]
        # With GroupBy set, Cost Explorer puts the money in Groups and leaves
        # Total empty — reading Total here would silently report 0.00 for every
        # day, which is the same failure this handler just came out of.
        groups = result.get("Groups") or []
        day_total = 0.0
        day_services: dict[str, float] = {}
        for g in groups:
            amount = float(g["Metrics"]["UnblendedCost"]["Amount"])
            if amount <= 0:
                continue
            service = g["Keys"][0]
            day_total += amount
            day_services[service] = round(amount, 2)
            service_totals[service] = service_totals.get(service, 0.0) + amount
        # Fall back to Total for any response that carries no Groups, so a future
        # change to the query cannot silently zero the chart.
        if not groups:
            day_total = float(
                result.get("Total", {}).get("UnblendedCost", {}).get("Amount", 0.0)
            )

        costs.append(
            {
                "date": date,
                # "cost", not "amount": web/admin/src/api/client.ts DailyCost declares
                # `cost` and CostsPage.tsx reads d.cost / c.cost / entry.cost. The key
                # was "amount", so every read was undefined -> the totals summed to NaN
                # and the chart's Y domain was NaN. Same field-name-contract break as
                # GET /sessions had; fixing the Cost Explorer query alone would still
                # have left this chart broken.
                "cost": round(day_total, 2),
                "byService": day_services,
            }
        )

    total = round(sum(c["cost"] for c in costs), 2)
    top_services = sorted(
        ({"service": s, "amount": round(a, 2)} for s, a in service_totals.items()),
        key=lambda x: -x["amount"],
    )[:10]
    logger.info(
        f"Retrieved {len(costs)} days of cost data, total: ${total}; "
        f"top service: {top_services[0] if top_services else 'none'}"
    )

    return {
        "costs": costs,
        "total": total,
        "currency": "USD",
        "periodStart": start_date,
        "periodEnd": end_date,
        "topServices": top_services,
    }
