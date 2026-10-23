# Triage Labels

The skills speak in terms of five canonical triage roles. This file maps those roles to the actual label strings used in this repo's issue tracker.

| Label in mattpocock/skills | Label in our tracker                | Meaning                                   |
| -------------------------- | ----------------------------------- | ----------------------------------------- |
| `needs-triage`             | `needs-triage`                      | Maintainer needs to evaluate this issue   |
| `needs-info`               | `needs-info`                        | Waiting on reporter for more information  |
| `ready-for-agent`          | `ready-for-agent`                   | Fully specified, ready for an AFK agent   |
| `ready-for-human`          | `ready-for-human`                   | Requires human implementation             |
| `wontfix`                  | `wontfix`                           | Will not be actioned                      |
| `claimed`                  | `claimed`                           | A wayfinder ticket someone is working     |
| `resolved`                 | `resolved (<yyyy-mm-dd>, <branch>)` | Done; the slice is in the area file's log |

When a skill mentions a role (e.g. "apply the AFK-ready triage label"), use the corresponding label string from this table.

The tracker here is local markdown (`issue-tracker.md`), so a "label" is the value of a ticket's `Status:` line.

No other label goes on a `Status:` line; a note in parentheses may follow it, as in `resolved (2026-10-08, <branch>)`. `scripts/check_plans.py` reads this table for the allowed values.

Edit the right-hand column to match whatever vocabulary you actually use.
