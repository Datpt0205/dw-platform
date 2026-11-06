---
status: Proposed
date: 2026-11-06
source:
    - ../../.claude/plans/go-live/customer-access/spec.md
    - ../../infra/keycloak/dw-realm.json
    - ../../packages/python/dw_platform/src/dw_platform/application/role_assignments.py
    - ../../packages/python/dw_platform/src/dw_platform/adapters/persistence/identity_provisioning.py
---

# 0200. Customer accounts are created through one narrow Keycloak admin client, and a sign-in account opens no company

## Context

An invitation creates a person with no sign-in and sends nothing. The realm has
self-registration and password reset off and no mail server, so the only way to
give someone a password today is an operator in the Keycloak admin console. No
customer can pass through that. Doing it for them makes the platform call the
identity provider's admin API, which it has never done: a new credential with
power over every user of the realm.

## Decision

1. `dw_platform` declares `IdentityProviderPort` with the calls it needs (create
   a user, send the set-password action email, disable a user); a Keycloak
   adapter satisfies it and only a composition root names the adapter.
2. The credential is a confidential client with service accounts on, holding
   `manage-users` of realm `dw` and nothing else. It is not `realm-admin`, it
   cannot touch clients or the `master` realm, and only the api process receives
   it. The worker and the web do not.
3. The set-password link is Keycloak's own action email, so the provider signs
   it and it expires there. The platform never sees or sends a password, and
   never holds a reset token.
4. Self-registration stays off everywhere. A sign-in account is not access:
   a verified identity with no invitation gets a user row and no membership,
   which `identity_provisioning.py` already guarantees and this must keep.
5. A failed call to the provider does not lose the invitation: the membership
   commits, and a lane retries the account creation with an idempotency key.

## Consequences

- A leaked client secret can create, disable and reset any user of the realm, so
  it is a deployment secret like the signing keys, rotated by runbook, and its
  use is audited on the platform side.
- The realm file only reaches an empty database (`--import-realm`), so settings
  added here need a step that applies them to a running cluster.
- If wrong: an operator script creates accounts by hand for the first customers,
  and the port stays unbuilt.
