"""Usage and limits (ADR-0121): the dated price book that is the one owner of
what a call costs, the per-call usage ledger, and the daily roll-up the usage
screen reads. The agent runtime declares the ports this package answers
(`PricingPort`, `UsageRecorderPort`) and never imports it."""
