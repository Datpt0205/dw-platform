---
status: Accepted (Đạt, 2026-10-23; amendments from the decision brief applied)
date: 2026-10-23
source:
    - ../../packages/python/dw_agent_runtime/src/dw_agent_runtime/contracts.py
    - ../../packages/python/dw_knowledge/src/dw_knowledge/contracts.py
    - ../../packages/python/dw_observability/src/dw_observability/redaction.py
    - ../../.claude/plans/studio/field-security/spec.md
    - ../../.claude/plans/studio/compliance-pdpl/spec.md
---

# 0106. Every field carries a personal-data category, and one application function decides field access from it and from roles on every path, agents and search included

Numbered in the block 0100-0199 reserved for Studio (ADR-0100 records the block). It rests on the requester's D3
("field-level security: hide or read-only per role, applied to agents and search results too"), on stance S14
(every field carries its personal-data category) and on the call on DO-36, decided 2026-10-23.

## Context

- **The law makes the category a design input.** The PDPL (Law 91/2025/QH15, passed 2025-06-26, in force 2026-01-01;
  unofficial English: https://static3.luatvietnam.vn/uploaded/vietlawfile/2025/7/91_2025_qh15_incom_110725173542.pdf)
  and Decree 356/2025/ND-CP (issued 2025-12-31, in force 2026-01-01; unofficial English translation:
  https://www.qtsc.com.vn/uploads/files/2026/02/02/356_2025_ND-CP_689146.pdf) list basic data (Art. 3) and sensitive
  data (Art. 4.1: health, location, ID images, bank data, "Data monitoring behavior and activities" in online services
  and more). Art. 4.2 requires "regulations on access authorization and restriction" for sensitive data; Art. 5 sets
  data-subject deadlines, a first response within 2 working days. Counsel has not yet confirmed this reading.
- **Nothing in the platform classifies a field.** Tool definitions declare `data_classification`
  (`packages/python/dw_agent_runtime/src/dw_agent_runtime/contracts.py:167`,
  `packages/python/dw_agent_runtime/src/dw_agent_runtime/tool_specs.py:54`) and no decision reads it (failure-modes
  #1). The clearance ladder (`packages/python/dw_knowledge/src/dw_knowledge/contracts.py:23-37`: internal, confidential,
  restricted) grades documents and memory, not fields. `packages/python/dw_observability/src/dw_observability/redaction.py:1`
  promises "secrets/PII" and redacts secrets.
- **Field security cannot live in PostgreSQL here.** Column privileges are per database role and one `dw_app` serves
  every user; tenant fields are slot columns shared across objects (ADR-0107); masking needs the value. The decision is
  therefore an application function, and every path that emits a value must call it.
- **A hidden field leaks through side doors.** Filtering or sorting on it is an oracle that a binary search turns into
  the value (si-platform `packages/python/platform/si_metadata/src/si_metadata/list_query.py`); approvals, run history,
  templates, indexes and error messages carry values past a projection. Microsoft notes that "Column-level security
  doesn't grant access to a record" (https://learn.microsoft.com/en-us/power-platform/admin/wp-security-cds, 2026-10-05).

## Decision

1. **Every field has a category.** `pd_category` is required on every platform or tenant field (custom-object fields, Data
   Hub schema fields, connector manifests' `pd_categories`) and on every tool schema property: `none`, `basic` or
   `sensitive`, a sensitive field also carrying `sensitive_type` from the Decree 356 Art. 4.1 list, plus the optional
   `subject_identifier` kind (email, phone, national_id, zalo_user_id, facebook_psid, tax_code, bank_account). One owner,
   `dw_kernel.personal_data`, holds the vocabulary; each table's CHECK equals the kernel list (a test). A field without
   a category is refused with 422 `pd_category_required`; the UI preselects from the field type and the admin confirms.
   The category drives field-security defaults, masking, model routing (ADR-0123: `sensitive` never leaves under
   `cross_border_minimised`), retention and data-subject requests. It is a separate axis from the clearance ladder, and
   per-property `pd_category` replaces `ToolDefinition.data_classification`.
2. **Fields are open or secured.** `access_mode` is `open` or `secured`, a property of the field in its object's
   `dw.object/v1` version. A field with `pd_category <> 'none'` starts secured, `basic` and `sensitive` alike. Opening a
   `basic` field widens access, so it is a new object version published through a second person (D11, ADR-0120),
   never a one-person switch and never a route of its own; securing a field again narrows, and takes one person and an
   audit event. A sensitive field is always secured (`ck_field_defs_sensitive_is_secured`) and can never be opened.
3. **Roles add read or edit on secured fields.** `studio.field_permissions` (`tenant_id`, `role_id`, `field_id`,
   `access`, `granted_by`, `granted_at`; `ck_field_permissions_access` read or edit; PK `(tenant_id, role_id, field_id)`;
   FKs `ON DELETE CASCADE` to the role and the field) carries `fld.<object>.<field>.read|edit` (ADR-0104), additively
   over every role a person holds in the tenant; `edit` counts only with object update reach and `read` only with object
   read reach (ADR-0105). Agents and workflows get the intersection with their boundary's field caps (ADR-0103).
4. **One function decides; the records adapter applies it on every path.**
   `resolve_field_access(principal_roles, object_security, boundary) -> FieldAccess` is pure, lives in the Studio access
   package and answers `hidden`, `read` or `edit` per field with the field-metadata version it used; formula fields
   inherit the strictest input, and a unique field cannot be hidden from a role that creates or updates the object. The
   records adapter selects only readable columns and slots; refuses a filter, sort, group-by or count on a hidden field
   before any SQL (422 `field_not_readable`); refuses a write to a non-editable field per field (403
   `field_not_editable`) and rolls back; and returns `hidden_fields`, listing every hidden field of the object whether
   its value is empty or not, so the UI shows "Đã ẩn" with a lock, never a blank, and the marker says nothing about
   emptiness. A hidden field's name is not secret, its value is: describe lists the field as `access: hidden`
   (ADR-0107). The paths, by name:
   REST projection, filters and exports; workflow data nodes and `{{ }}` templates (a hidden reference fails the node
   with `template_field_hidden`); agent object tools (schema narrowed per run to the boundary's fields); search and
   knowledge indexing (open, non-personal fields only, stamped with `fls_version`); record history and outbound
   webhooks; run-history payloads and approvals (references and field names stored, values fetched live and masked for
   the viewer); telemetry, logs, audit and error messages (field names, never values). An architecture test keeps the
   records table and its slot columns named only in the records adapter.
5. **Sensitive reads leave a trace.** A response carrying sensitive values writes one audit event `pd.read` with record
   ids and field names only. From W1, granting read on a sensitive field takes a second person, because every `fld.*`
   grant is a two-person role change (ADR-0104 decision 10), and a role carrying one counts as critical for
   `platform.roles.bind`.
6. **Nobody approves masked content.** An approval's audience must hold read on every field its content references, as
   the workflow stamps them; approver candidates are found by role depth through `platform.effective_grants` (DO-36,
   decided 2026-10-23). Field security owns this rule and tenant-rbac only points to it: the candidate picker calls
   it, and `decision_guards["studio.step.approval"]` (ADR-0112) applies it again at `decide`, through tenant-config/05's
   async guard when it reads the database, so a decider who lost read since the approval opened is refused.
7. **One data-subject request service.** It declares `DataSubjectPort` (find, restrict, export, erase), and one
   dispatch table at the composition root registers an implementation per personal-data store: custom-object records,
   Data Hub event history, run step input and output with `worker_runs.input` and `result`, `tool_executions.output`
   and checkpoints, knowledge rows, vectors and stored text, memory, consents and send logs, files, exports,
   notifications and caches. A data subject is found by exact match on normalised `subject_identifier` values, never by free
   text. `platform.dsr_requests` (tenant RLS) holds the type, `received_at`, `first_response_due`, `completion_due` and
   a receipt per port; deadlines count Vietnamese working days from `configs/policies/vn_working_days@2026.yaml`, which
   names an owner; erasure is a hard delete, or crypto-shredding where a row cannot be deleted.
8. **A second language reads record values through the API.** Field security lives in the application, so a non-Python
   service may use the database as CLAUDE.md:77-120 allows but reads Studio record values only through the platform API.
9. **Detection supports and never decides.** Presidio with Vietnamese recognizers (CCCD and CMND, phone, tax code, bank
   account, email, names through an NER model chosen by measurement, addresses) runs at three choke points: before a
   `cross_border_minimised` model call (placeholders, the mapping kept in Vietnam per run with a TTL), as a custom
   detector in LangChain's `PIIMiddleware` for tool results and outputs, and in the telemetry exporter. It is measured
   on at least 500 labelled synthetic Vietnamese snippets (precision and recall per entity; recall first for telemetry,
   precision first for model calls) before anything relies on it; the personal-data category stays the primary control,
   and detection covers free text (chats, email bodies, documents). Presidio 2.2.364 is MIT and maintained
   (https://pypi.org/pypi/presidio-analyzer/json, release of 2026-07-22, read 2026-10-22); `PIIMiddleware`'s built-in
   types are email, credit card, IP, MAC and URL only (https://docs.langchain.com/oss/python/langchain/middleware/built-in,
   undated), hence the custom detector.

## Alternatives considered

- **Field security in PostgreSQL column grants or RLS.** Rejected: tenant fields are slot columns shared across objects,
  one `dw_app` serves every user, and masking needs the value.
- **An optional personal-data category.** Rejected: a field without one reads as permissive (failure-modes #7).
- **A category per object.** Rejected: one sensitive field would taint every field, and masking needs fields.
- **Detection as the primary control.** Rejected: recall on Vietnamese text is unmeasured and a miss is a disclosure.
  Within detection, LLM Guard is archived (GitHub API, 2026-10-22), guardrails sold as a service move data abroad, and
  regex alone misses names and addresses.
- **A data-subject request code path per store.** Rejected: the store nobody remembered is the breach; registration at
  the composition root makes the list checkable.
- **Per-role "hidden" overrides on open fields; SQL views with a CASE per slot; hiding in the UI only.** Rejected: not
  additive (a second role silently undoes the first), a second implementation, and CLAUDE.md:193.

## Consequences

- **A category before publish.** custom-objects, tools-and-skills and connector manifests (`pd_categories`) must set a
  category on every field and schema property before publish; every field-definition table carries the columns and the
  CHECK.
  compliance-pdpl owns the vocabulary (compliance-pdpl/01) and the data-subject request service; telemetry-and-audit
  masks steps at read with the same function.
- **Tests that must exist.** For each path named in point 4, a role without the field grant receives `hidden_fields`
  and no value, and removing the check on that path turns its test red (field-security/02); a filter or sort on a
  hidden field is refused before SQL; an agent tool schema omits the field; opening a sensitive field fails on the
  CHECK; a registry test fails a table holding personal-data fields without a `DataSubjectPort`; Presidio has a measured
  threshold per choke point before it is switched on.
- **Phasing.** W1 secures the lead's personal fields (phone, email, full name) by default and masks them on every path
  the slice uses; the matrix screen, exports, knowledge, the sensitive-read audit, data-subject requests and Presidio
  come in W2.
- **Harder.** Every new path that emits record values must call the function; checkpoints and run history should hold
  record references rather than values (FOG-37); Presidio costs CPU on hot paths and grows the image by an NLP model.
- Contradicts CLAUDE.md:77-120 (a second language may connect to the database under four conditions): adds "reads
  Studio record values only through the API" for Studio record tables; worth reopening because a direct read as
  `dw_app` sees every field a record has, while field security is decided in the application.
- Replaces the declared-only `data_classification` (`contracts.py:167`, `tool_specs.py:54`) with a category that has
  readers, and corrects `redaction.py:1` to say "secrets".
- **si-platform.** Re-derived; no si-platform code is ported for field security. It diverges from si-platform's default
  allow and view-all bypass (`packages/python/platform/si_security/src/si_security/domain/permissions.py`) and from its
  `si.fields`, which has no personal-data column; the hidden-field oracle refusal arrives with the port of si-platform's
  `list_query.py` that ADR-0107 records.

## Open

1. **DO-34 (counsel and requester, before P1; Đạt for the second person).** Is basic personal data, a person's name
   included, secured by default and openable by an admin with an audit event; must reads of sensitive values be logged
   (one event per response, ids and field names only); does granting read on a sensitive field take a second person
   (v1.5)? Counsel confirms Decree 356 Art. 4.2. Answered 2026-10-23: `basic` and `sensitive` fields are secured at
   creation, a `basic` one opens only through two people and a sensitive one never (DO-34.1 (a)); reads of sensitive
   values are audited per response (YC24, W2); the second person for sensitive read grants applies from W1. Counsel's
   questions on Art. 4.2 and 4.1(l) go out with compliance-pdpl/02, and their answer changes only a field's
   `pd_category`, through a new object version (DO-34.2 (a)).
2. **DO-13 (Đạt, before W1).** Second-language services read Studio record values only through the platform API,
   amending CLAUDE.md "A second language"? Answered 2026-10-23: yes, decision 8 (DO-13.3 (a)).
3. **DO-36 (requester).** Provisional call (agent, 2026-10-23, option (a)): the audience must hold read on the fields an
   approval shows, and candidates are found by role depth. If wrong: approvers decide over `hidden_fields` markers, and
   candidates narrow to the run's workspace. Answered 2026-10-23: option (a), owned here and applied by the step
   approval's decision guard (decision 6, DO-36 (a)).
4. **DO-07 (answered by D11).** "Two people for every tenant configuration change" is read here as configuration in
   the sense of ADR-0110; if it covers role assignments and field grants too, the second person for sensitive read grants moves
   from v1.5 into W1. Answered 2026-10-23 (the requester and Đạt): D11 covers role assignments and field grants
   (ADR-0104), an object's `default_access`, a field's `access_mode` and every `dw.object/v1` publish; a change that
   narrows takes one person and an audit event, one that widens two. The second person for sensitive read grants is
   therefore in W1 (decision 5).
5. **FOG-77 (prototype).** Presidio's precision and recall on Vietnamese names, addresses, CCCD and phone numbers,
   which decides whether `cross_border_minimised` can be offered at all.
6. **FOG-74 (research).** The October 2026 status of Decree 356 Art. 4.2 and whether lead-ad, UTM and social-profile
   fields are behavioural-monitoring sensitive data under Art. 4.1(l), which would change the pilot's field defaults.
   Answered in part 2026-10-23: the questions go to counsel with compliance-pdpl/02, the pilot runs on simulated leads
   until counsel answers (YC89), and an answer that makes a pilot field sensitive changes its `pd_category` through a
   new `dw.object/v1` version, never the code (DO-34.2 (a)).

## Acceptance (2026-10-23)

- Status Accepted by Đạt with the decision brief's amendments.
- Decision 2: the CHECK is `ck_field_defs_sensitive_is_secured`; `access_mode` lives in the object's `dw.object/v1`
  version, opening a `basic` field takes a second person and securing one takes one person and an audit event
  (D:field-security:R1.4~requirements.md:D11 (a), D11 override, DO-34.1 (a)).
- Decision 4: `hidden_fields` lists every hidden field whatever its value, describe lists it as `access: hidden`, and
  the refusal codes carry their statuses (B:custom-objects:R6.5~field-security:R3.3 (a)).
- Decision 5: the second person for sensitive read grants moves from v1.5 into W1, and such a role is critical for
  `bind` (DO-09.2 (a), DO-32.1).
- Decision 6: field security owns the approver rule and the step approval's decision guard applies it (DO-36 (a)).
- Open 1 to 4 answered, Open 6 answered in part.
