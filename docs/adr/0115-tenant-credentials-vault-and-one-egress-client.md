---
status: Accepted (Đạt, 2026-10-23; amendments from the decision brief applied; OpenBao and smokescreen ship only after spike 21 (FOG-25) measures unattended unseal and Transit parity)
date: 2026-10-23
source:
    - ../../.claude/plans/studio/connections-and-vault/spec.md
    - ../../packages/python/dw_kernel/src/dw_kernel/net_guard.py
    - ../../apps/api/src/dw_api/settings.py
    - ../../scripts/backup_postgres.sh
---

# 0115. Tenant credentials are envelope-encrypted under a per-tenant key, used only through connections that one rule admits, and leave only through one address-pinning egress client

Numbered 0115 in the block 0100-0199 that ADR-0100 reserves for Studio. It rests on the requester's D8 (tenants bring
their own models and keys in v1, so tenant secrets become data the platform holds), D13 (tenant model keys stay in the
platform's vault and are injected per call into the model proxy) and D14 (the primary host grows to at least 4 vCPU /
16 GB before OpenBao and the egress proxy ship). The shape of vault, broker and egress is stance S10.

## Context

- Nothing stores a tenant secret today: deployment secrets come only from the environment
  (`apps/api/src/dw_api/settings.py:1`, "secrets only via environment"), and `dw_connectors` promises "credential
  references" (`packages/python/dw_connectors/pyproject.toml:4`) that no code holds. Studio needs OAuth tokens (Zalo
  OA, Meta Pages, Google), API keys for HTTP tools, signing secrets for Data Hub and outbound webhook endpoints, MCP
  credentials and model keys (D8).
- The one address check, `ensure_allowed_outbound_url` (`packages/python/dw_kernel/src/dw_kernel/net_guard.py:49-75`),
  vets a configured base URL. It refuses private, loopback, link-local, reserved and unspecified answers
  (`net_guard.py:36-46`) but not the other non-global forms (multicast, IPv4-mapped, 6to4, Teredo, NAT64), and it does
  not pin what it checked, so an answer that changes between check and connect passes. Tenant-defined destinations
  (HTTP tools, MCP servers, webhooks, model base URLs) turn that gap into a path to the internal network.
- Decree 356/2025/ND-CP Art. 12.4 asks that personal data in cloud computing be "encrypted both at rest and in transit"
  (unofficial translation, <https://www.qtsc.com.vn/uploads/files/2026/02/02/356_2025_ND-CP_689146.pdf>); a provider
  token unlocks exactly that data.

## Decision

1. **The vault.** Every tenant secret is an AES-256-GCM envelope in `platform.secret_envelopes`: a fresh data key per
   write, kept wrapped beside the ciphertext by the tenant key `tenant-<tenant_uuid>` (`aes256-gcm96`, not exportable)
   in self-hosted OpenBao Transit behind `KmsPort` (`ensure_tenant_key`, `generate_data_key`, `decrypt_data_key`,
   `rewrap`, `destroy_tenant_key`); `LocalDevKms` serves only outside deployed profiles (`validate_for_profile`
   refuses it when `is_deployed`). Each row names its secret's `field text NOT NULL` and
   `secret_version integer NOT NULL`, the credential version a run manifest pins (ADR-0109 decision 6), which rises
   when the secret's value changes and never on a rewrap; a row is unique per tenant, subject, field and secret
   version, so a rotation with an overlap, such as a signing secret's 24 hours, holds two versions side by side. The
   AAD, `dw.secret.v1|<tenant_id>|<owning_workspace_id>|<subject_kind>:<subject_id>|<field>|<secret_version>` (the
   subject kind being its FK column's name without `_id`, such as `connection` or `inbound_endpoint`), binds tenant,
   owning workspace, subject, field and the version of the secret, unchanged by rewrap: a rewrap wraps only the data
   key again, so the AAD stays the same and the envelope still opens, while an envelope copied to another row, field,
   version or subject fails the tag check. The key is chosen from the run's or access context's tenant, never from the
   row. `dw_app` holds no privilege on the table: four SECURITY DEFINER functions (`platform.put_secret`,
   `platform.open_secret`, `platform.secret_status`, `platform.delete_secret`), each narrowing by `app.tenant_id`, are
   the one database door, and only the credential broker decrypts. A secret never enters graph state, tool arguments,
   checkpoints, traces, logs or audit, and the API never returns one (write-only fields; a signing secret the platform
   generates is shown once). A new subject (OAuth client, outbound webhook endpoint, inbound endpoint, MCP server
   registration, model connection) is one nullable FK plus a widened `num_nonnulls(...) = 1` CHECK. An unreachable KMS
   fails the call with `kms_unavailable`; nothing falls back to plaintext or to a Valkey cache. A tenant key rotates
   every 90 days (`rewrap`), and tenant-supplied keys (BYOK) come after v1. Offboarding destroys the tenant key
   (crypto-shredding). The shredding takes effect once the oldest key-store backup that still holds the key has
   expired, since an older OpenBao backup could still decrypt an older database backup: the key store's backups are
   kept under a written term no longer than the data backups', and the restore drill checks both.
2. **Connections and the one rule.** `platform.connections` holds one authorized link to one external account, owned
   by a workspace (`share_scope` `owner`, `workspace` or `workspace_subtree`) or, from v1, by one user. RLS is
   tenant-only, because reach crosses the workspaces of a tenant by design (D1), and the table is listed as tenant-wide
   with that reason under amendment A6 (ADR-0100); the status machine is the database's
   (`platform.guard_connection_status`). Disabling a connection takes one person, audited; enabling it again takes two:
   the request opens a strict run-less approval `connections.enable`, stamped `required_scope = connections.manage`
   (ADR-0004), and only its `.decided` handler moves the connection from `disabled` to `active`, auditing the decider
   with the lane in `details.lane` (ADR-0011; D11, closing with one person and opening with two).
   `connection_usable(connection, context, purpose)`, one function in the platform's connections application layer,
   is the single answer to "may this run use this connection now": same tenant, `status = 'active'`, the run's
   workspace equal to the owning one or inside its sub-tree under `workspace_subtree`, `connections.use` held there,
   and for a personal connection the owner acting or a delegation covering the run's definition. It is asked when a
   binding value is approved (ADR-0110), at run admission and before every egress call.
3. **Personal connections.** A personal connection acts in a background run only through a revocable delegation
   (`platform.connection_delegations`: one workflow or agent, granted by the owner, expiring at most 365 days after
   the grant, its effective state derived by one function). P1 ships workspace-shared connections only, so no
   personal column exists before something reads it (failure-modes #1).
4. **One OAuth broker** owns every authorization-code flow, MCP's included (`platform.oauth_flows`, `purpose`
   `connect`, `reauth` or `mcp`): PKCE S256; a 256-bit `state` stored only as its SHA-256, single-use, bound server-side
   to tenant, workspace, user and provider and consumed by one conditional `UPDATE` in SECURITY DEFINER
   `platform.consume_oauth_flow`; an issuer check where the server sends `iss` (RFC 9207); one fixed callback per
   provider under `/api` (`GET /api/v1/connections/oauth/callback/{provider_key}`), the tenant taken from the flow row,
   never from the query. A connection becomes `active` only after the initiating user confirms while signed in as
   themselves, within 10 minutes, else its tokens are revoked. Refresh is single-flight through a 30-second claim on
   the connection row (`refresh_lease_until`), because Zalo issues a new refresh token on each refresh and kills the
   old one (forum reports, unverified against Zalo's documentation); lane `oauth_refresh` refreshes ahead, auditing as
   `system:oauth_refresh` (ADR-0011). The OAuth client is the tenant's own if configured (`platform.oauth_clients`),
   else the platform's, never another tenant's.
5. **One address policy.** `dw_kernel.net_guard` gains `forbidden_address(ip)`, refusing every address that is not
   global (and multicast, private, loopback, link-local, reserved, unspecified), applied recursively to IPv4-mapped,
   6to4, Teredo and NAT64 (`64:ff9b::/96`) forms, and `resolve_checked(host, port)`, which resolves once and refuses
   if any answer is forbidden. `ensure_allowed_outbound_url` uses the same function.
6. **One egress client** carries all tenant-directed traffic: connector actions, HTTP and OpenAPI-imported tools,
   outbound webhooks, and OAuth token, revoke and discovery calls. It connects to the address `resolve_checked`
   returned (`PinnedNetworkBackend` on `httpcore`) and verifies TLS against the hostname; sets `trust_env=False`;
   follows no redirect unless a connector manifest allows up to 3, each re-validated, dropping auth headers on an
   origin change; allows only `https` when deployed; caps a response at 2 MiB while streaming; limits catalogue
   connectors to their manifest `egress_hosts` and tenant-defined destinations to `platform.egress_allowed_hosts`
   (managed with `integrations.admin`; no IP literals; one wildcard level, never on a public suffix; a host is added
   only by the `.decided` handler of a strict run-less approval `egress.allowed_host`, stamped
   `required_scope = integrations.admin` (ADR-0004), that a second person decides, and removed by one person,
   audited); keys rate limits by provider app, connection and tenant; owns retries (a timed-out non-idempotent POST
   is `outcome_unknown`, never retried); scrubs the call's secrets from bodies, errors and logs; and in `simulate`
   refuses every purpose except `model` and read-only actions (`egress_blocked:run_mode`). An architecture test
   allows `httpx.AsyncClient(` only in the egress package and the existing operator-configured adapters.
7. **The egress proxy.** In deployed profiles smokescreen (<https://github.com/stripe/smokescreen>, MIT, built from a
   pinned commit) runs on networks of its own (`dw-egress-in`, internal, shared with api, worker, the MCP gateway and
   the model proxy; `dw-egress-out`, smokescreen alone; never `dw-edge`) as a second layer that decides nothing
   tenant-specific: role `catalog` enforces the union of manifest hosts, role `tenant` admits any global address. The
   per-tenant allowlist stays in Python. The proxy is mandatory before the first tenant-defined HTTP destination (W2:
   HTTP tools, webhooks, MCP servers, model base URLs), and `validate_for_profile` refuses a deployed profile that
   enables a tenant-defined HTTP destination without `DW_EGRESS_PROXY_URL`. SMTP is outside that rule: P1's one
   tenant-defined destination, the SMTP host, is resolved once by `resolve_checked` and reached at the address it
   pinned (decision 5), without the proxy. The MCP gateway and the model proxy reach the internet only through it.
8. **Webhooks and signatures.** Outbound webhooks are tenant-registered HTTPS endpoints (`platform.webhook_endpoints`)
   fed from the outbox in ADR-0006's shape (`platform.webhook_deliveries`, whose rows enter only through SECURITY
   DEFINER `platform.enqueue_webhook_deliveries`) and signed per Standard Webhooks 1.0 (`webhook-id`,
   `webhook-timestamp`, `webhook-signature` over the exact bytes; v1 HMAC-SHA256, v1a Ed25519; both signatures during
   a 24-hour rotation; <https://github.com/standard-webhooks/standard-webhooks/blob/main/spec/standard-webhooks.md>).
   One pure module owns that signing and every inbound signature verifier: a `SignatureVerifier` Protocol and one
   `VERIFIERS` table keyed by scheme (`standard_webhooks_v1`, `standard_webhooks_v1a`, `static_header_token`,
   `meta_x_hub_signature_256`, and `zalo_oa_zevent` until it is measured), with a 5-minute timestamp tolerance. An
   outbound event is thin by default. An endpoint carries personal data only once `include_personal_data` is switched
   on for it, audited; a principal named on the endpoint then decides what stays hidden, as the record API does for its
   caller (YC24, ADR-0106), and an endpoint abroad must pass the residency route class (ADR-0123) (DO-58 (b)).

## Alternatives considered

- **Secrets in OpenBao KV with a reference in Postgres.** Rejected: a second system of record (`CLAUDE.md:61`) and one
  more failure domain on every read, with no RLS and offboarding and backups split across two stores.
- **pgcrypto under one platform key, or one Transit key with derived contexts.** Rejected: no per-tenant
  crypto-shredding at offboarding, and with pgcrypto the key travels through SQL.
- **HashiCorp Vault.** Rejected: BUSL 1.1 restricts hosted or embedded competitive use
  (<https://raw.githubusercontent.com/hashicorp/vault/main/LICENSE>); OpenBao is MPL-2.0
  (<https://raw.githubusercontent.com/openbao/openbao/main/LICENSE>), both read by the research on 2026-10-22.
- **An HTTP client per cluster.** Rejected: the next raw client is unguarded.
- **In-process checks only, no smokescreen.** Rejected: one forgotten client or redirect reaches the internal network
  (<https://cheatsheetseries.owasp.org/cheatsheets/Server_Side_Request_Forgery_Prevention_Cheat_Sheet.html>).
- **Squid or Envoy as the egress proxy.** Rejected: heavier to run, and no simple per-role CONNECT allowlist; the
  fallback if smokescreen proves unbuildable.
- **A hosted secret manager or OAuth broker abroad.** Rejected: tenant credentials leave Vietnam, and the fact gets a
  second owner.

## Consequences

- OpenBao (P1) and smokescreen (before the first tenant-defined HTTP destination, W2) are new tier-0 services under
  the deployable admission rules, and they ship only after spike 21 (FOG-25) measures unattended unseal and Transit
  parity; the host grows first (D14), sized by measurement (FOG-23). tools-and-skills, mcp-client, model-connections
  and workflow-triggers consume the vault, the usable rule and the egress client rather than building their own.
- Only OpenBao and smokescreen wait for the spike: `KmsPort`, `LocalDevKms`, `platform.secret_envelopes` with its
  definer functions, and the address policy that closes the gaps of `net_guard.py:36-46` (decision 5) go ahead now.
- OpenBao's storage joins the backup job, under decision 1's retention term, and the restore drill:
  `scripts/backup_postgres.sh:26` backs up the `dw` database only, so a green drill could not see the keys
  (failure-modes #0).
- Migrations: `platform.secret_envelopes` (RLS ENABLE and FORCE, no grant to `dw_app`), `platform.connections`,
  `platform.oauth_flows`, `platform.oauth_clients`, `platform.egress_allowed_hosts`, `platform.webhook_endpoints`,
  `platform.webhook_deliveries` and the definer functions; `platform.connection_delegations` with personal connections.
- Tests that must exist, each red when its guard is removed: `test_privileges.py` asserting `dw_app` holds nothing on
  `platform.secret_envelopes`; an envelope copied to another field, secret version or subject failing to decrypt
  while a rewrapped one still opens (decision 1); RLS coverage of every new table; a canary running a workflow and an
  agent against a mock provider that echoes the `Authorization` header and the key, then finding no secret in
  checkpoint blobs, `platform.tool_executions`, `platform.audit_events`, spans or logs; the address policy over
  mapped, 6to4, Teredo and NAT64 forms; a DNS answer changed after the check still reaching only the pinned address; a
  replayed `state` doing nothing; the OAuth client never resolved sideways (mirroring `test_tenant_overlay.py`).
- Harder: an extra hop per call, a Go image to maintain, an unseal after every OpenBao restart; an operator endpoint on
  CGNAT space (`100.64.0.0/10`) is refused after the change unless allow-listed.
- The existing outbound URL check folds into the one address policy, so startup checks and the egress client cannot
  disagree. `CLAUDE.md:124-129` (Required stack) gains "OpenBao (Transit) holds tenant keys, and smokescreen is the
  egress proxy in deployed profiles" (amendment A10).
- `CLAUDE.md:116-120` (a second language must not take over "anything that decides"): OpenBao and smokescreen are Go,
  but each decides only an infrastructure fact (may this process identity use this key; is this address global);
  whether a connection may be used stays in Python. `apps/api/src/dw_api/settings.py:1` stays true for deployment
  secrets only; its docstring is amended on acceptance.
- Reuses `docs/adr/0006-provider-neutral-channel-delivery-outbox.md`'s outbox shape but contradicts its line 67
  ("Another channel (email) is one CHECK value and one adapter, not a new table"): a webhook is a tenant destination
  with a credential and a days-long schedule, not a channel to a person, so it gets a sibling table; worth reopening
  that sentence for this case. Leaves `docs/adr/0009-hosting-on-three-hostnames-behind-caddy.md`'s networks unchanged.
- si-platform: re-derived, since si-platform has no vault and no connections; Studio diverges from its
  `client_secret_ref` shape (si-platform `db/si/migrations/0006_platform.sql`, under si-platform
  `docs/adr/0035-each-tenant-signs-in-with-its-own-idp.md`). smokescreen never connects to the database (si-platform
  `docs/adr/0027-a-second-language-never-owns-tenant-isolation.md`).

## Open

1. **DO-47 (Đạt and operator).** Accept OpenBao as a tier-0 service with an unattended unseal path (integrated storage
   or its own database); the `dw-egress` networks with smokescreen built from a pinned commit, mandatory before the
   first tenant-defined destination; a 90-day tenant key rotation; tenant-supplied keys in v2? Answered 2026-10-23:
   OpenBao Transit from P1 with an unattended unseal as FOG-25 measures it, key-store backups and a 90-day rotation;
   tenant-supplied keys after v1 (DO-47.1 (a)); smokescreen mandatory before the first tenant-defined HTTP
   destination (W2), P1's SMTP host pinned by address only (DO-47.2 (a)). Both ship only after spike 21.
2. **DO-48 (requester; counsel on fan-out).** Workspace-shared connections only in P1? Answered 2026-10-23: yes, with
   generic SMTP as the P1 email path; OAuth flows and personal connections are W2 (DO-48.1 (a)).
3. **DO-24.** Answered 2026-10-23 by D14: at least 4 vCPU / 16 GB before OpenBao and the egress proxy ship; the sizes
   are fixed only after FOG-23 measures them.
4. **DO-58 (requester and counsel, before GA).** May outbound webhook payloads carry personal data? Answered
   2026-10-23 (DO-58 (b)): thin by default, and personal data only on an endpoint switched to it, as decision 8 says.
5. **FOG-25 and FOG-26 (prototypes).** OpenBao 2.7.x Transit parity with the documented API (`datakey/plaintext`,
   `rewrap`, `deletion_allowed`), latency, unseal and the need for a data-key cache; smokescreen's build, role
   identification without mTLS, deny ranges and CONNECT through `httpx2`. Spike 21 is the condition this ADR was
   accepted on.

## Acceptance (2026-10-23)

Accepted by Đạt on 2026-10-23, on condition that OpenBao and smokescreen ship only after spike 21 (FOG-25) measures
unattended unseal and Transit parity, with these amendments from the decision brief:

- Decision 1: a 90-day key rotation and BYOK after v1; crypto-shredding takes effect only once the oldest key-store
  backup holding the key has expired, so key-store backups are kept no longer than data backups and the restore drill
  checks both (DO-47.1 (a)).
- Decision 2: `platform.connections` is listed as tenant-wide under amendment A6.
- Decision 7: the proxy is mandatory before the first tenant-defined HTTP destination (W2), and `validate_for_profile`
  checks HTTP destinations only; P1's SMTP host is pinned by address without the proxy (DO-47.2 (a)).
- Decision 8: outbound events are thin by default; personal data is switched on per endpoint, audited, with hidden
  fields and the residency route applied (DO-58 (b)).
- Consequences: what waits for the spike and what goes ahead now; the A10 sentence written out.
- Open: DO-47, DO-48, DO-24 and DO-58 answered; FOG-25 and FOG-26 stay open as the condition.

## Amendments (2026-10-24)

Amended on 2026-10-24 by the requester and Đạt, who scoped the remaining D11 cases:

- Decisions 2 and 6: enabling a disabled connection again and adding an allowed host each take a second person,
  through the strict run-less approvals `connections.enable` and `egress.allowed_host`, whose `.decided` handlers
  apply the change; disabling a connection and removing an allowed host take one person, audited.
- Third consistency check (round 4), Đạt's V4.5: `connections.enable` is stamped `connections.manage` and
  `egress.allowed_host` is stamped `integrations.admin`, each the key that manages that change (decisions 2 and 6;
  D:ADR-0115~connections-and-vault:spec).
- Third consistency check (round 4), second pass: decision 1 writes out the AAD, whose version is the secret's
  `secret_version`, unchanged by rewrap, and the columns `field` and `secret_version` with their uniqueness, because
  the round-3 fix had put the key's version in the AAD, which every `transit/rewrap` would change, so the first
  rotation would have broken every envelope (F:ADR-0115\~connections-and-vault:R1.4); a test copies an envelope to
  another field, secret version and subject and rewraps one. The planner's provisional call; if it is wrong, the
  rotation lane encrypts every envelope again under a new data key instead of rewrapping it, and the AAD may then
  carry the key's version.
