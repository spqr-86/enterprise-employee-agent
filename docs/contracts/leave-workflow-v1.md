# Leave workflow contract v1

Status: frozen for v0.1 implementation. This is a local educational workflow, not GitLab,
Tilt, Okta, or HRIS behavior. It does not determine eligibility or accept diagnoses, medical
documents, or other clinical details.

The executable source of truth for enums, validation, transitions, command metadata, preview
digests, and projection field sets is `enterprise_employee_agent.leave.contracts`. The
server-selected demo identities and negative access cases are versioned in
`data/synthetic_protected/demo-access-v1.json`.

## Request fields

| Field | Type and validation | Visibility |
|---|---|---|
| `request_id` | Server-generated non-empty identifier | employee, reporting manager, HR |
| `employee_id` | Server-selected identity; never accepted from model output | employee, reporting manager, HR |
| `status` | One declared `LeaveStatus` | employee, reporting manager, HR |
| `version` | Positive integer, incremented by every draft/workflow mutation | employee, HR |
| `start_date` | ISO date | employee, reporting manager, HR |
| `end_date` | ISO date, not before `start_date` | employee, reporting manager, HR |
| `request_type` | `continuous` or `intermittent`; not a legal eligibility decision | employee, reporting manager, HR |
| `employee_comment` | Optional untrusted free text, whitespace-normalized, at most 500 characters; persistence requires a separate fail-closed sensitive-content review | employee, HR |
| `clarification_question` | Optional HR operational question; no diagnosis request | employee, HR |
| `updated_at` | Timezone-aware server timestamp | employee, HR |
| `action_history` | Append-only events whose actor is the employee | employee only |
| `audit_history` | Append-only authorized event projection | HR only |

The executable contract exposes separate strict `EmployeeLeaveProjection`,
`ManagerLeaveProjection`, and `HrLeaveProjection` output models without inheritance between trust
levels. The employee projection contains request details plus only that employee's action history.
The manager projection contains exactly `request_id`, `employee_id`, `status`, `start_date`,
`end_date`, and `request_type`. The HR projection contains the processing fields and full audit
history. Authorization runs before loading a request and before rendering one of these models.

All identifiers use only ASCII letters, digits, `.`, `_`, `:`, and `-`, begin with an
alphanumeric character, and contain at most 100 characters. Idempotency keys use the same
character set and contain 8–200 characters. Payload and output date ranges require
`end_date >= start_date`. Comments and clarification questions collapse whitespace; comments are
optional and at most 500 characters, while questions are non-empty and at most 500 characters.
Confirmation and command fingerprints are exactly 64 lowercase hexadecimal characters.
`request_version` is positive except the create command's expected version zero. Output and audit
timestamps must include a timezone. Unknown JSON fields are rejected, and all contract models are
immutable after validation.

## Identities and access

The server chooses one identity from the versioned synthetic fixture. User text and model output
cannot supply or override `actor_id`, role, reporting line, or request owner. An employee may
access only their own requests. A manager may read only direct-report projections and has no
mutation command. HR may read HR projections and execute only HR commands. Negative fixture
cases cover cross-employee access, a manager accessing a non-report, and an employee attempting
an HR action. The fixture also pins one permission rule per role: request scope, projection, and
the exact allowed command set. Fixture validation fails if it drifts from the executable command
contract. A valid fixture has unique identifiers, at least two employees, at least one manager,
and at least one HR identity; every employee reports to a declared manager, while manager and HR
identities do not declare `reports_to`. All three typed negative-case categories are mandatory.

`enterprise_employee_agent.leave.access_policy` is the only module that decides this (D1):
`resolve_identity` is the sole way to obtain an actor, `can_view`/`visible_requests` decide scope,
`authorize_command`/`authorize_replay`/`authorize_audit_history` gate mutations, replay and audit
reads, and `project_for` builds the typed projection after authorization. Per D3, a command the
actor's role never has at all (manager mutation, an employee HR command) is `forbidden`; a
request that exists but is outside the actor's scope (another employee's request, a non-report's
request) is `not_found`, indistinguishable from a missing request, for view, command, replay, and
audit-history access alike.

## Commands

Every mutation first validates a command-specific client input. Existing-request inputs contain
the command, target request identifier, positive expected current version, idempotency key, and
typed payload where applicable. `create_draft` has expected version zero and no client-supplied
request ID; the application service generates the ID. Client inputs reject `actor_id` and role as
undeclared fields. The service resolves one complete identity object from the validated manifest
and binds it with the input and server-owned target. The resulting command context is an opaque
private type returned only by `bind_server_command`; it cannot be parsed from
request JSON or assembled from independent ID and role claims.

The server computes a canonical fingerprint over actor identity, actor role, command, expected
version, and typed semantic payload. Existing-request fingerprints also include the target.
`create_draft` excludes the newly generated request ID because it is not part of client intent;
an exact retry may allocate a throwaway candidate ID, but the idempotency lookup returns the
original stored result and request ID. A caller-supplied digest is never authoritative.
The idempotency key is scoped to actor and command. The same key plus the same server-computed
fingerprint returns the original authorized result without a second audit event; the same key with
a different target, version, or payload returns `idempotency_conflict`.

| Command | Role | Additional input and effect |
|---|---|---|
| `create_draft` | employee | Validated payload; creates version 1 in `draft` |
| `update_draft` | owner employee | Validated payload; remains `draft`, increments version, invalidates preview |
| `cancel_draft` | owner employee | `draft → cancelled` |
| `confirm_submit` | owner employee | Matching confirmation envelope; `draft → submitted` or `needs_clarification → submitted` |
| `start_processing` | HR | `submitted → processing` |
| `request_clarification` | HR | Operational question; `submitted → needs_clarification` |
| `provide_clarification` | owner employee | Updated payload while `needs_clarification`; increments version and requires a new preview before submit |

Mutation authorization, expected-version validation, idempotency lookup, payload validation, and
transition validation run before a write. The request mutation, idempotency result, and audit
event commit atomically in the later persistence implementation.

## Preview and confirmation

A preview contains the normalized payload, current positive request version, and the lowercase
SHA-256 digest of canonical UTF-8 JSON (`sort_keys`, compact separators). A confirmation envelope
contains `request_id`, `request_version`, and that digest. Matching checks all three values, so a
confirmation cannot be replayed across requests with identical payloads. `confirm_submit` rejects
any changed request, version, or payload as `stale_confirmation`. Editing a draft or providing
clarification always requires a new preview and confirmation.

## State machine

The only v0.1 transitions are:

| Source | Command | Target |
|---|---|---|
| `draft` | `confirm_submit` | `submitted` |
| `draft` | `cancel_draft` | `cancelled` |
| `submitted` | `start_processing` | `processing` |
| `submitted` | `request_clarification` | `needs_clarification` |
| `needs_clarification` | `confirm_submit` | `submitted` |

`cancelled` and `processing` are terminal in v0.1. Manager approval and rejection do not exist.

## Errors

| Code | Meaning |
|---|---|
| `validation_failed` | Input does not satisfy the declared schema |
| `unauthorized` | No valid server-selected identity exists |
| `forbidden` | The actor cannot access the target or command |
| `not_found` | The authorized lookup found no request |
| `version_conflict` | `expected_version` differs from stored version |
| `stale_confirmation` | Confirmation version or digest no longer matches |
| `invalid_transition` | Command is not declared for the current state |
| `idempotency_conflict` | A key was reused with a different normalized command payload |
| `sensitive_content_rejected` | Input contains excluded medical detail or documents |

Errors expose the stable code and a safe message. They do not expose another user's existence,
forbidden fields, raw model output, secrets, or a traceback.

## Audit event

Each successful mutation appends an immutable event with `event_id`, `request_id`, `actor_id`,
command, previous and new status, previous and resulting request version, idempotency key,
server-computed command fingerprint, and timezone-aware server timestamp. Events are built from
the already server-bound command context. Schema validation rejects undeclared state pairs,
non-incrementing versions, a create event other than version 0 → 1, and any non-create event
starting from version zero. The event builder also requires the event's previous version to equal
the command's expected version. The audit record excludes chain-of-thought, medical documents,
diagnoses, provider secrets, and unvalidated raw model output.

## Sensitive free text boundary

`employee_comment` and an HR clarification question are untrusted free text. Keyword deny-lists
are not a security boundary and the Pydantic length/normalization checks do not claim to classify
medical content. Before persistence or logging, the later application layer must pass free text
through a conservative sensitive-content decision that either returns reviewed operational text
or `sensitive_content_rejected`; classifier failure is fail-closed. Raw rejected text is not
stored, logged, copied into audit events, or sent to a model. The v0.1 UI also states that users
must not enter diagnoses or attach medical documents.

## Threat and regression cases

The implementation test plan must include:

- client-supplied `actor_id` or role rejected before server identity binding;
- employee access to another employee and manager access to a non-report denied before lookup;
- manager mutation and employee HR-command attempts denied;
- cross-request confirmation replay, stale version, and changed-payload confirmation denied;
- same idempotency key with a different request, version, or payload rejected, while an exact
  retry returns the original result without another event;
- invalid and undeclared transitions rejected, including manager approval or rejection;
- role projections compared by exact field set, with forbidden fields absent before rendering;
- medical-detail input, Unicode obfuscation, review failure, and sensitive logging handled
  fail-closed.
