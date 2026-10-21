"""AV 3.0 Blueprint Lab - Monitoring Construct.

SNS topic for admin notifications, email subscription, and daily AWS Budget alarm.
"""

from constructs import Construct

import aws_cdk as cdk
from aws_cdk import (
    aws_iam as iam,
    aws_sns as sns,
    aws_sns_subscriptions as sns_subscriptions,
    aws_budgets as budgets,
)

# The Region cost filter takes the region CODE ("ap-northeast-2"), not the Cost Explorer
# console's display name ("Asia Pacific (Seoul)").
#
# This file previously mapped codes to display names, on the belief that Cost Explorer
# identifies regions the way its console labels them. That is wrong, and it fails in the
# worst possible way: a display name is not rejected, it simply matches NOTHING, so the
# budget reports $0.00 for ever and never alarms. Measured in account <aws-account-id> over
# the same 14-day window:
#
#     filter                        UnblendedCost
#     (none)                        $1647.76
#     REGION = "us-west-2"          $ 950.18
#     REGION = "US West (Oregon)"   $   0.00     <-- silently no match
#     REGION = "ap-northeast-2"     $ 371.63
#     REGION = "Asia Pacific (Seoul)" $ 0.00     <-- silently no match
#
# `ce get-dimension-values --dimension REGION` returns ONLY codes (18 values plus
# "global"); no display name exists in the vocabulary at all. The deployed proof: the
# Seoul budget read ActualSpend 0.0 while Cost Explorer showed $371.63 of real
# ap-northeast-2 spend in the same period.
#
# That made the guardrail strictly worse than the unfiltered budget it replaced — that
# one at least alarmed. This repo's own history is the cost of a silent budget:
# $269/day ran unnoticed against a $200 limit for roughly 85 days.
#
# Using the code also removes a side effect of the old table: it raised for 7 regions
# that smd_images.py otherwise supports (af-south-1, ap-east-1, ap-southeast-3,
# eu-south-1, eu-west-3, me-central-1, me-south-1), hard-failing synth there.


class MonitoringConstruct(Construct):
    """Budget monitoring and admin notifications.

    Attributes:
        sns_topic: SNS topic for admin alert delivery.
    """

    def __init__(self, scope: Construct, construct_id: str) -> None:
        super().__init__(scope, construct_id)

        # Admin email from CDK context (optional during bootstrap; required for deploy)
        admin_email = self.node.try_get_context("admin_email") or "placeholder@example.com"

        # SNS Topic for admin notifications
        self._sns_topic = sns.Topic(
            self,
            "AdminTopic",
            topic_name="av30lab-admin-notifications",
            display_name="AV 3.0 Blueprint Lab Admin Notifications",
        )

        # Let AWS Budgets publish to this topic. Without it the budget fails validation
        # with "Unable to publish to SNS topic". This existed ONLY as hand-added drift
        # on the us-west-2 topic — the CDK declared no topic policy at all (verified:
        # 0 AWS::SNS::TopicPolicy in the synthesized template, while the live topic
        # carries Sid AllowAWSBudgetsPublish). So any fresh deployment, in any region,
        # would have produced a budget that could not alert. Scoped to this account so
        # another account's budget cannot publish here.
        self._sns_topic.add_to_resource_policy(
            iam.PolicyStatement(
                sid="AllowAWSBudgetsPublish",
                effect=iam.Effect.ALLOW,
                principals=[iam.ServicePrincipal("budgets.amazonaws.com")],
                actions=["SNS:Publish"],
                resources=[self._sns_topic.topic_arn],
                conditions={
                    "StringEquals": {"aws:SourceAccount": cdk.Stack.of(self).account}
                },
            )
        )

        # Email subscription for admin.
        #
        # WARNING — THIS RESOURCE REPORTS SUCCESS WITHOUT WORKING. An SNS email
        # subscription is not active until the recipient clicks the confirmation link,
        # and CloudFormation reports CREATE_COMPLETE as soon as the REQUEST is made. It
        # never waits for confirmation and never retries. SNS then deletes an
        # unconfirmed pending subscription after ~3 days.
        #
        # That is not hypothetical here: the subscription created 2026-07-02 showed
        # CREATE_COMPLETE in CloudFormation while sns:GetSubscriptionAttributes on the
        # very ARN CFN recorded returned "NotFound: Subscription does not exist", and
        # list-subscriptions-by-topic returned []. The daily budget alarm therefore had
        # nowhere to deliver for months — including three consecutive days of ~$269
        # spend against a $200/day budget, which is part of why four abandoned
        # notebook apps in other regions ran for ~85 days unnoticed.
        #
        # There is no way to confirm on the admin's behalf, so scripts/deploy.sh checks
        # for a CONFIRMED subscription after every deploy and warns loudly when there is
        # none. Do not treat a green CloudFormation resource here as a working alert.
        self._sns_topic.add_subscription(
            sns_subscriptions.EmailSubscription(admin_email)
        )

        # AWS Budget — daily $200 threshold with notification to SNS
        # Note: DAILY budgets only support ACTUAL notification type (not FORECASTED)
        budgets.CfnBudget(
            self,
            "DailyBudget",
            budget=budgets.CfnBudget.BudgetDataProperty(
                # Region-suffixed AND region-SCOPED. Both halves are required:
                #
                #  - The name: Budgets is an ACCOUNT-GLOBAL service and budget names are
                #    unique per account, so the old fixed "av30lab-daily-budget" made a
                #    second regional deployment hard-fail with DuplicateRecordException.
                #  - The filter: fixing only the name would give every region a budget
                #    with NO CostFilters, i.e. two budgets both measuring the entire
                #    account. Each would alarm at the combined total, neither could say
                #    which region overran, and a single region quietly using its whole
                #    allowance would trip the other region's alarm too.
                budget_name=f"av30lab-daily-budget-{cdk.Stack.of(self).region}",
                budget_type="COST",
                time_unit="DAILY",
                cost_filters={"Region": [cdk.Stack.of(self).region]},
                budget_limit=budgets.CfnBudget.SpendProperty(
                    amount=200,
                    unit="USD",
                ),
            ),
            notifications_with_subscribers=[
                budgets.CfnBudget.NotificationWithSubscribersProperty(
                    notification=budgets.CfnBudget.NotificationProperty(
                        comparison_operator="GREATER_THAN",
                        notification_type="ACTUAL",
                        threshold=100,
                        threshold_type="PERCENTAGE",
                    ),
                    subscribers=[
                        budgets.CfnBudget.SubscriberProperty(
                            address=self._sns_topic.topic_arn,
                            subscription_type="SNS",
                        ),
                    ],
                ),
            ],
        )

        # ACCOUNT-WIDE ceiling, opt-in via `-c account_budget=true`.
        #
        # Region-scoping the budget above closed one hole and opened another: with every
        # budget filtered to its own region, NOTHING measures the account total any more.
        # Two regions at $199/day each never alarm, and spend outside both regions — a
        # third region, or a non-lab service — is invisible to all of them.
        #
        # This is also a SEQUENCING TRAP on the first redeploy of an existing stack. The
        # live us-west-2 budget is still the pre-rename `av30lab-daily-budget` with
        # CostFilters null, i.e. the account's ONLY account-wide ceiling. Renaming a
        # Budget REPLACES it, so that redeploy deletes the last aggregate guardrail — the
        # exact class of gap that let ~$269/day run unnoticed here for ~85 days. Create
        # this one FIRST (or in the same change), not afterwards.
        #
        # Opt-in rather than automatic because budget names are ACCOUNT-GLOBAL: if every
        # regional deployment declared it, the second one would hard-fail with
        # DuplicateRecordException. Exactly ONE deployment in the account owns it — set the
        # flag there and leave it unset everywhere else. scripts/deploy.sh reports whether
        # an account-wide budget exists so this is a decision, not an accident.
        #
        # The subscriber is THIS region's topic, so the owning deployment's admin email is
        # where account-wide breaches land. That is deliberate: one owner, one inbox.
        if self.node.try_get_context("account_budget"):
            budgets.CfnBudget(
                self,
                "AccountBudget",
                budget=budgets.CfnBudget.BudgetDataProperty(
                    budget_name="av30lab-daily-budget-account",
                    budget_type="COST",
                    time_unit="DAILY",
                    # No CostFilters ON PURPOSE — this one must see everything.
                    budget_limit=budgets.CfnBudget.SpendProperty(
                        # int() is required: every -c value arrives as a STRING, and
                        # SpendProperty type-checks amount as int|float, so passing it
                        # through raw fails synth with
                        # "type of argument amount must be one of (int, float); got str".
                        amount=int(
                            self.node.try_get_context("account_budget_limit") or 400
                        ),
                        unit="USD",
                    ),
                ),
                notifications_with_subscribers=[
                    budgets.CfnBudget.NotificationWithSubscribersProperty(
                        notification=budgets.CfnBudget.NotificationProperty(
                            comparison_operator="GREATER_THAN",
                            notification_type="ACTUAL",
                            threshold=100,
                            threshold_type="PERCENTAGE",
                        ),
                        subscribers=[
                            budgets.CfnBudget.SubscriberProperty(
                                address=self._sns_topic.topic_arn,
                                subscription_type="SNS",
                            ),
                        ],
                    ),
                ],
            )

    @property
    def sns_topic(self) -> sns.Topic:
        """SNS topic for admin alert delivery."""
        return self._sns_topic
