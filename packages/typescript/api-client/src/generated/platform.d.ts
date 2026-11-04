/**
 * Auto-generated types for context "platform" — do not edit.
 * Regenerate with `make generate-contracts`.
 */
export interface paths {
    "/api/v1/admin/freeze": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Freeze */
        post: operations["freeze_api_v1_admin_freeze_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/admin/hierarchy": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Get Hierarchy
         * @description The org chart: every member of the workspace and who they report to.
         */
        get: operations["get_hierarchy_api_v1_admin_hierarchy_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/admin/hierarchy/{user_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        /** Set Manager */
        put: operations["set_manager_api_v1_admin_hierarchy__user_id__put"];
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/admin/invitations": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Invite Member
         * @description Create the person (no sign-in yet) and their memberships. No email is
         *     sent: the admin tells the person, who then signs in with that email.
         */
        post: operations["invite_member_api_v1_admin_invitations_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/admin/members": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * List Members
         * @description Everyone in the caller's tenant, by name (Vietnamese collation), with
         *     their roles in each workspace.
         */
        get: operations["list_members_api_v1_admin_members_get"];
        put?: never;
        /** Grant Member */
        post: operations["grant_member_api_v1_admin_members_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/admin/members/{user_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        post?: never;
        /** Revoke Member */
        delete: operations["revoke_member_api_v1_admin_members__user_id__delete"];
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/admin/members/{user_id}/memberships": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        /**
         * Set Memberships
         * @description Replace the person's non-administrative roles, workspace by workspace,
         *     in one transaction. A workspace in the body without a membership gets one;
         *     one left out keeps only its administrative roles, and goes without any.
         *     Answers the person's memberships as they now are (empty: none left).
         */
        put: operations["set_memberships_api_v1_admin_members__user_id__memberships_put"];
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/admin/members/{user_id}/permission-sets": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        /** Set Permission Sets */
        put: operations["set_permission_sets_api_v1_admin_members__user_id__permission_sets_put"];
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/admin/permission-sets": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** List Permission Sets */
        get: operations["list_permission_sets_api_v1_admin_permission_sets_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/admin/permissions": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * List Permissions
         * @description tenant-rbac R1.4: the permission catalogue, by area then key, for a
         *     holder of `platform.roles.read`.
         */
        get: operations["list_permissions_api_v1_admin_permissions_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/admin/roles": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** List Roles */
        get: operations["list_roles_api_v1_admin_roles_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/admin/separation-of-duties": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** List Separation Of Duties */
        get: operations["list_separation_of_duties_api_v1_admin_separation_of_duties_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/admin/separation-of-duties/{rule_key}/waiver": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Waive Separation Of Duties Rule */
        post: operations["waive_separation_of_duties_rule_api_v1_admin_separation_of_duties__rule_key__waiver_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/admin/separation-of-duties/{rule_key}/waiver/confirm": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Confirm Separation Of Duties Waiver */
        post: operations["confirm_separation_of_duties_waiver_api_v1_admin_separation_of_duties__rule_key__waiver_confirm_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/admin/separation-of-duties/{rule_key}/waiver/revoke": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Revoke Separation Of Duties Waiver */
        post: operations["revoke_separation_of_duties_waiver_api_v1_admin_separation_of_duties__rule_key__waiver_revoke_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/admin/service-principals": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** List Service Principals */
        get: operations["list_service_principals_api_v1_admin_service_principals_get"];
        put?: never;
        /** Create Service Principal */
        post: operations["create_service_principal_api_v1_admin_service_principals_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/admin/service-principals/{service_principal_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        /** Update Service Principal */
        patch: operations["update_service_principal_api_v1_admin_service_principals__service_principal_id__patch"];
        trace?: never;
    };
    "/api/v1/admin/tenant": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get Tenant */
        get: operations["get_tenant_api_v1_admin_tenant_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        /** Update Tenant */
        patch: operations["update_tenant_api_v1_admin_tenant_patch"];
        trace?: never;
    };
    "/api/v1/admin/unfreeze": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Unfreeze */
        post: operations["unfreeze_api_v1_admin_unfreeze_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/admin/workspaces": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** List Workspaces */
        get: operations["list_workspaces_api_v1_admin_workspaces_get"];
        put?: never;
        /** Create Workspace */
        post: operations["create_workspace_api_v1_admin_workspaces_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/admin/workspaces/{workspace_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        /** Rename Workspace */
        patch: operations["rename_workspace_api_v1_admin_workspaces__workspace_id__patch"];
        trace?: never;
    };
    "/api/v1/admin/workspaces/{workspace_id}/archive": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Archive Workspace */
        post: operations["archive_workspace_api_v1_admin_workspaces__workspace_id__archive_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/approvals": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** List Pending */
        get: operations["list_pending_api_v1_approvals_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/approvals/{approval_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get Approval */
        get: operations["get_approval_api_v1_approvals__approval_id__get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/approvals/{approval_id}/decisions": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Decide */
        post: operations["decide_api_v1_approvals__approval_id__decisions_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/approvals/{approval_id}/view": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** View Approval */
        post: operations["view_approval_api_v1_approvals__approval_id__view_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/audit/events": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** List Events */
        get: operations["list_events_api_v1_audit_events_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/auth/bootstrap": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Bootstrap */
        get: operations["bootstrap_api_v1_auth_bootstrap_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/connections": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** List Connections */
        get: operations["list_connections_api_v1_connections_get"];
        put?: never;
        /** Create Connection */
        post: operations["create_connection_api_v1_connections_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/connections/{connection_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get Connection */
        get: operations["get_connection_api_v1_connections__connection_id__get"];
        put?: never;
        post?: never;
        /** Delete Connection */
        delete: operations["delete_connection_api_v1_connections__connection_id__delete"];
        options?: never;
        head?: never;
        /** Update Connection */
        patch: operations["update_connection_api_v1_connections__connection_id__patch"];
        trace?: never;
    };
    "/api/v1/connections/{connection_id}/dependents": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Connection Dependents */
        get: operations["connection_dependents_api_v1_connections__connection_id__dependents_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/connections/{connection_id}/disable": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Disable Connection */
        post: operations["disable_connection_api_v1_connections__connection_id__disable_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/connections/{connection_id}/enable": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Enable Connection */
        post: operations["enable_connection_api_v1_connections__connection_id__enable_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/connections/{connection_id}/revoke-credentials": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Revoke Connection Credentials */
        post: operations["revoke_connection_credentials_api_v1_connections__connection_id__revoke_credentials_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/control-state": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Control State */
        get: operations["control_state_api_v1_control_state_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/dev/demo-users": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Demo Users */
        get: operations["demo_users_api_v1_dev_demo_users_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/dev/session": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Create Session */
        post: operations["create_session_api_v1_dev_session_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/digital-workers": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** List Digital Workers */
        get: operations["list_digital_workers_api_v1_digital_workers_get"];
        put?: never;
        /** Create Digital Worker */
        post: operations["create_digital_worker_api_v1_digital_workers_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/digital-workers/{dw_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get Digital Worker */
        get: operations["get_digital_worker_api_v1_digital_workers__dw_id__get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/digital-workers/{dw_id}/decision-classes/{key}/autonomy": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Change Decision Class Autonomy
         * @description Lower at once (R8.1), or open a raise for a second person (R8.2): 202.
         */
        post: operations["change_decision_class_autonomy_api_v1_digital_workers__dw_id__decision_classes__key__autonomy_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/digital-workers/{dw_id}/intake-key": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Read Intake Key */
        get: operations["read_intake_key_api_v1_digital_workers__dw_id__intake_key_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/digital-workers/{dw_id}/people": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        /** Replace Digital Worker People */
        put: operations["replace_digital_worker_people_api_v1_digital_workers__dw_id__people_put"];
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/digital-workers/{dw_id}/scorecard": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get Digital Worker Scorecard */
        get: operations["get_digital_worker_scorecard_api_v1_digital_workers__dw_id__scorecard_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/digital-workers/{dw_id}/state": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Change Digital Worker State */
        post: operations["change_digital_worker_state_api_v1_digital_workers__dw_id__state_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/digital-workers/{dw_id}/work-items": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Give Work */
        post: operations["give_work_api_v1_digital_workers__dw_id__work_items_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/digital-workers/{dw_id}/workflow": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get Digital Worker Workflow */
        get: operations["get_digital_worker_workflow_api_v1_digital_workers__dw_id__workflow_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/digital-workers/{dw_id}/workflow-assistant": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Ask Workflow Assistant
         * @description wf-ai R1: one turn with the assistant; nothing is stored, so no
         *     `Idempotency-Key`. The base is the DW's own pin, never the body (R1.3).
         */
        post: operations["ask_workflow_assistant_api_v1_digital_workers__dw_id__workflow_assistant_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/digital-workers/{dw_id}/workflow-draft": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Get Workflow Draft
         * @description wf-ai R6.1: the DW's draft and its last simulation, for its owners;
         *     404 `draft_not_found` when there is none.
         */
        get: operations["get_workflow_draft_api_v1_digital_workers__dw_id__workflow_draft_get"];
        /**
         * Save Workflow Draft
         * @description wf-ai R6.1, R6.7: 422 `draft_not_publishable` with its problems, and
         *     nothing stored, when the rebuilt document fails a check.
         */
        put: operations["save_workflow_draft_api_v1_digital_workers__dw_id__workflow_draft_put"];
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/digital-workers/{dw_id}/workflow-draft/review": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Review Workflow Draft
         * @description wf-ai R7.2: what a publication's decider reads, for the DW's
         *     Validator, Business Owner or Technical Owner; 403 `not_dw_person` for
         *     anyone else, 404 for a DW the caller may not read or one without a
         *     draft.
         */
        get: operations["review_workflow_draft_api_v1_digital_workers__dw_id__workflow_draft_review_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/digital-workers/{dw_id}/workflow-draft/simulate": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Simulate Workflow Draft
         * @description wf-ai R6.2, R6.9: a dry run of the stored draft; nothing is sent and no
         *     model is called.
         */
        post: operations["simulate_workflow_draft_api_v1_digital_workers__dw_id__workflow_draft_simulate_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/digital-workers/{dw_id}/workflow-draft/submit": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Submit Workflow Draft
         * @description wf-ai R6.3, R6.4, R6.8: opens the `dw.workflow.publish` approval for a
         *     second person; 409 `simulation_required` without a passed simulation of
         *     this content, 409 `draft_submitted` when it already waits.
         */
        post: operations["submit_workflow_draft_api_v1_digital_workers__dw_id__workflow_draft_submit_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/digital-workers/{dw_id}/workflow-draft/withdraw": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Withdraw Workflow Draft
         * @description wf-ai R6.10: cancels the pending approval and returns the draft;
         *     409 `draft_not_submitted`, or `approval_decided` once it was decided.
         */
        post: operations["withdraw_workflow_draft_api_v1_digital_workers__dw_id__workflow_draft_withdraw_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/directory/candidates": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * List Candidates
         * @description Signed-in identities an admin can grant into the workspace — the picker
         *     behind the 'add member' email box, so an already-known account is chosen,
         *     not retyped.
         */
        get: operations["list_candidates_api_v1_directory_candidates_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/directory/members": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** List Members */
        get: operations["list_members_api_v1_directory_members_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/egress/allowed-hosts": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** List Allowed Hosts */
        get: operations["list_allowed_hosts_api_v1_egress_allowed_hosts_get"];
        put?: never;
        /** Request Allowed Host */
        post: operations["request_allowed_host_api_v1_egress_allowed_hosts_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/egress/allowed-hosts/{host_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        post?: never;
        /** Remove Allowed Host */
        delete: operations["remove_allowed_host_api_v1_egress_allowed_hosts__host_id__delete"];
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/feedback": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** List Feedback */
        get: operations["list_feedback_api_v1_feedback_get"];
        put?: never;
        /** Submit Feedback */
        post: operations["submit_feedback_api_v1_feedback_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/feedback/{feedback_id}/attachments/{attachment_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Read Attachment
         * @description The screenshot bytes, for the inbox. Same scope as the inbox itself.
         */
        get: operations["read_attachment_api_v1_feedback__feedback_id__attachments__attachment_id__get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/health": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Health */
        get: operations["health_api_v1_health_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/intake/leads": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Receive Lead */
        post: operations["receive_lead_api_v1_intake_leads_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/integrations": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** List Integrations */
        get: operations["list_integrations_api_v1_integrations_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/knowledge/documents": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** List Documents */
        get: operations["list_documents_api_v1_knowledge_documents_get"];
        put?: never;
        /** Upload Document */
        post: operations["upload_document_api_v1_knowledge_documents_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/knowledge/documents/jobs/{job_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get Ingest Job */
        get: operations["get_ingest_job_api_v1_knowledge_documents_jobs__job_id__get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/knowledge/documents/{document_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        post?: never;
        /** Delete Document */
        delete: operations["delete_document_api_v1_knowledge_documents__document_id__delete"];
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/me": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Me */
        get: operations["me_api_v1_me_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/memory/candidates/{candidate_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get Candidate */
        get: operations["get_candidate_api_v1_memory_candidates__candidate_id__get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/memory/items": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** List Items */
        get: operations["list_items_api_v1_memory_items_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/notifications": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** List Notifications */
        get: operations["list_notifications_api_v1_notifications_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/notifications/read-all": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Mark All Notifications Read */
        post: operations["mark_all_notifications_read_api_v1_notifications_read_all_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/notifications/{notification_id}/read": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Mark Notification Read */
        post: operations["mark_notification_read_api_v1_notifications__notification_id__read_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/platform/freeze": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Freeze Platform
         * @description Every company's runs stop at their next door; 409 `already_frozen`.
         */
        post: operations["freeze_platform_api_v1_platform_freeze_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/platform/operators": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** List Operators */
        get: operations["list_operators_api_v1_platform_operators_get"];
        put?: never;
        /** Add Operator */
        post: operations["add_operator_api_v1_platform_operators_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/platform/operators/{user_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        post?: never;
        /** Remove Operator */
        delete: operations["remove_operator_api_v1_platform_operators__user_id__delete"];
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/platform/support-requests": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * List Support Requests
         * @description Every tenant's grants waiting for assignment (`pending_assignment`), oldest first.
         */
        get: operations["list_support_requests_api_v1_platform_support_requests_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/platform/support-requests/{grant_id}/assign": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Assign Support Request
         * @description 409 `support_staff_required` when the person is not support staff, 409
         *     `support_grant_wrong_status` when the grant is not waiting for assignment.
         *     No conflict-of-interest check yet (ADR 0024).
         */
        post: operations["assign_support_request_api_v1_platform_support_requests__grant_id__assign_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/platform/support-staff": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** List Support Staff */
        get: operations["list_support_staff_api_v1_platform_support_staff_get"];
        put?: never;
        /**
         * Add Support Staff
         * @description By the email of an identity that has signed in; idempotent.
         */
        post: operations["add_support_staff_api_v1_platform_support_staff_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/platform/support-staff/{user_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        post?: never;
        /** Remove Support Staff */
        delete: operations["remove_support_staff_api_v1_platform_support_staff__user_id__delete"];
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/platform/tenants": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** List Tenants */
        get: operations["list_tenants_api_v1_platform_tenants_get"];
        put?: never;
        /** Create Tenant */
        post: operations["create_tenant_api_v1_platform_tenants_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/platform/tenants/{tenant_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        /** Rename Tenant */
        patch: operations["rename_tenant_api_v1_platform_tenants__tenant_id__patch"];
        trace?: never;
    };
    "/api/v1/platform/tenants/{tenant_id}/freeze": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Freeze Tenant
         * @description An operator's freeze of one company, beside any of its own; the company
         *     cannot lift it. 404 for an unknown company, 409 `already_frozen`.
         */
        post: operations["freeze_tenant_api_v1_platform_tenants__tenant_id__freeze_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/platform/tenants/{tenant_id}/lock": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Lock Tenant */
        post: operations["lock_tenant_api_v1_platform_tenants__tenant_id__lock_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/platform/tenants/{tenant_id}/offboard": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get Offboarding Status */
        get: operations["get_offboarding_status_api_v1_platform_tenants__tenant_id__offboard_get"];
        put?: never;
        /**
         * Initiate Offboarding
         * @description Files the request and flips the tenant to `offboarding` immediately.
         *
         *     202, not 200 or 204: the export/purge itself runs later, on the worker's
         *     offboarding lane — this call only starts it.
         */
        post: operations["initiate_offboarding_api_v1_platform_tenants__tenant_id__offboard_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/platform/tenants/{tenant_id}/offboard/finalize": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Finalize Offboarding
         * @description The operator's explicit second step, once GET .../offboard reports
         *     `completed` — see ProvisioningService.finalize_offboarding's docstring
         *     for why this is not automatic.
         */
        post: operations["finalize_offboarding_api_v1_platform_tenants__tenant_id__offboard_finalize_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/platform/tenants/{tenant_id}/org-admins": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Assign Org Admin */
        post: operations["assign_org_admin_api_v1_platform_tenants__tenant_id__org_admins_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/platform/tenants/{tenant_id}/unfreeze": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Unfreeze Tenant
         * @description Lifts the operator's freeze of the company only, never the company's own
         *     (D11); 409 `not_frozen` when no operator's freeze is open.
         */
        post: operations["unfreeze_tenant_api_v1_platform_tenants__tenant_id__unfreeze_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/platform/tenants/{tenant_id}/unlock": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Unlock Tenant */
        post: operations["unlock_tenant_api_v1_platform_tenants__tenant_id__unlock_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/platform/unfreeze": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Unfreeze Platform
         * @description 409 `not_frozen` when no platform freeze is open.
         */
        post: operations["unfreeze_platform_api_v1_platform_unfreeze_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/platform/users": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * List Users
         * @description Every signed-in identity — the picker behind the assign-admin / add-operator
         *     email boxes, so an operator selects an account instead of retyping it.
         */
        get: operations["list_users_api_v1_platform_users_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/public/unsubscribe/{token}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Check Unsubscribe */
        get: operations["check_unsubscribe_api_v1_public_unsubscribe__token__get"];
        put?: never;
        /** Confirm Unsubscribe */
        post: operations["confirm_unsubscribe_api_v1_public_unsubscribe__token__post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/ready": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Ready */
        get: operations["ready_api_v1_ready_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/runs/threads/{thread_id}/cancel": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Cancel Thread
         * @description Stop the run in flight on this thread.
         *
         *     The runner's own `cancel_thread` takes a thread id and nothing else: it
         *     looks the task up in an in-process dict, which is safe while the only caller
         *     is a run that started it. Over HTTP the id is whatever the caller typed, so
         *     ownership is established HERE, against the database under the caller's
         *     tenant, before the runner is asked to do anything.
         *
         *     A thread this tenant has never run on is a 404 rather than a 403. "Not
         *     yours" and "never existed" are the same answer to someone probing ids, and
         *     the difference between them is exactly what a prober is trying to learn.
         */
        post: operations["cancel_thread_api_v1_runs_threads__thread_id__cancel_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/runs/{run_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get Run */
        get: operations["get_run_api_v1_runs__run_id__get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/runs/{run_id}/timeline": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get Timeline */
        get: operations["get_timeline_api_v1_runs__run_id__timeline_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/runs/{run_id}/usage": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Get Run Usage
         * @description The run's usage records summed by operation, model and cost source
         *     (usage-and-limits R3.6). The run is read first, in the caller's workspace,
         *     as `GET /runs/{run_id}` does: another company's run, another workspace's
         *     and one that does not exist are all a 404; a run that has called no model
         *     yet is a 200 with a total of zero.
         */
        get: operations["get_run_usage_api_v1_runs__run_id__usage_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/studio/artifacts": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** List Artifacts */
        get: operations["list_artifacts_api_v1_studio_artifacts_get"];
        put?: never;
        /** Create Artifact */
        post: operations["create_artifact_api_v1_studio_artifacts_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/studio/artifacts/{artifact_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Read Artifact */
        get: operations["read_artifact_api_v1_studio_artifacts__artifact_id__get"];
        put?: never;
        post?: never;
        /** Delete Artifact */
        delete: operations["delete_artifact_api_v1_studio_artifacts__artifact_id__delete"];
        options?: never;
        head?: never;
        /** Update Artifact */
        patch: operations["update_artifact_api_v1_studio_artifacts__artifact_id__patch"];
        trace?: never;
    };
    "/api/v1/studio/artifacts/{artifact_id}/dependents": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** List Dependents */
        get: operations["list_dependents_api_v1_studio_artifacts__artifact_id__dependents_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/studio/artifacts/{artifact_id}/draft": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Read Draft */
        get: operations["read_draft_api_v1_studio_artifacts__artifact_id__draft_get"];
        /** Save Draft */
        put: operations["save_draft_api_v1_studio_artifacts__artifact_id__draft_put"];
        /** Create Draft */
        post: operations["create_draft_api_v1_studio_artifacts__artifact_id__draft_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/studio/artifacts/{artifact_id}/draft/dependencies": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Draft Dependencies */
        get: operations["draft_dependencies_api_v1_studio_artifacts__artifact_id__draft_dependencies_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/studio/artifacts/{artifact_id}/versions": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** List Versions */
        get: operations["list_versions_api_v1_studio_artifacts__artifact_id__versions_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/studio/artifacts/{artifact_id}/versions/{version_no}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Read Version */
        get: operations["read_version_api_v1_studio_artifacts__artifact_id__versions__version_no__get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/support/catalog": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Catalog */
        get: operations["catalog_api_v1_support_catalog_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/support/grants": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * List Grants
         * @description `support.grant`: every grant of this workspace. `support.request` only:
         *     the caller's own requests.
         */
        get: operations["list_grants_api_v1_support_grants_get"];
        put?: never;
        /**
         * Request Grant
         * @description With `support.grant` the grant is made (`pending_assignment`); with only
         *     `support.request` it waits for a granter (`pending_approval`).
         */
        post: operations["request_grant_api_v1_support_grants_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/support/grants/{grant_id}/approve": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Approve Grant */
        post: operations["approve_grant_api_v1_support_grants__grant_id__approve_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/support/grants/{grant_id}/reject": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Reject Grant */
        post: operations["reject_grant_api_v1_support_grants__grant_id__reject_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/support/grants/{grant_id}/revoke": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Revoke Grant
         * @description Takes effect at the staff member's next request.
         */
        post: operations["revoke_grant_api_v1_support_grants__grant_id__revoke_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/support/my-grants": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * My Grants
         * @description The caller's grants, in force or ended in the last 30 days. Support
         *     staff only (403 `support_staff_required`); no tenant header is read.
         */
        get: operations["my_grants_api_v1_support_my_grants_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/usage/summary": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Get Usage Summary
         * @description Totals over `[from, to]`, days cut in the company's time zone (the
         *     current month when neither is given, at most 400 days), grouped by
         *     workspace, agent or workflow, or purpose; never by person in W1 (DO-51.2).
         */
        get: operations["get_usage_summary_api_v1_usage_summary_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/work-items": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** List Work Items */
        get: operations["list_work_items_api_v1_work_items_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/work-items/{item_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get Work Item */
        get: operations["get_work_item_api_v1_work_items__item_id__get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/work-items/{item_id}/complete": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Complete Work Item */
        post: operations["complete_work_item_api_v1_work_items__item_id__complete_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/zalo/connect": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Zalo Connect */
        post: operations["zalo_connect_api_v1_zalo_connect_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/zalo/disconnect": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Zalo Disconnect */
        post: operations["zalo_disconnect_api_v1_zalo_disconnect_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/zalo/status": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Zalo Status */
        get: operations["zalo_status_api_v1_zalo_status_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/zalo/workspace": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Zalo Workspace */
        get: operations["zalo_workspace_api_v1_zalo_workspace_get"];
        /** Zalo Choose Workspace */
        put: operations["zalo_choose_workspace_api_v1_zalo_workspace_put"];
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
}
export type webhooks = Record<string, never>;
export interface components {
    schemas: {
        /** AddOperatorRequest */
        AddOperatorRequest: {
            /** Email */
            email: string;
            /** Note */
            note?: string | null;
        };
        /** AddSupportStaffRequest */
        AddSupportStaffRequest: {
            /** Email */
            email: string;
            /** Note */
            note?: string | null;
        };
        /** AllowedHostRequestBody */
        AllowedHostRequestBody: {
            /** Host Pattern */
            host_pattern: string;
            /** Note */
            note?: string | null;
            /** Ports */
            ports?: number[];
            /**
             * Purpose
             * @enum {string}
             */
            purpose: "http_tool" | "mcp" | "webhook" | "model" | "any";
        };
        /**
         * AllowedHostRequestView
         * @description The approval that will add the host once a second person approves it.
         */
        AllowedHostRequestView: {
            /**
             * Approval Id
             * Format: uuid
             */
            approval_id: string;
            /**
             * Status
             * @default pending
             */
            status: string;
        };
        /** AllowedHostView */
        AllowedHostView: {
            /**
             * Created At
             * Format: date-time
             */
            created_at: string;
            /**
             * Created By
             * Format: uuid
             */
            created_by: string;
            /** Host Pattern */
            host_pattern: string;
            /**
             * Id
             * Format: uuid
             */
            id: string;
            /** Note */
            note: string | null;
            /**
             * Owning Workspace Id
             * Format: uuid
             */
            owning_workspace_id: string;
            /** Ports */
            ports: number[];
            /** Purpose */
            purpose: string;
        };
        /** ApprovalView */
        ApprovalView: {
            /** Approval Type */
            approval_type: string;
            /** Can Decide */
            can_decide: boolean;
            /** Created At */
            created_at: string | null;
            /** Decided At */
            decided_at: string | null;
            /**
             * Id
             * Format: uuid
             */
            id: string;
            /** Payload */
            payload: {
                [key: string]: unknown;
            };
            /** Reason */
            reason: string;
            /** Requested By Me */
            requested_by_me: boolean;
            /** Required Scope */
            required_scope: string | null;
            /** Requires Comment */
            requires_comment: boolean;
            /** Run Id */
            run_id: string | null;
            /** Status */
            status: string;
        };
        /** ApprovalViewOutcome */
        ApprovalViewOutcome: {
            /** Code */
            code: string | null;
            /** Command Approve */
            command_approve: string | null;
            /** Command Reject */
            command_reject: string | null;
            /** Expires At */
            expires_at: string | null;
            /** Requires Comment */
            requires_comment: boolean;
            unavailable_reason: components["schemas"]["CodeUnavailable"] | null;
            /**
             * Viewed At
             * Format: date-time
             */
            viewed_at: string;
        };
        /** ArtifactDraftBody */
        ArtifactDraftBody: {
            /** Document */
            document: {
                [key: string]: unknown;
            };
        };
        /** ArtifactDraftView */
        ArtifactDraftView: {
            /**
             * Artifact Id
             * Format: uuid
             */
            artifact_id: string;
            /** Based On Version Id */
            based_on_version_id: string | null;
            /** Document */
            document: {
                [key: string]: unknown;
            };
            /** Document Schema */
            document_schema: string;
            /**
             * Id
             * Format: uuid
             */
            id: string;
            /**
             * Version
             * @description The draft's ETag; `If-Match` of a save and a submit.
             */
            version: number;
        };
        /** ArtifactView */
        ArtifactView: {
            /** Api Name */
            api_name: string;
            /**
             * Created At
             * Format: date-time
             */
            created_at: string;
            /**
             * Id
             * Format: uuid
             */
            id: string;
            /** Kind */
            kind: string;
            /** Labels */
            labels: string[];
            /** Last Version No */
            last_version_no: number;
            /**
             * Owning Workspace Id
             * Format: uuid
             */
            owning_workspace_id: string;
            /**
             * Updated At
             * Format: date-time
             */
            updated_at: string;
            /**
             * Version
             * @description The artifact's ETag; `If-Match` of its writes.
             */
            version: number;
        };
        /** AssignOrgAdminRequest */
        AssignOrgAdminRequest: {
            /** Email */
            email: string;
        };
        /** AssignSupportRequest */
        AssignSupportRequest: {
            /**
             * Staff User Id
             * Format: uuid
             */
            staff_user_id: string;
        };
        /** AssignedSupportGrantView */
        AssignedSupportGrantView: {
            /**
             * Activated At
             * Format: date-time
             */
            activated_at: string;
            /** Code */
            code: string;
            /**
             * Expires At
             * Format: date-time
             */
            expires_at: string;
            /**
             * Grant Id
             * Format: uuid
             */
            grant_id: string;
            /**
             * Staff User Id
             * Format: uuid
             */
            staff_user_id: string;
            /**
             * Tenant Id
             * Format: uuid
             */
            tenant_id: string;
        };
        /** AssistantAnswerView */
        AssistantAnswerView: {
            /** Diff */
            diff: components["schemas"]["StepChangeView"][];
            /**
             * Kind
             * @enum {string}
             */
            kind: "question" | "proposal";
            /** Outline */
            outline: components["schemas"]["OutlineStepView"][];
            /** Plan */
            plan: string[];
            /** Problems */
            problems: components["schemas"]["WorkflowProblemView"][];
            /** Publishable */
            publishable: boolean;
            /** Question */
            question: string | null;
            /** Steps */
            steps: {
                [key: string]: unknown;
            }[] | null;
        };
        /** AssistantRequest */
        AssistantRequest: {
            /** History */
            history?: components["schemas"]["HistoryTurnBody"][];
            /** Instruction */
            instruction: string;
        };
        /**
         * AuditEventView
         * @description One audit row as the screen shows it.
         *
         *     ``actor_id`` is here because it was the one thing the table could not show:
         *     the column exists on the row and is not inside ``details``, so dropping it
         *     from this view made "who did this" unanswerable from the UI for every action,
         *     not only sharing (spec 03.1 BR10 names it explicitly).
         */
        AuditEventView: {
            /** Action */
            action: string;
            /** Actor Id */
            actor_id: string;
            /** Details */
            details: {
                [key: string]: unknown;
            };
            /**
             * Occurred At
             * Format: date-time
             */
            occurred_at: string;
            /** Policy Decision */
            policy_decision: string | null;
            /** Resource Id */
            resource_id: string;
            /** Resource Type */
            resource_type: string;
            /** Trace Id */
            trace_id: string | null;
        };
        /** AutonomyChangeView */
        AutonomyChangeView: {
            /** Approval Id */
            approval_id: string | null;
            /** Decision Class */
            decision_class: string;
            /**
             * Dw Id
             * Format: uuid
             */
            dw_id: string;
            /** Earned Level */
            earned_level: string;
            /**
             * Outcome
             * @enum {string}
             */
            outcome: "lowered" | "raise_requested";
            /** Requested Level */
            requested_level: string;
        };
        /** AutonomyRequest */
        AutonomyRequest: {
            /** Level */
            level: string;
        };
        /** Body_submit_feedback_api_v1_feedback_post */
        Body_submit_feedback_api_v1_feedback_post: {
            /**
             * Images
             * @default []
             */
            images: string[];
            /** Message */
            message: string;
            /** Module */
            module: string;
            /** Page Path */
            page_path?: string | null;
            /** Suggestion */
            suggestion?: string | null;
        };
        /** Body_upload_document_api_v1_knowledge_documents_post */
        Body_upload_document_api_v1_knowledge_documents_post: {
            /**
             * Classification
             * @default internal
             */
            classification: string;
            /**
             * Domain
             * @default shared
             */
            domain: string;
            /** File */
            file: string;
            /**
             * Scope
             * @default tenant
             */
            scope: string;
            /**
             * Source Version
             * @default 1
             */
            source_version: string;
            /** Title */
            title: string;
        };
        /** BootstrapResponse */
        BootstrapResponse: {
            /** Display Name */
            display_name: string;
            /** Email */
            email: string | null;
            /**
             * Is Platform Operator
             * @default false
             */
            is_platform_operator: boolean;
            /**
             * Is Support Staff
             * @default false
             */
            is_support_staff: boolean;
            /** Memberships */
            memberships: components["schemas"]["WorkspaceMembershipModel"][];
            /**
             * Principal Id
             * Format: uuid
             */
            principal_id: string;
            /** Subject */
            subject: string;
        };
        /**
         * CancelResult
         * @description Whether a run was actually stopped, not whether the request was understood.
         *
         *     `False` is an ordinary answer: the turn had already finished, or another
         *     process holds it. A caller pressing Stop twice should get 200 both times —
         *     the second one describes a thread that is already not running, which is what
         *     they asked for.
         */
        CancelResult: {
            /** Cancelled */
            cancelled: boolean;
        };
        /** ChangeStateRequest */
        ChangeStateRequest: {
            /** State */
            state: string;
        };
        /** ClassStandingView */
        ClassStandingView: {
            /**
             * Effective Level
             * @enum {string}
             */
            effective_level: "A0" | "A1" | "A2" | "A3" | "A4";
            /** Key */
            key: string;
            /**
             * Mode
             * @enum {string}
             */
            mode: "auto" | "ask" | "blocked";
        };
        /**
         * CodeUnavailable
         * @description Why the portal offers no code. Each one is a sentence on the page.
         * @enum {string}
         */
        CodeUnavailable: "not_pending" | "cannot_decide" | "requester" | "web_only" | "not_linked" | "comment_required" | "channel_off";
        /** ConnectionDependentView */
        ConnectionDependentView: {
            /**
             * Id
             * Format: uuid
             */
            id: string;
            /** Kind */
            kind: string;
            /** Name */
            name: string;
        };
        /**
         * ConnectionDependentsView
         * @description `total` counts every dependent; `visible` those the caller may read.
         */
        ConnectionDependentsView: {
            /** Total */
            total: number;
            /** Visible */
            visible: components["schemas"]["ConnectionDependentView"][];
        };
        /** ConnectionDetailView */
        ConnectionDetailView: {
            /** Compromised At */
            compromised_at: string | null;
            /** Connector Key */
            connector_key: string;
            /** Connector Major */
            connector_major: number;
            /**
             * Created At
             * Format: date-time
             */
            created_at: string;
            /** Created By */
            created_by: string | null;
            /** Disabled At */
            disabled_at: string | null;
            /** External Account */
            external_account: string | null;
            /**
             * Id
             * Format: uuid
             */
            id: string;
            /** Last Used At */
            last_used_at: string | null;
            /** Name */
            name: string;
            /**
             * Owning Workspace Id
             * Format: uuid
             */
            owning_workspace_id: string;
            /** Pending Enable Approval Id */
            pending_enable_approval_id: string | null;
            /** Scopes */
            scopes: string[];
            /** Secret Fields */
            secret_fields: components["schemas"]["SecretFieldView"][];
            /** Share Scope */
            share_scope: string;
            /** Status */
            status: string;
            /**
             * Updated At
             * Format: date-time
             */
            updated_at: string;
        };
        /**
         * ConnectionPatchBody
         * @description The name and a rotation; the status, scope, connector and account never
         *     change here (the account is the connection's identity: delete and create).
         */
        ConnectionPatchBody: {
            /** Name */
            name?: string | null;
            /** Secrets */
            secrets?: {
                [key: string]: string;
            };
        };
        /** ConnectionView */
        ConnectionView: {
            /** Compromised At */
            compromised_at: string | null;
            /** Connector Key */
            connector_key: string;
            /** Connector Major */
            connector_major: number;
            /**
             * Created At
             * Format: date-time
             */
            created_at: string;
            /** Created By */
            created_by: string | null;
            /** Disabled At */
            disabled_at: string | null;
            /** External Account */
            external_account: string | null;
            /**
             * Id
             * Format: uuid
             */
            id: string;
            /** Last Used At */
            last_used_at: string | null;
            /** Name */
            name: string;
            /**
             * Owning Workspace Id
             * Format: uuid
             */
            owning_workspace_id: string;
            /** Scopes */
            scopes: string[];
            /** Share Scope */
            share_scope: string;
            /** Status */
            status: string;
            /**
             * Updated At
             * Format: date-time
             */
            updated_at: string;
        };
        /** ControlStateView */
        ControlStateView: {
            /** Freezes */
            freezes: components["schemas"]["OpenFreezeView"][];
            platform_freeze: components["schemas"]["OpenFreezeView"] | null;
            /**
             * State
             * @enum {string}
             */
            state: "open" | "platform_frozen" | "tenant_frozen";
        };
        /**
         * CreateDigitalWorkerRequest
         * @description Unknown fields are ignored, not refused: a `tenant_id` or `workspace_id`
         *     in the body changes nothing, both come from the access context (R1.1).
         */
        CreateDigitalWorkerRequest: {
            /** Allowed Tools */
            allowed_tools?: string[];
            /** Decision Classes */
            decision_classes?: components["schemas"]["DecisionClassBody"][];
            /** Key */
            key: string;
            /** Mandate */
            mandate: string;
            /** Name */
            name: string;
            /** Parameters */
            parameters?: {
                [key: string]: unknown;
            };
            people: components["schemas"]["PeopleBody"];
            /** Role Keys */
            role_keys: string[];
            /** Work Kinds */
            work_kinds: string[];
            /** Workflow Key */
            workflow_key: string;
            /** Workflow Version */
            workflow_version: string;
        };
        /**
         * CreateServicePrincipalBody
         * @description The tenant is never the body's: it is the access context's.
         */
        CreateServicePrincipalBody: {
            /** Description */
            description?: string | null;
            /** Name */
            name: string;
            /**
             * Owner User Id
             * Format: uuid
             */
            owner_user_id: string;
            /**
             * Owning Workspace Id
             * Format: uuid
             */
            owning_workspace_id: string;
        };
        /** CreateTenantRequest */
        CreateTenantRequest: {
            /** Name */
            name: string;
            /** Owners */
            owners: string[];
            /** Plan Id */
            plan_id: string;
            /** Slug */
            slug: string;
        };
        /** CreateWorkspaceBody */
        CreateWorkspaceBody: {
            /** Name */
            name: string;
            /** Slug */
            slug: string;
        };
        /** DecisionClassBody */
        DecisionClassBody: {
            /** Ceiling */
            ceiling: string;
            /** Earned Level */
            earned_level: string;
            /** Effect Level */
            effect_level: string;
            /** Key */
            key: string;
            /** Reversible */
            reversible: boolean;
        };
        /** DecisionClassView */
        DecisionClassView: {
            /** Ceiling */
            ceiling: string;
            /** Earned Level */
            earned_level: string;
            /** Effect Level */
            effect_level: string;
            /** Key */
            key: string;
            /** Reversible */
            reversible: boolean;
        };
        /** DecisionRequest */
        DecisionRequest: {
            /** Approve */
            approve: boolean;
            /** Approved Action Ids */
            approved_action_ids?: string[] | null;
            /**
             * Comment
             * @default
             */
            comment: string;
            /** Edited Proposal */
            edited_proposal?: {
                [key: string]: unknown;
            } | null;
        };
        /** DemoUser */
        DemoUser: {
            /** Description */
            description: string;
            /** Display Name */
            display_name: string;
            /** Roles */
            roles: string[];
            /** Subject */
            subject: string;
            /**
             * Tenant Id
             * Format: uuid
             */
            tenant_id: string;
            /** Tenant Name */
            tenant_name: string;
            /**
             * Workspace Id
             * Format: uuid
             */
            workspace_id: string;
        };
        /** DependentGroupView */
        DependentGroupView: {
            /**
             * Hidden
             * @description Dependents the caller may not read, counted only.
             */
            hidden: number;
            /** Items */
            items: components["schemas"]["DependentView"][];
        };
        /** DependentView */
        DependentView: {
            /** Api Name */
            api_name: string;
            /**
             * Artifact Id
             * Format: uuid
             */
            artifact_id: string;
            /** Kind */
            kind: string;
        };
        /** DependentsView */
        DependentsView: {
            candidate: components["schemas"]["DependentGroupView"];
            live: components["schemas"]["DependentGroupView"];
        };
        /** DevSessionRequest */
        DevSessionRequest: {
            /** Subject */
            subject: string;
        };
        /** DevSessionResponse */
        DevSessionResponse: {
            /** Display Name */
            display_name: string;
            /**
             * Expires At
             * Format: date-time
             */
            expires_at: string;
            /** Roles */
            roles: string[];
            /** Subject */
            subject: string;
            /**
             * Tenant Id
             * Format: uuid
             */
            tenant_id: string;
            /** Tenant Name */
            tenant_name: string;
            /** Token */
            token: string;
            /**
             * Workspace Id
             * Format: uuid
             */
            workspace_id: string;
        };
        /** DigitalWorkerListItemView */
        DigitalWorkerListItemView: {
            /** Allowed Tools */
            allowed_tools: string[];
            /**
             * Created At
             * Format: date-time
             */
            created_at: string;
            /**
             * Created By
             * Format: uuid
             */
            created_by: string;
            /** Decision Classes */
            decision_classes: components["schemas"]["DecisionClassView"][];
            /**
             * Id
             * Format: uuid
             */
            id: string;
            /** Key */
            key: string;
            /** Mandate */
            mandate: string;
            /** Name */
            name: string;
            /** Open Items */
            open_items: number;
            /** Parameters */
            parameters: {
                [key: string]: unknown;
            };
            people: components["schemas"]["PeopleView"];
            /**
             * Principal User Id
             * Format: uuid
             */
            principal_user_id: string;
            /** Role Keys */
            role_keys: string[];
            /** State */
            state: string;
            /**
             * Updated At
             * Format: date-time
             */
            updated_at: string;
            /** Work Kinds */
            work_kinds: string[];
            /** Workflow Key */
            workflow_key: string;
            /** Workflow Version */
            workflow_version: string;
        };
        /** DigitalWorkerView */
        DigitalWorkerView: {
            /** Allowed Tools */
            allowed_tools: string[];
            /**
             * Created At
             * Format: date-time
             */
            created_at: string;
            /**
             * Created By
             * Format: uuid
             */
            created_by: string;
            /** Decision Classes */
            decision_classes: components["schemas"]["DecisionClassView"][];
            /**
             * Id
             * Format: uuid
             */
            id: string;
            /** Key */
            key: string;
            /** Mandate */
            mandate: string;
            /** Name */
            name: string;
            /** Parameters */
            parameters: {
                [key: string]: unknown;
            };
            people: components["schemas"]["PeopleView"];
            /**
             * Principal User Id
             * Format: uuid
             */
            principal_user_id: string;
            /** Role Keys */
            role_keys: string[];
            /** State */
            state: string;
            /**
             * Updated At
             * Format: date-time
             */
            updated_at: string;
            /** Work Kinds */
            work_kinds: string[];
            /** Workflow Key */
            workflow_key: string;
            /** Workflow Version */
            workflow_version: string;
        };
        /** DraftBody */
        DraftBody: {
            /** Steps */
            steps: {
                [key: string]: unknown;
            }[];
        };
        /** DraftReviewView */
        DraftReviewView: {
            /** Approval Id */
            approval_id: string | null;
            /** Author Ids */
            author_ids: string[];
            /** Base Current */
            base_current: boolean;
            /** Base Sha256 */
            base_sha256: string;
            /** Content Sha256 */
            content_sha256: string;
            /** Diff */
            diff: components["schemas"]["StepChangeView"][];
            /**
             * Dw Id
             * Format: uuid
             */
            dw_id: string;
            /** Outline */
            outline: components["schemas"]["OutlineStepView"][];
            simulation: components["schemas"]["SimulationView"] | null;
            /**
             * State
             * @enum {string}
             */
            state: "draft" | "submitted";
        };
        /** DraftView */
        DraftView: {
            /** Approval Id */
            approval_id: string | null;
            /** Author Ids */
            author_ids: string[];
            /** Base Sha256 */
            base_sha256: string;
            /** Content */
            content: {
                [key: string]: unknown;
            };
            /** Content Sha256 */
            content_sha256: string;
            /**
             * Dw Id
             * Format: uuid
             */
            dw_id: string;
            /** Reason */
            reason: string | null;
            /**
             * Saved By
             * Format: uuid
             */
            saved_by: string;
            simulation: components["schemas"]["SimulationView"] | null;
            /**
             * State
             * @enum {string}
             */
            state: "draft" | "submitted";
            /**
             * Updated At
             * Format: date-time
             */
            updated_at: string;
        };
        /**
         * EnableRequestView
         * @description The approval that enables the connection once a second person approves it.
         */
        EnableRequestView: {
            /**
             * Approval Id
             * Format: uuid
             */
            approval_id: string;
            /**
             * Status
             * @default pending
             */
            status: string;
        };
        /** FeedbackAttachmentView */
        FeedbackAttachmentView: {
            /** Content Type */
            content_type: string;
            /** Id */
            id: string;
            /** Size Bytes */
            size_bytes: number;
        };
        /** FeedbackView */
        FeedbackView: {
            /**
             * Attachments
             * @default []
             */
            attachments: components["schemas"]["FeedbackAttachmentView"][];
            /** Author Name */
            author_name: string;
            /** Category */
            category: string;
            /**
             * Created At
             * Format: date-time
             */
            created_at: string;
            /** Id */
            id: string;
            /** Message */
            message: string;
            /** Module */
            module?: string | null;
            /** Page Path */
            page_path?: string | null;
            /** Suggestion */
            suggestion?: string | null;
        };
        /** FreezeBody */
        FreezeBody: {
            /** Reason */
            reason: string;
            /**
             * Reason Code
             * @enum {string}
             */
            reason_code: "incident" | "maintenance" | "abuse" | "test" | "other";
        };
        /** FreezeView */
        FreezeView: {
            /**
             * Switch Id
             * Format: uuid
             */
            switch_id: string;
        };
        /** GrantMemberRequest */
        GrantMemberRequest: {
            /**
             * Department
             * @default general
             */
            department: string;
            /** Email */
            email: string;
            /** Role Keys */
            role_keys: string[];
            /**
             * Workspace Id
             * Format: uuid
             */
            workspace_id: string;
        };
        /** GrantView */
        GrantView: {
            /**
             * Anchor Workspace Id
             * Format: uuid
             */
            anchor_workspace_id: string;
            /** Depth */
            depth: string;
            /** Key */
            key: string;
        };
        /** HandoffView */
        HandoffView: {
            /** Context */
            context: string;
            /** Problem */
            problem: string;
            /** Recommendation */
            recommendation: string;
            /** Tried */
            tried: string;
        };
        /** HealthResponse */
        HealthResponse: {
            /** Api Version */
            api_version: string;
            /** Status */
            status: string;
            /** Version */
            version: string;
        };
        /** HierarchyMemberView */
        HierarchyMemberView: {
            /** Display Name */
            display_name: string;
            /** Email */
            email: string | null;
            /** Manager User Id */
            manager_user_id: string | null;
            /** Role Keys */
            role_keys: string[];
            /**
             * User Id
             * Format: uuid
             */
            user_id: string;
        };
        /** HistoryTurnBody */
        HistoryTurnBody: {
            /**
             * Role
             * @enum {string}
             */
            role: "user" | "assistant";
            /** Text */
            text: string;
        };
        /** IdentityRefView */
        IdentityRefView: {
            /** Display Name */
            display_name: string;
            /** Email */
            email: string | null;
            /**
             * User Id
             * Format: uuid
             */
            user_id: string;
        };
        /** InboxView */
        InboxView: {
            /** Items */
            items: components["schemas"]["NotificationView"][];
            /** Unread */
            unread: number;
        };
        /** IngestJobView */
        IngestJobView: {
            /** Attempts */
            attempts: number;
            /** Chunk Count */
            chunk_count: number | null;
            /**
             * Created At
             * Format: date-time
             */
            created_at: string;
            /** Document Id */
            document_id: string | null;
            /** Error */
            error: string | null;
            /** Filename */
            filename: string;
            /**
             * Job Id
             * Format: uuid
             */
            job_id: string;
            /** Scope */
            scope: string;
            /** Status */
            status: string;
            /** Title */
            title: string;
            /**
             * Updated At
             * Format: date-time
             */
            updated_at: string;
            /**
             * Warnings
             * @default []
             */
            warnings: string[];
        };
        /** IntakeKey */
        IntakeKey: {
            /** Key */
            key: string;
        };
        /** IntegrationView */
        IntegrationView: {
            /** Approval Policy */
            approval_policy: string;
            /** Description */
            description: string;
            /** Idempotent */
            idempotent: boolean;
            /** Required Scopes */
            required_scopes: string[];
            /**
             * Requires Approval
             * @description True if this tool always requires approval, at every autonomy level. False does not mean it never pauses: whether a given call does depends on the run.
             */
            requires_approval: boolean;
            /** Side Effect Level */
            side_effect_level: string;
            /** Timeout Seconds */
            timeout_seconds: number;
            /** Tool */
            tool: string;
            /** Version */
            version: string;
        };
        /** InviteMemberRequest */
        InviteMemberRequest: {
            /** Display Name */
            display_name: string;
            /** Email */
            email: string;
            /** Memberships */
            memberships: components["schemas"]["WorkspaceRolesBody"][];
        };
        /** KnowledgeDocumentView */
        KnowledgeDocumentView: {
            /** Chunk Count */
            chunk_count: number;
            /** Classification */
            classification: string;
            /**
             * Created At
             * Format: date-time
             */
            created_at: string;
            /**
             * Document Id
             * Format: uuid
             */
            document_id: string;
            /** Domain */
            domain: string;
            /** Index Version */
            index_version: string | null;
            /** Scope */
            scope: string;
            /** Source Version */
            source_version: string;
            /** Title */
            title: string;
        };
        /** MeResponse */
        MeResponse: {
            /** Access Version */
            access_version: number | null;
            /** Clearance */
            clearance: string;
            /** Feature Flags */
            feature_flags: string[];
            /** Grants */
            grants: components["schemas"]["GrantView"][];
            /** Plan Id */
            plan_id: string;
            /** Platform Bypass */
            platform_bypass: boolean;
            /**
             * Principal Id
             * Format: uuid
             */
            principal_id: string;
            /** Roles */
            roles: string[];
            /** Scopes */
            scopes: string[];
            /**
             * Tenant Id
             * Format: uuid
             */
            tenant_id: string;
            /**
             * Workspace Id
             * Format: uuid
             */
            workspace_id: string;
        };
        /**
         * MemberMembershipsView
         * @description A person's memberships in this tenant after a change; empty when none is left.
         */
        MemberMembershipsView: {
            /** Memberships */
            memberships: components["schemas"]["MemberWorkspaceView"][];
            /**
             * User Id
             * Format: uuid
             */
            user_id: string;
        };
        /** MemberRefView */
        MemberRefView: {
            /** Display Name */
            display_name: string;
            /** Email */
            email: string | null;
            /**
             * User Id
             * Format: uuid
             */
            user_id: string;
        };
        /** MemberWorkspaceView */
        MemberWorkspaceView: {
            /** Role Keys */
            role_keys: string[];
            /**
             * Workspace Id
             * Format: uuid
             */
            workspace_id: string;
            /** Workspace Name */
            workspace_name: string;
        };
        /** MemoryCandidateView */
        MemoryCandidateView: {
            /**
             * Candidate Id
             * Format: uuid
             */
            candidate_id: string;
            /** Classification */
            classification: string;
            /** Confidence */
            confidence: number;
            /** Content */
            content: string;
            /**
             * Created At
             * Format: date-time
             */
            created_at: string;
            /**
             * Created By Run Id
             * Format: uuid
             */
            created_by_run_id: string;
            /** Decision */
            decision: string;
            /** Fact Key */
            fact_key: string | null;
            /** Memory Id */
            memory_id: string | null;
            /** Memory Type */
            memory_type: string;
            /** Provenance Refs */
            provenance_refs: {
                [key: string]: unknown;
            }[];
            /** Structured Facts */
            structured_facts: {
                [key: string]: unknown;
            };
            /** Subject Refs */
            subject_refs: string[];
            /** Worker Id */
            worker_id: string;
        };
        /** MemoryItemView */
        MemoryItemView: {
            /** Classification */
            classification: string;
            /** Confidence */
            confidence: number;
            /** Content */
            content: string;
            /**
             * Created By Run Id
             * Format: uuid
             */
            created_by_run_id: string;
            /**
             * Memory Id
             * Format: uuid
             */
            memory_id: string;
            /** Memory Type */
            memory_type: string;
            /** Provenance Count */
            provenance_count: number;
            /**
             * Valid From
             * Format: date-time
             */
            valid_from: string;
            /** Worker Id */
            worker_id: string;
        };
        /**
         * MySupportGrantModel
         * @description A grant assigned to the caller: enough to open it, nothing the customer
         *     wrote (no reason).
         */
        MySupportGrantModel: {
            /** Activated At */
            activated_at: string | null;
            /** Code */
            code: string;
            /** Expires At */
            expires_at: string | null;
            /**
             * Id
             * Format: uuid
             */
            id: string;
            /** Resource Id */
            resource_id: string | null;
            /** Resource Label */
            resource_label: string;
            /** Resource Type */
            resource_type: string;
            /** Revoked At */
            revoked_at: string | null;
            /** Scope Set Key */
            scope_set_key: string;
            /** Scope Set Label */
            scope_set_label: string;
            /** State */
            state: string;
            /**
             * Tenant Id
             * Format: uuid
             */
            tenant_id: string;
            /** Tenant Name */
            tenant_name: string;
            /**
             * Workspace Id
             * Format: uuid
             */
            workspace_id: string;
            /** Workspace Name */
            workspace_name: string;
        };
        /** NewArtifact */
        NewArtifact: {
            /** Api Name */
            api_name: string;
            /**
             * Document
             * @default {}
             */
            document: {
                [key: string]: unknown;
            };
            /** Kind */
            kind: string;
            /**
             * Labels
             * @default []
             */
            labels: string[];
        };
        /** NewConnectionBody */
        NewConnectionBody: {
            /** Connector Key */
            connector_key: string;
            /** Connector Major */
            connector_major: number;
            /** External Account */
            external_account: string;
            /** Name */
            name: string;
            /** Secrets */
            secrets?: {
                [key: string]: string;
            };
            /**
             * Share Scope
             * @default workspace
             * @constant
             */
            share_scope: "workspace";
        };
        /** NewTenantView */
        NewTenantView: {
            /** Name */
            name: string;
            /** Slug */
            slug: string;
            /** Status */
            status: string;
            /**
             * Tenant Id
             * Format: uuid
             */
            tenant_id: string;
            /**
             * Workspace Id
             * Format: uuid
             */
            workspace_id: string;
        };
        /** NewWorkRequest */
        NewWorkRequest: {
            /** Kind */
            kind: string;
            /** Payload */
            payload: {
                [key: string]: unknown;
            };
            /** Source Key */
            source_key: string;
        };
        /** NotificationView */
        NotificationView: {
            /** Body */
            body: string;
            /**
             * Created At
             * Format: date-time
             */
            created_at: string;
            /**
             * Id
             * Format: uuid
             */
            id: string;
            /** Link */
            link: string | null;
            /** Read At */
            read_at: string | null;
            /** Title */
            title: string;
        };
        /** OffboardingStatusView */
        OffboardingStatusView: {
            /** Error */
            error: string | null;
            /** Export Key */
            export_key: string | null;
            /**
             * Request Id
             * Format: uuid
             */
            request_id: string;
            /**
             * Requested At
             * Format: date-time
             */
            requested_at: string;
            /**
             * Requested By
             * Format: uuid
             */
            requested_by: string;
            /** Status */
            status: string;
            /**
             * Tenant Id
             * Format: uuid
             */
            tenant_id: string;
            /**
             * Updated At
             * Format: date-time
             */
            updated_at: string;
        };
        /** OpenFreezeView */
        OpenFreezeView: {
            /**
             * Origin
             * @enum {string}
             */
            origin: "tenant" | "platform";
            /** Reason Code */
            reason_code: string;
            /**
             * Set At
             * Format: date-time
             */
            set_at: string;
        };
        /** OperatorView */
        OperatorView: {
            /**
             * Created At
             * Format: date-time
             */
            created_at: string;
            /** Display Name */
            display_name: string;
            /** Email */
            email: string | null;
            /** Note */
            note: string | null;
            /**
             * User Id
             * Format: uuid
             */
            user_id: string;
        };
        /** OutlineLaneView */
        OutlineLaneView: {
            /** Port */
            port: string;
            /** Steps */
            steps: components["schemas"]["OutlineStepView"][];
        };
        /** OutlineStepView */
        OutlineStepView: {
            /** Decision Class */
            decision_class: string | null;
            /** Description */
            description: string | null;
            /** Id */
            id: string;
            /** Lanes */
            lanes: components["schemas"]["OutlineLaneView"][];
            /** Tool */
            tool: string | null;
            /** Type */
            type: string;
        };
        /**
         * Page
         * @description A page of results and the cursor that continues it.
         *
         *     ``next_cursor`` is ``None`` on the last page, and that — not an empty
         *     ``items`` — is the client's stop condition: a filtered listing can return an
         *     empty page in the middle of a run and still have more rows behind it.
         */
        Page_AllowedHostView_: {
            /** Items */
            items: components["schemas"]["AllowedHostView"][];
            /** Next Cursor */
            next_cursor: string | null;
        };
        /**
         * Page
         * @description A page of results and the cursor that continues it.
         *
         *     ``next_cursor`` is ``None`` on the last page, and that — not an empty
         *     ``items`` — is the client's stop condition: a filtered listing can return an
         *     empty page in the middle of a run and still have more rows behind it.
         */
        Page_ApprovalView_: {
            /** Items */
            items: components["schemas"]["ApprovalView"][];
            /** Next Cursor */
            next_cursor: string | null;
        };
        /**
         * Page
         * @description A page of results and the cursor that continues it.
         *
         *     ``next_cursor`` is ``None`` on the last page, and that — not an empty
         *     ``items`` — is the client's stop condition: a filtered listing can return an
         *     empty page in the middle of a run and still have more rows behind it.
         */
        Page_ArtifactView_: {
            /** Items */
            items: components["schemas"]["ArtifactView"][];
            /** Next Cursor */
            next_cursor: string | null;
        };
        /**
         * Page
         * @description A page of results and the cursor that continues it.
         *
         *     ``next_cursor`` is ``None`` on the last page, and that — not an empty
         *     ``items`` — is the client's stop condition: a filtered listing can return an
         *     empty page in the middle of a run and still have more rows behind it.
         */
        Page_AuditEventView_: {
            /** Items */
            items: components["schemas"]["AuditEventView"][];
            /** Next Cursor */
            next_cursor: string | null;
        };
        /**
         * Page
         * @description A page of results and the cursor that continues it.
         *
         *     ``next_cursor`` is ``None`` on the last page, and that — not an empty
         *     ``items`` — is the client's stop condition: a filtered listing can return an
         *     empty page in the middle of a run and still have more rows behind it.
         */
        Page_ConnectionView_: {
            /** Items */
            items: components["schemas"]["ConnectionView"][];
            /** Next Cursor */
            next_cursor: string | null;
        };
        /**
         * Page
         * @description A page of results and the cursor that continues it.
         *
         *     ``next_cursor`` is ``None`` on the last page, and that — not an empty
         *     ``items`` — is the client's stop condition: a filtered listing can return an
         *     empty page in the middle of a run and still have more rows behind it.
         */
        Page_DigitalWorkerListItemView_: {
            /** Items */
            items: components["schemas"]["DigitalWorkerListItemView"][];
            /** Next Cursor */
            next_cursor: string | null;
        };
        /**
         * Page
         * @description A page of results and the cursor that continues it.
         *
         *     ``next_cursor`` is ``None`` on the last page, and that — not an empty
         *     ``items`` — is the client's stop condition: a filtered listing can return an
         *     empty page in the middle of a run and still have more rows behind it.
         */
        Page_FeedbackView_: {
            /** Items */
            items: components["schemas"]["FeedbackView"][];
            /** Next Cursor */
            next_cursor: string | null;
        };
        /**
         * Page
         * @description A page of results and the cursor that continues it.
         *
         *     ``next_cursor`` is ``None`` on the last page, and that — not an empty
         *     ``items`` — is the client's stop condition: a filtered listing can return an
         *     empty page in the middle of a run and still have more rows behind it.
         */
        Page_KnowledgeDocumentView_: {
            /** Items */
            items: components["schemas"]["KnowledgeDocumentView"][];
            /** Next Cursor */
            next_cursor: string | null;
        };
        /**
         * Page
         * @description A page of results and the cursor that continues it.
         *
         *     ``next_cursor`` is ``None`` on the last page, and that — not an empty
         *     ``items`` — is the client's stop condition: a filtered listing can return an
         *     empty page in the middle of a run and still have more rows behind it.
         */
        Page_MemoryItemView_: {
            /** Items */
            items: components["schemas"]["MemoryItemView"][];
            /** Next Cursor */
            next_cursor: string | null;
        };
        /**
         * Page
         * @description A page of results and the cursor that continues it.
         *
         *     ``next_cursor`` is ``None`` on the last page, and that — not an empty
         *     ``items`` — is the client's stop condition: a filtered listing can return an
         *     empty page in the middle of a run and still have more rows behind it.
         */
        Page_ServicePrincipalView_: {
            /** Items */
            items: components["schemas"]["ServicePrincipalView"][];
            /** Next Cursor */
            next_cursor: string | null;
        };
        /**
         * Page
         * @description A page of results and the cursor that continues it.
         *
         *     ``next_cursor`` is ``None`` on the last page, and that — not an empty
         *     ``items`` — is the client's stop condition: a filtered listing can return an
         *     empty page in the middle of a run and still have more rows behind it.
         */
        Page_WorkItemView_: {
            /** Items */
            items: components["schemas"]["WorkItemView"][];
            /** Next Cursor */
            next_cursor: string | null;
        };
        /** PeopleBody */
        PeopleBody: {
            /**
             * Business Owner Id
             * Format: uuid
             */
            business_owner_id: string;
            /**
             * Technical Owner Id
             * Format: uuid
             */
            technical_owner_id: string;
            /**
             * Validator Id
             * Format: uuid
             */
            validator_id: string;
            /**
             * Work Assigner Id
             * Format: uuid
             */
            work_assigner_id: string;
        };
        /** PeopleView */
        PeopleView: {
            /** Business Owner Id */
            business_owner_id: string | null;
            /**
             * Technical Owner Id
             * Format: uuid
             */
            technical_owner_id: string;
            /**
             * Validator Id
             * Format: uuid
             */
            validator_id: string;
            /**
             * Work Assigner Id
             * Format: uuid
             */
            work_assigner_id: string;
        };
        /** PermissionSetView */
        PermissionSetView: {
            /** Key */
            key: string;
            /** Name */
            name: string;
            /** Scopes */
            scopes: string[];
        };
        /** PermissionView */
        PermissionView: {
            /** Area */
            area: string;
            /** Key */
            key: string;
            /** Label Vi */
            label_vi: string;
            /**
             * Risk
             * @enum {string}
             */
            risk: "standard" | "elevated" | "critical";
            /**
             * Scope Kind
             * @enum {string}
             */
            scope_kind: "tenant" | "workspace" | "record";
            /**
             * Status
             * @enum {string}
             */
            status: "active" | "unassigned" | "retired";
        };
        /** PlatformFreezeRequest */
        PlatformFreezeRequest: {
            /** Reason */
            reason: string;
            /**
             * Reason Code
             * @enum {string}
             */
            reason_code: "incident" | "maintenance" | "abuse" | "test" | "other";
        };
        /** PlatformFreezeView */
        PlatformFreezeView: {
            /**
             * Id
             * Format: uuid
             */
            id: string;
        };
        /** PlatformUnfreezeRequest */
        PlatformUnfreezeRequest: {
            /** Reason */
            reason?: string | null;
        };
        /**
         * Problem
         * @description The single error description returned by every endpoint.
         */
        Problem: {
            /** Code */
            code: string;
            /** Detail */
            detail: string;
            /**
             * Details
             * @default {}
             */
            details: {
                [key: string]: unknown;
            };
            /**
             * Errors
             * @default []
             */
            errors: components["schemas"]["ProblemError"][];
            /** Instance */
            instance: string | null;
            /** Message */
            message: string;
            /** Request Id */
            request_id?: string | null;
            /** Status */
            status: number;
            /** Title */
            title: string;
            /** Trace Id */
            trace_id?: string | null;
            /** Type */
            type: string;
        };
        /**
         * ProblemError
         * @description One thing wrong with the request, located in exactly one place.
         */
        ProblemError: {
            /** Code */
            code: string;
            /** Detail */
            detail: string;
            /** Header */
            header?: string | null;
            /** Parameter */
            parameter?: string | null;
            /** Pointer */
            pointer?: string | null;
        };
        /** ReadinessResponse */
        ReadinessResponse: {
            /** Checks */
            checks: {
                [key: string]: string;
            };
            /** Status */
            status: string;
        };
        /** Received */
        Received: {
            /**
             * Id
             * Format: uuid
             */
            id: string;
        };
        /** ReferenceList */
        ReferenceList: {
            /** Items */
            items: components["schemas"]["ReferenceView"][];
        };
        /** ReferenceView */
        ReferenceView: {
            /** Path */
            path: string;
            /** To Key */
            to_key: string;
            /** To Kind */
            to_kind: string;
            /** Usage */
            usage: string;
        };
        /** RejectSupportGrantBody */
        RejectSupportGrantBody: {
            /** Reason */
            reason: string;
        };
        /** RenameTenantRequest */
        RenameTenantRequest: {
            /** Name */
            name: string;
        };
        /** RenameWorkspaceBody */
        RenameWorkspaceBody: {
            /** Name */
            name: string;
        };
        /** RequestSupportGrantBody */
        RequestSupportGrantBody: {
            /** Duration Hours */
            duration_hours: number;
            /** Reason */
            reason: string;
            /** Resource Id */
            resource_id?: string | null;
            /** Resource Type */
            resource_type: string;
            /** Scope Set Key */
            scope_set_key: string;
        };
        /** RoleView */
        RoleView: {
            /** Key */
            key: string;
            /** Name */
            name: string;
            /** Scopes */
            scopes: string[];
        };
        /** RunUsageRowView */
        RunUsageRowView: {
            /** Calls */
            calls: number;
            /** Cost Source */
            cost_source: string;
            /** Cost Usd */
            cost_usd: string;
            /** Input Tokens */
            input_tokens: number;
            /** Model */
            model: string;
            /** Operation */
            operation: string;
            /** Output Tokens */
            output_tokens: number;
            /** Provider */
            provider: string;
        };
        /** RunUsageView */
        RunUsageView: {
            /** Calls */
            calls: number;
            /** Cost Usd */
            cost_usd: string;
            /** Rows */
            rows: components["schemas"]["RunUsageRowView"][];
            /**
             * Run Id
             * Format: uuid
             */
            run_id: string;
        };
        /** RunView */
        RunView: {
            /** Approval Request Id */
            approval_request_id: string | null;
            /** Error */
            error: {
                [key: string]: unknown;
            } | null;
            /** Graph Version */
            graph_version: string;
            /**
             * Id
             * Format: uuid
             */
            id: string;
            /** Release Manifest Ref */
            release_manifest_ref: string | null;
            /** Result */
            result: {
                [key: string]: unknown;
            } | null;
            /** Status */
            status: string;
            /** Worker Id */
            worker_id: string;
            /** Worker Version */
            worker_version: string;
        };
        /** ScorecardDecisionsView */
        ScorecardDecisionsView: {
            /** Approved As Is */
            approved_as_is: number;
            /** Approved Edited */
            approved_edited: number;
            /** Rejected */
            rejected: number;
        };
        /** ScorecardItemsView */
        ScorecardItemsView: {
            /** By Status */
            by_status: {
                [key: string]: number;
            };
            /** Done Alone Rate */
            done_alone_rate: number | null;
            /** Handed Off Rate */
            handed_off_rate: number | null;
            /** Total */
            total: number;
        };
        /** ScorecardView */
        ScorecardView: {
            /** Days */
            days: number;
            decisions: components["schemas"]["ScorecardDecisionsView"];
            /**
             * Dw Id
             * Format: uuid
             */
            dw_id: string;
            items: components["schemas"]["ScorecardItemsView"];
            /** Model Cost Usd */
            model_cost_usd: string;
            /**
             * Since
             * Format: date-time
             */
            since: string;
        };
        /**
         * SecretFieldView
         * @description A declared secret field: `configured` while a version of it is not
         *     revoked ("Đã cấu hình"). Never a value.
         */
        SecretFieldView: {
            /** Configured */
            configured: boolean;
            /** Field */
            field: string;
        };
        /** ServicePrincipalView */
        ServicePrincipalView: {
            /** Bindable By Me */
            bindable_by_me: boolean;
            /** Description */
            description: string | null;
            /**
             * Id
             * Format: uuid
             */
            id: string;
            /** Name */
            name: string;
            /** Owner Missing */
            owner_missing: boolean;
            /** Owner User Id */
            owner_user_id: string | null;
            /**
             * Owning Workspace Id
             * Format: uuid
             */
            owning_workspace_id: string;
            /** Status */
            status: ("invited" | "active" | "suspended") | null;
        };
        /** SetManagerBody */
        SetManagerBody: {
            /** Manager User Id */
            manager_user_id?: string | null;
        };
        /** SetMembershipsRequest */
        SetMembershipsRequest: {
            /** Memberships */
            memberships: components["schemas"]["WorkspaceRolesBody"][];
        };
        /** SetPermissionSetsBody */
        SetPermissionSetsBody: {
            /** Permission Set Keys */
            permission_set_keys: string[];
        };
        /** SimulationView */
        SimulationView: {
            /** Content Sha256 */
            content_sha256: string;
            /**
             * Created At
             * Format: date-time
             */
            created_at: string;
            /** Error */
            error: string | null;
            /** Failed Step */
            failed_step: string | null;
            /**
             * Outcome
             * @enum {string}
             */
            outcome: "passed" | "failed";
            /** Tool Calls */
            tool_calls: {
                [key: string]: unknown;
            }[];
            /** Trail */
            trail: {
                [key: string]: unknown;
            }[];
        };
        /** SodRuleView */
        SodRuleView: {
            /** Description */
            description: string;
            /** Key */
            key: string;
            /** Left Scopes */
            left_scopes: string[];
            /** Right Scopes */
            right_scopes: string[];
            /** Waivable */
            waivable: boolean;
            waiver: components["schemas"]["SodWaiverView"] | null;
        };
        /** SodWaiverView */
        SodWaiverView: {
            /** Confirmed At */
            confirmed_at: string | null;
            /** Confirmed By */
            confirmed_by: string | null;
            /**
             * Granted At
             * Format: date-time
             */
            granted_at: string;
            /**
             * Granted By
             * Format: uuid
             */
            granted_by: string;
            /** Reason */
            reason: string;
        };
        /** StepChangeView */
        StepChangeView: {
            /**
             * Change
             * @enum {string}
             */
            change: "added" | "removed" | "changed" | "moved";
            /** From Lane */
            from_lane: string | null;
            /** Lane */
            lane: string;
            /** Step Id */
            step_id: string;
            /** Type */
            type: string;
        };
        /** SupportGrantModel */
        SupportGrantModel: {
            /** Activated At */
            activated_at: string | null;
            /** Code */
            code: string;
            /** Duration Hours */
            duration_hours: number;
            /** Expires At */
            expires_at: string | null;
            /** Granted At */
            granted_at: string | null;
            /** Granted By */
            granted_by: string | null;
            /**
             * Id
             * Format: uuid
             */
            id: string;
            /** Reason */
            reason: string;
            /** Reject Reason */
            reject_reason: string | null;
            /** Rejected At */
            rejected_at: string | null;
            /**
             * Requested At
             * Format: date-time
             */
            requested_at: string;
            /** Requested By */
            requested_by: string | null;
            /** Resource Id */
            resource_id: string | null;
            /** Resource Label */
            resource_label: string;
            /** Resource Type */
            resource_type: string;
            /** Revoked At */
            revoked_at: string | null;
            /** Scope Set Key */
            scope_set_key: string;
            /** Scope Set Label */
            scope_set_label: string;
            /** Staff User Id */
            staff_user_id: string | null;
            /** State */
            state: string;
            /** Status */
            status: string;
            /**
             * Workspace Id
             * Format: uuid
             */
            workspace_id: string;
        };
        /**
         * SupportRequestView
         * @description A grant waiting for a person: what the operator chooses by, no more.
         */
        SupportRequestView: {
            /** Code */
            code: string;
            /** Duration Hours */
            duration_hours: number;
            /**
             * Grant Id
             * Format: uuid
             */
            grant_id: string;
            /** Reason */
            reason: string;
            /**
             * Requested At
             * Format: date-time
             */
            requested_at: string;
            /** Resource Label */
            resource_label: string;
            /** Resource Type */
            resource_type: string;
            /** Scope Set Key */
            scope_set_key: string;
            /** Scope Set Label */
            scope_set_label: string;
            /**
             * Tenant Id
             * Format: uuid
             */
            tenant_id: string;
            /** Tenant Name */
            tenant_name: string;
            /**
             * Workspace Id
             * Format: uuid
             */
            workspace_id: string;
            /** Workspace Name */
            workspace_name: string;
        };
        /**
         * SupportScopeSetView
         * @description A grantable set: no scope list, only what a person chooses by.
         */
        SupportScopeSetView: {
            /** Key */
            key: string;
            /** Label */
            label: string;
            /** Resource Types */
            resource_types: string[];
        };
        /** SupportStaffView */
        SupportStaffView: {
            /**
             * Added At
             * Format: date-time
             */
            added_at: string;
            /** Display Name */
            display_name: string;
            /** Email */
            email: string | null;
            /** Note */
            note: string | null;
            /**
             * User Id
             * Format: uuid
             */
            user_id: string;
        };
        /** TenantMemberView */
        TenantMemberView: {
            /** Display Name */
            display_name: string;
            /** Email */
            email: string | null;
            /** Memberships */
            memberships: components["schemas"]["MemberWorkspaceView"][];
            /** Status */
            status: string;
            /**
             * User Id
             * Format: uuid
             */
            user_id: string;
        };
        /** TenantSettingsView */
        TenantSettingsView: {
            /** Locale */
            locale: string | null;
            /**
             * Max Autonomy Level
             * @enum {string}
             */
            max_autonomy_level: "A0" | "A1" | "A2" | "A3" | "A4";
            /** Name */
            name: string;
            /** Record Visibility */
            record_visibility: string;
            /** Slug */
            slug: string;
            /** Status */
            status: string;
            /**
             * Tenant Id
             * Format: uuid
             */
            tenant_id: string;
            /** Timezone */
            timezone: string | null;
        };
        /** TenantView */
        TenantView: {
            /**
             * Created At
             * Format: date-time
             */
            created_at: string;
            /**
             * Id
             * Format: uuid
             */
            id: string;
            /** Member Count */
            member_count: number;
            /** Name */
            name: string;
            /** Owner Coverage Low Since */
            owner_coverage_low_since: string | null;
            /** Plan Id */
            plan_id: string | null;
            /** Slug */
            slug: string;
            /** Status */
            status: string;
            /** Workspace Count */
            workspace_count: number;
        };
        /** TimelineEvent */
        TimelineEvent: {
            /** Action */
            action: string;
            /** Details */
            details: {
                [key: string]: unknown;
            };
            /**
             * Occurred At
             * Format: date-time
             */
            occurred_at: string;
            /** Policy Decision */
            policy_decision: string | null;
            /** Resource Id */
            resource_id: string;
            /** Resource Type */
            resource_type: string;
        };
        /** TrailEntryView */
        TrailEntryView: {
            /** At */
            at: string;
            /** Status */
            status: string;
            /** Step Id */
            step_id: string;
            /** Type */
            type: string;
        };
        /**
         * UnfreezeRequestView
         * @description The approval that lifts the freeze once a second person approves it.
         */
        UnfreezeRequestView: {
            /**
             * Approval Id
             * Format: uuid
             */
            approval_id: string;
            /**
             * Status
             * @default pending
             */
            status: string;
        };
        /** UnsubscribeView */
        UnsubscribeView: {
            /** Channel */
            channel: string;
            /** Unsubscribed */
            unsubscribed: boolean;
        };
        /**
         * UpdateServicePrincipalBody
         * @description Only the members sent change; `description: null` empties it. A name
         *     or an accountable owner cannot be emptied (R6.16).
         */
        UpdateServicePrincipalBody: {
            /** Description */
            description?: string | null;
            /** Name */
            name?: string | null;
            /** Owner User Id */
            owner_user_id?: string | null;
        };
        /** UpdateTenantBody */
        UpdateTenantBody: {
            /** Locale */
            locale?: string | null;
            /** Max Autonomy Level */
            max_autonomy_level?: ("A0" | "A1" | "A2" | "A3" | "A4") | null;
            /** Name */
            name?: string | null;
            /** Record Visibility */
            record_visibility?: string | null;
            /** Timezone */
            timezone?: string | null;
        };
        /** UsageGroupView */
        UsageGroupView: {
            /** Artifact Kind */
            artifact_kind: string | null;
            /** Calls */
            calls: number;
            /** Cost Usd */
            cost_usd: string;
            /** Estimated Calls */
            estimated_calls: number;
            /** Input Tokens */
            input_tokens: number;
            /** Key */
            key: string | null;
            /** Label */
            label: string | null;
            /** Output Tokens */
            output_tokens: number;
            /** Unpriced Calls */
            unpriced_calls: number;
        };
        /** UsageSummaryView */
        UsageSummaryView: {
            /** Calls */
            calls: number;
            /** Cost Usd */
            cost_usd: string;
            /** Estimated Calls */
            estimated_calls: number;
            /**
             * First Day
             * Format: date
             */
            first_day: string;
            /**
             * Group By
             * @enum {string}
             */
            group_by: "workspace" | "artifact" | "purpose";
            /** Groups */
            groups: components["schemas"]["UsageGroupView"][];
            /** Input Tokens */
            input_tokens: number;
            /**
             * Last Day
             * Format: date
             */
            last_day: string;
            /** Output Tokens */
            output_tokens: number;
            /** Timezone */
            timezone: string;
            /** Unpriced Calls */
            unpriced_calls: number;
        };
        /** UserRefView */
        UserRefView: {
            /** Display Name */
            display_name: string;
            /** Email */
            email: string | null;
            /**
             * User Id
             * Format: uuid
             */
            user_id: string;
        };
        /** VersionList */
        VersionList: {
            /** Items */
            items: components["schemas"]["VersionView"][];
        };
        /** VersionView */
        VersionView: {
            /** Based On Version Id */
            based_on_version_id: string | null;
            /** Change Note */
            change_note: string | null;
            /** Content Hash */
            content_hash: string | null;
            /** Definition Hash */
            definition_hash: string | null;
            /** Document */
            document: {
                [key: string]: unknown;
            };
            /** Document Schema */
            document_schema: string;
            /**
             * Id
             * Format: uuid
             */
            id: string;
            /** Stage */
            stage: string;
            /** Version No */
            version_no: number;
        };
        /** ViewRequest */
        ViewRequest: {
            /**
             * Comment
             * @default
             */
            comment: string;
            /**
             * Issue Code
             * @default false
             */
            issue_code: boolean;
        };
        /** WaiverDecisionBody */
        WaiverDecisionBody: {
            /** Reason */
            reason: string;
        };
        /** WorkItemView */
        WorkItemView: {
            /**
             * Available At
             * Format: date-time
             */
            available_at: string;
            /** Closed At */
            closed_at: string | null;
            /**
             * Created At
             * Format: date-time
             */
            created_at: string;
            /**
             * Dw Id
             * Format: uuid
             */
            dw_id: string;
            /** Error */
            error: string | null;
            handoff?: components["schemas"]["HandoffView"] | null;
            /**
             * Holder Id
             * Format: uuid
             */
            holder_id: string;
            /** Holder Kind */
            holder_kind: string;
            /**
             * Id
             * Format: uuid
             */
            id: string;
            /** Kind */
            kind: string;
            /** Payload */
            payload?: {
                [key: string]: unknown;
            } | null;
            /** Source Key */
            source_key: string;
            /** Status */
            status: string;
            /** Trail */
            trail?: components["schemas"]["TrailEntryView"][] | null;
            /**
             * Updated At
             * Format: date-time
             */
            updated_at: string;
            /** Wake At */
            wake_at: string | null;
        };
        /** WorkflowOutlineView */
        WorkflowOutlineView: {
            /** Decision Classes */
            decision_classes: components["schemas"]["ClassStandingView"][];
            /**
             * Dw Id
             * Format: uuid
             */
            dw_id: string;
            /** Key */
            key: string;
            /** Sha256 */
            sha256: string;
            /** Steps */
            steps: components["schemas"]["OutlineStepView"][];
            /** Version */
            version: string;
        };
        /** WorkflowProblemView */
        WorkflowProblemView: {
            /** Code */
            code: string;
            /** Message En */
            message_en: string;
            /** Message Vi */
            message_vi: string;
            /** Path */
            path: string;
        };
        /** WorkspaceMemberView */
        WorkspaceMemberView: {
            /** Department */
            department: string;
            /** Display Name */
            display_name: string;
            /** Email */
            email: string | null;
            /** Permission Set Keys */
            permission_set_keys: string[];
            /** Role Keys */
            role_keys: string[];
            /** Status */
            status: string;
            /**
             * User Id
             * Format: uuid
             */
            user_id: string;
        };
        /** WorkspaceMembershipModel */
        WorkspaceMembershipModel: {
            /**
             * Tenant Id
             * Format: uuid
             */
            tenant_id: string;
            /** Tenant Name */
            tenant_name: string;
            /** Tenant Slug */
            tenant_slug: string;
            /**
             * Workspace Id
             * Format: uuid
             */
            workspace_id: string;
            /** Workspace Name */
            workspace_name: string;
            /** Workspace Slug */
            workspace_slug: string;
        };
        /** WorkspaceRefView */
        WorkspaceRefView: {
            /** Name */
            name: string;
            /** Slug */
            slug: string;
            /**
             * Workspace Id
             * Format: uuid
             */
            workspace_id: string;
        };
        /** WorkspaceRolesBody */
        WorkspaceRolesBody: {
            /** Role Keys */
            role_keys: string[];
            /**
             * Workspace Id
             * Format: uuid
             */
            workspace_id: string;
        };
        /** WorkspaceSummaryView */
        WorkspaceSummaryView: {
            /** Archived */
            archived: boolean;
            /** Member Count */
            member_count: number;
            /** Name */
            name: string;
            /** Slug */
            slug: string;
            /**
             * Workspace Id
             * Format: uuid
             */
            workspace_id: string;
        };
        /** ZaloConnectView */
        ZaloConnectView: {
            /** Code */
            code: string;
            /** Deep Link */
            deep_link: string | null;
            /**
             * Expires At
             * Format: date-time
             */
            expires_at: string;
        };
        /** ZaloStatusView */
        ZaloStatusView: {
            /** Linked */
            linked: boolean;
        };
        /** ZaloWorkspaceChoice */
        ZaloWorkspaceChoice: {
            /**
             * Tenant Id
             * Format: uuid
             */
            tenant_id: string;
            /**
             * Workspace Id
             * Format: uuid
             */
            workspace_id: string;
        };
        /** ZaloWorkspaceView */
        ZaloWorkspaceView: {
            /** Tenant Id */
            tenant_id: string | null;
            /** Workspace Id */
            workspace_id: string | null;
        };
    };
    responses: never;
    parameters: never;
    requestBodies: never;
    headers: never;
    pathItems: never;
}
export type $defs = Record<string, never>;
export interface operations {
    freeze_api_v1_admin_freeze_post: {
        parameters: {
            query?: never;
            header?: {
                /** @description Optional. Retrying with the same key returns the first response instead of acting twice; reusing it for a different request, or another person's key, is a 409. */
                "Idempotency-Key"?: string | null;
            };
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["FreezeBody"];
            };
        };
        responses: {
            /** @description Successful Response */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["FreezeView"];
                };
            };
            /** @description The request was refused */
            "4XX": {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
            /** @description The server failed */
            "5XX": {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
        };
    };
    get_hierarchy_api_v1_admin_hierarchy_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HierarchyMemberView"][];
                };
            };
            /** @description The request was refused */
            "4XX": {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
            /** @description The server failed */
            "5XX": {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
        };
    };
    set_manager_api_v1_admin_hierarchy__user_id__put: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                user_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["SetManagerBody"];
            };
        };
        responses: {
            /** @description Successful Response */
            204: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description The request was refused */
            "4XX": {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
            /** @description The server failed */
            "5XX": {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
        };
    };
    invite_member_api_v1_admin_invitations_post: {
        parameters: {
            query?: never;
            header?: {
                /** @description Optional. Retrying with the same key returns the first response instead of acting twice; reusing it for a different request, or another person's key, is a 409. */
                "Idempotency-Key"?: string | null;
            };
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["InviteMemberRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["MemberRefView"];
                };
            };
            /** @description The request was refused */
            "4XX": {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
            /** @description The server failed */
            "5XX": {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
        };
    };
    list_members_api_v1_admin_members_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["TenantMemberView"][];
                };
            };
            /** @description The request was refused */
            "4XX": {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
            /** @description The server failed */
            "5XX": {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
        };
    };
    grant_member_api_v1_admin_members_post: {
        parameters: {
            query?: never;
            header?: {
                /** @description Optional. Retrying with the same key returns the first response instead of acting twice; reusing it for a different request, or another person's key, is a 409. */
                "Idempotency-Key"?: string | null;
            };
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["GrantMemberRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["MemberRefView"];
                };
            };
            /** @description The request was refused */
            "4XX": {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
            /** @description The server failed */
            "5XX": {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
        };
    };
    revoke_member_api_v1_admin_members__user_id__delete: {
        parameters: {
            query: {
                workspace_id: string;
            };
            header?: {
                /** @description Optional. Retrying with the same key returns the first response instead of acting twice; reusing it for a different request, or another person's key, is a 409. */
                "Idempotency-Key"?: string | null;
            };
            path: {
                user_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            204: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description The request was refused */
            "4XX": {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
            /** @description The server failed */
            "5XX": {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
        };
    };
    set_memberships_api_v1_admin_members__user_id__memberships_put: {
        parameters: {
            query?: never;
            header?: {
                /** @description Optional. Retrying with the same key returns the first response instead of acting twice; reusing it for a different request, or another person's key, is a 409. */
                "Idempotency-Key"?: string | null;
            };
            path: {
                user_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["SetMembershipsRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["MemberMembershipsView"];
                };
            };
            /** @description The request was refused */
            "4XX": {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
            /** @description The server failed */
            "5XX": {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
        };
    };
    set_permission_sets_api_v1_admin_members__user_id__permission_sets_put: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                user_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["SetPermissionSetsBody"];
            };
        };
        responses: {
            /** @description Successful Response */
            204: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description The request was refused */
            "4XX": {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
            /** @description The server failed */
            "5XX": {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
        };
    };
    list_permission_sets_api_v1_admin_permission_sets_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["PermissionSetView"][];
                };
            };
            /** @description The request was refused */
            "4XX": {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
            /** @description The server failed */
            "5XX": {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
        };
    };
    list_permissions_api_v1_admin_permissions_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["PermissionView"][];
                };
            };
            /** @description The request was refused */
            "4XX": {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
            /** @description The server failed */
            "5XX": {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
        };
    };
    list_roles_api_v1_admin_roles_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["RoleView"][];
                };
            };
            /** @description The request was refused */
            "4XX": {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
            /** @description The server failed */
            "5XX": {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
        };
    };
    list_separation_of_duties_api_v1_admin_separation_of_duties_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["SodRuleView"][];
                };
            };
            /** @description The request was refused */
            "4XX": {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
            /** @description The server failed */
            "5XX": {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
        };
    };
    waive_separation_of_duties_rule_api_v1_admin_separation_of_duties__rule_key__waiver_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                rule_key: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["WaiverDecisionBody"];
            };
        };
        responses: {
            /** @description Successful Response */
            204: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description The request was refused */
            "4XX": {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
            /** @description The server failed */
            "5XX": {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
        };
    };
    confirm_separation_of_duties_waiver_api_v1_admin_separation_of_duties__rule_key__waiver_confirm_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                rule_key: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["WaiverDecisionBody"];
            };
        };
        responses: {
            /** @description Successful Response */
            204: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description The request was refused */
            "4XX": {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
            /** @description The server failed */
            "5XX": {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
        };
    };
    revoke_separation_of_duties_waiver_api_v1_admin_separation_of_duties__rule_key__waiver_revoke_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                rule_key: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["WaiverDecisionBody"];
            };
        };
        responses: {
            /** @description Successful Response */
            204: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description The request was refused */
            "4XX": {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
            /** @description The server failed */
            "5XX": {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
        };
    };
    list_service_principals_api_v1_admin_service_principals_get: {
        parameters: {
            query?: {
                limit?: number;
                /** @description Opaque cursor from a previous page. */
                cursor?: string | null;
            };
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["Page_ServicePrincipalView_"];
                };
            };
            /** @description The request was refused */
            "4XX": {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
            /** @description The server failed */
            "5XX": {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
        };
    };
    create_service_principal_api_v1_admin_service_principals_post: {
        parameters: {
            query?: never;
            header?: {
                /** @description Optional. Retrying with the same key returns the first response instead of acting twice; reusing it for a different request, or another person's key, is a 409. */
                "Idempotency-Key"?: string | null;
            };
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["CreateServicePrincipalBody"];
            };
        };
        responses: {
            /** @description Successful Response */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ServicePrincipalView"];
                };
            };
            /** @description The request was refused */
            "4XX": {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
            /** @description The server failed */
            "5XX": {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
        };
    };
    update_service_principal_api_v1_admin_service_principals__service_principal_id__patch: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                service_principal_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["UpdateServicePrincipalBody"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ServicePrincipalView"];
                };
            };
            /** @description The request was refused */
            "4XX": {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
            /** @description The server failed */
            "5XX": {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
        };
    };
    get_tenant_api_v1_admin_tenant_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["TenantSettingsView"];
                };
            };
            /** @description The request was refused */
            "4XX": {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
            /** @description The server failed */
            "5XX": {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
        };
    };
    update_tenant_api_v1_admin_tenant_patch: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["UpdateTenantBody"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["TenantSettingsView"];
                };
            };
            /** @description The request was refused */
            "4XX": {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
            /** @description The server failed */
            "5XX": {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
        };
    };
    unfreeze_api_v1_admin_unfreeze_post: {
        parameters: {
            query?: never;
            header?: {
                /** @description Optional. Retrying with the same key returns the first response instead of acting twice; reusing it for a different request, or another person's key, is a 409. */
                "Idempotency-Key"?: string | null;
            };
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            202: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["UnfreezeRequestView"];
                };
            };
            /** @description The request was refused */
            "4XX": {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
            /** @description The server failed */
            "5XX": {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
        };
    };
    list_workspaces_api_v1_admin_workspaces_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["WorkspaceSummaryView"][];
                };
            };
            /** @description The request was refused */
            "4XX": {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
            /** @description The server failed */
            "5XX": {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
        };
    };
    create_workspace_api_v1_admin_workspaces_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["CreateWorkspaceBody"];
            };
        };
        responses: {
            /** @description Successful Response */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["WorkspaceRefView"];
                };
            };
            /** @description The request was refused */
            "4XX": {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
            /** @description The server failed */
            "5XX": {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
        };
    };
    rename_workspace_api_v1_admin_workspaces__workspace_id__patch: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                workspace_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["RenameWorkspaceBody"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["WorkspaceRefView"];
                };
            };
            /** @description The request was refused */
            "4XX": {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
            /** @description The server failed */
            "5XX": {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
        };
    };
    archive_workspace_api_v1_admin_workspaces__workspace_id__archive_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                workspace_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            204: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description The request was refused */
            "4XX": {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
            /** @description The server failed */
            "5XX": {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
        };
    };
    list_pending_api_v1_approvals_get: {
        parameters: {
            query?: {
                limit?: number;
                /** @description Opaque cursor from a previous page. */
                cursor?: string | null;
            };
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["Page_ApprovalView_"];
                };
            };
            /** @description The request was refused */
            "4XX": {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
            /** @description The server failed */
            "5XX": {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
        };
    };
    get_approval_api_v1_approvals__approval_id__get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                approval_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ApprovalView"];
                };
            };
            /** @description The request was refused */
            "4XX": {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
            /** @description The server failed */
            "5XX": {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
        };
    };
    decide_api_v1_approvals__approval_id__decisions_post: {
        parameters: {
            query?: never;
            header?: {
                /** @description Optional. Retrying with the same key returns the first response instead of acting twice; reusing it for a different request, or another person's key, is a 409. */
                "Idempotency-Key"?: string | null;
            };
            path: {
                approval_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["DecisionRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ApprovalView"];
                };
            };
            /** @description The request was refused */
            "4XX": {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
            /** @description The server failed */
            "5XX": {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
        };
    };
    view_approval_api_v1_approvals__approval_id__view_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                approval_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["ViewRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ApprovalViewOutcome"];
                };
            };
            /** @description The request was refused */
            "4XX": {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
            /** @description The server failed */
            "5XX": {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
        };
    };
    list_events_api_v1_audit_events_get: {
        parameters: {
            query?: {
                limit?: number;
                /** @description Opaque cursor from a previous page. */
                cursor?: string | null;
            };
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["Page_AuditEventView_"];
                };
            };
            /** @description The request was refused */
            "4XX": {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
            /** @description The server failed */
            "5XX": {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
        };
    };
    bootstrap_api_v1_auth_bootstrap_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["BootstrapResponse"];
                };
            };
            /** @description The request was refused */
            "4XX": {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
            /** @description The server failed */
            "5XX": {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
        };
    };
    list_connections_api_v1_connections_get: {
        parameters: {
            query?: {
                limit?: number;
                /** @description Opaque cursor from a previous page. */
                cursor?: string | null;
            };
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["Page_ConnectionView_"];
                };
            };
            /** @description The request was refused */
            "4XX": {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
            /** @description The server failed */
            "5XX": {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
        };
    };
    create_connection_api_v1_connections_post: {
        parameters: {
            query?: never;
            header?: {
                /** @description Optional. Retrying with the same key returns the first response instead of acting twice; reusing it for a different request, or another person's key, is a 409. */
                "Idempotency-Key"?: string | null;
            };
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["NewConnectionBody"];
            };
        };
        responses: {
            /** @description Successful Response */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ConnectionDetailView"];
                };
            };
            /** @description The request was refused */
            "4XX": {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
            /** @description The server failed */
            "5XX": {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
        };
    };
    get_connection_api_v1_connections__connection_id__get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                connection_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ConnectionDetailView"];
                };
            };
            /** @description The request was refused */
            "4XX": {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
            /** @description The server failed */
            "5XX": {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
        };
    };
    delete_connection_api_v1_connections__connection_id__delete: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                connection_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            204: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description The request was refused */
            "4XX": {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
            /** @description The server failed */
            "5XX": {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
        };
    };
    update_connection_api_v1_connections__connection_id__patch: {
        parameters: {
            query?: never;
            header?: {
                /** @description Optional. Retrying with the same key returns the first response instead of acting twice; reusing it for a different request, or another person's key, is a 409. */
                "Idempotency-Key"?: string | null;
            };
            path: {
                connection_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["ConnectionPatchBody"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ConnectionDetailView"];
                };
            };
            /** @description The request was refused */
            "4XX": {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
            /** @description The server failed */
            "5XX": {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
        };
    };
    connection_dependents_api_v1_connections__connection_id__dependents_get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                connection_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ConnectionDependentsView"];
                };
            };
            /** @description The request was refused */
            "4XX": {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
            /** @description The server failed */
            "5XX": {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
        };
    };
    disable_connection_api_v1_connections__connection_id__disable_post: {
        parameters: {
            query?: never;
            header?: {
                /** @description Optional. Retrying with the same key returns the first response instead of acting twice; reusing it for a different request, or another person's key, is a 409. */
                "Idempotency-Key"?: string | null;
            };
            path: {
                connection_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ConnectionDetailView"];
                };
            };
            /** @description The request was refused */
            "4XX": {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
            /** @description The server failed */
            "5XX": {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
        };
    };
    enable_connection_api_v1_connections__connection_id__enable_post: {
        parameters: {
            query?: never;
            header?: {
                /** @description Optional. Retrying with the same key returns the first response instead of acting twice; reusing it for a different request, or another person's key, is a 409. */
                "Idempotency-Key"?: string | null;
            };
            path: {
                connection_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            202: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["EnableRequestView"];
                };
            };
            /** @description The request was refused */
            "4XX": {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
            /** @description The server failed */
            "5XX": {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
        };
    };
    revoke_connection_credentials_api_v1_connections__connection_id__revoke_credentials_post: {
        parameters: {
            query?: never;
            header?: {
                /** @description Optional. Retrying with the same key returns the first response instead of acting twice; reusing it for a different request, or another person's key, is a 409. */
                "Idempotency-Key"?: string | null;
            };
            path: {
                connection_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ConnectionDetailView"];
                };
            };
            /** @description The request was refused */
            "4XX": {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
            /** @description The server failed */
            "5XX": {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
        };
    };
    control_state_api_v1_control_state_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ControlStateView"];
                };
            };
            /** @description The request was refused */
            "4XX": {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
            /** @description The server failed */
            "5XX": {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
        };
    };
    demo_users_api_v1_dev_demo_users_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["DemoUser"][];
                };
            };
            /** @description The request was refused */
            "4XX": {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
            /** @description The server failed */
            "5XX": {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
        };
    };
    create_session_api_v1_dev_session_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["DevSessionRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["DevSessionResponse"];
                };
            };
            /** @description The request was refused */
            "4XX": {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
            /** @description The server failed */
            "5XX": {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
        };
    };
    list_digital_workers_api_v1_digital_workers_get: {
        parameters: {
            query?: {
                limit?: number;
                /** @description Opaque cursor from a previous page. */
                cursor?: string | null;
            };
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["Page_DigitalWorkerListItemView_"];
                };
            };
            /** @description The request was refused */
            "4XX": {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
            /** @description The server failed */
            "5XX": {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
        };
    };
    create_digital_worker_api_v1_digital_workers_post: {
        parameters: {
            query?: never;
            header?: {
                /** @description Optional. Retrying with the same key returns the first response instead of acting twice; reusing it for a different request, or another person's key, is a 409. */
                "Idempotency-Key"?: string | null;
            };
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["CreateDigitalWorkerRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["DigitalWorkerView"];
                };
            };
            /** @description The request was refused */
            "4XX": {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
            /** @description The server failed */
            "5XX": {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
        };
    };
    get_digital_worker_api_v1_digital_workers__dw_id__get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                dw_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["DigitalWorkerView"];
                };
            };
            /** @description The request was refused */
            "4XX": {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
            /** @description The server failed */
            "5XX": {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
        };
    };
    change_decision_class_autonomy_api_v1_digital_workers__dw_id__decision_classes__key__autonomy_post: {
        parameters: {
            query?: never;
            header?: {
                /** @description Optional. Retrying with the same key returns the first response instead of acting twice; reusing it for a different request, or another person's key, is a 409. */
                "Idempotency-Key"?: string | null;
            };
            path: {
                dw_id: string;
                key: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["AutonomyRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AutonomyChangeView"];
                };
            };
            /** @description a raise waits for approval */
            202: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AutonomyChangeView"];
                };
            };
            /** @description The request was refused */
            "4XX": {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
            /** @description The server failed */
            "5XX": {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
        };
    };
    read_intake_key_api_v1_digital_workers__dw_id__intake_key_get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                dw_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["IntakeKey"];
                };
            };
            /** @description The request was refused */
            "4XX": {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
            /** @description The server failed */
            "5XX": {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
        };
    };
    replace_digital_worker_people_api_v1_digital_workers__dw_id__people_put: {
        parameters: {
            query?: never;
            header?: {
                /** @description Optional. Retrying with the same key returns the first response instead of acting twice; reusing it for a different request, or another person's key, is a 409. */
                "Idempotency-Key"?: string | null;
            };
            path: {
                dw_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["PeopleBody"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["DigitalWorkerView"];
                };
            };
            /** @description The request was refused */
            "4XX": {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
            /** @description The server failed */
            "5XX": {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
        };
    };
    get_digital_worker_scorecard_api_v1_digital_workers__dw_id__scorecard_get: {
        parameters: {
            query?: {
                days?: number;
            };
            header?: never;
            path: {
                dw_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ScorecardView"];
                };
            };
            /** @description The request was refused */
            "4XX": {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
            /** @description The server failed */
            "5XX": {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
        };
    };
    change_digital_worker_state_api_v1_digital_workers__dw_id__state_post: {
        parameters: {
            query?: never;
            header?: {
                /** @description Optional. Retrying with the same key returns the first response instead of acting twice; reusing it for a different request, or another person's key, is a 409. */
                "Idempotency-Key"?: string | null;
            };
            path: {
                dw_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["ChangeStateRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["DigitalWorkerView"];
                };
            };
            /** @description The request was refused */
            "4XX": {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
            /** @description The server failed */
            "5XX": {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
        };
    };
    give_work_api_v1_digital_workers__dw_id__work_items_post: {
        parameters: {
            query?: never;
            header?: {
                /** @description Optional. Retrying with the same key returns the first response instead of acting twice; reusing it for a different request, or another person's key, is a 409. */
                "Idempotency-Key"?: string | null;
            };
            path: {
                dw_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["NewWorkRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["WorkItemView"];
                };
            };
            /** @description The request was refused */
            "4XX": {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
            /** @description The server failed */
            "5XX": {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
        };
    };
    get_digital_worker_workflow_api_v1_digital_workers__dw_id__workflow_get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                dw_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["WorkflowOutlineView"];
                };
            };
            /** @description The request was refused */
            "4XX": {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
            /** @description The server failed */
            "5XX": {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
        };
    };
    ask_workflow_assistant_api_v1_digital_workers__dw_id__workflow_assistant_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                dw_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["AssistantRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AssistantAnswerView"];
                };
            };
            /** @description The request was refused */
            "4XX": {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
            /** @description The server failed */
            "5XX": {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
        };
    };
    get_workflow_draft_api_v1_digital_workers__dw_id__workflow_draft_get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                dw_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["DraftView"];
                };
            };
            /** @description The request was refused */
            "4XX": {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
            /** @description The server failed */
            "5XX": {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
        };
    };
    save_workflow_draft_api_v1_digital_workers__dw_id__workflow_draft_put: {
        parameters: {
            query?: never;
            header?: {
                /** @description Optional. Retrying with the same key returns the first response instead of acting twice; reusing it for a different request, or another person's key, is a 409. */
                "Idempotency-Key"?: string | null;
            };
            path: {
                dw_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["DraftBody"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["DraftView"];
                };
            };
            /** @description The request was refused */
            "4XX": {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
            /** @description The server failed */
            "5XX": {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
        };
    };
    review_workflow_draft_api_v1_digital_workers__dw_id__workflow_draft_review_get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                dw_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["DraftReviewView"];
                };
            };
            /** @description The request was refused */
            "4XX": {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
            /** @description The server failed */
            "5XX": {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
        };
    };
    simulate_workflow_draft_api_v1_digital_workers__dw_id__workflow_draft_simulate_post: {
        parameters: {
            query?: never;
            header?: {
                /** @description Optional. Retrying with the same key returns the first response instead of acting twice; reusing it for a different request, or another person's key, is a 409. */
                "Idempotency-Key"?: string | null;
            };
            path: {
                dw_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["SimulationView"];
                };
            };
            /** @description The request was refused */
            "4XX": {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
            /** @description The server failed */
            "5XX": {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
        };
    };
    submit_workflow_draft_api_v1_digital_workers__dw_id__workflow_draft_submit_post: {
        parameters: {
            query?: never;
            header?: {
                /** @description Optional. Retrying with the same key returns the first response instead of acting twice; reusing it for a different request, or another person's key, is a 409. */
                "Idempotency-Key"?: string | null;
            };
            path: {
                dw_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["DraftView"];
                };
            };
            /** @description The request was refused */
            "4XX": {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
            /** @description The server failed */
            "5XX": {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
        };
    };
    withdraw_workflow_draft_api_v1_digital_workers__dw_id__workflow_draft_withdraw_post: {
        parameters: {
            query?: never;
            header?: {
                /** @description Optional. Retrying with the same key returns the first response instead of acting twice; reusing it for a different request, or another person's key, is a 409. */
                "Idempotency-Key"?: string | null;
            };
            path: {
                dw_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["DraftView"];
                };
            };
            /** @description The request was refused */
            "4XX": {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
            /** @description The server failed */
            "5XX": {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
        };
    };
    list_candidates_api_v1_directory_candidates_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["IdentityRefView"][];
                };
            };
            /** @description The request was refused */
            "4XX": {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
            /** @description The server failed */
            "5XX": {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
        };
    };
    list_members_api_v1_directory_members_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["WorkspaceMemberView"][];
                };
            };
            /** @description The request was refused */
            "4XX": {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
            /** @description The server failed */
            "5XX": {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
        };
    };
    list_allowed_hosts_api_v1_egress_allowed_hosts_get: {
        parameters: {
            query?: {
                limit?: number;
                /** @description Opaque cursor from a previous page. */
                cursor?: string | null;
            };
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["Page_AllowedHostView_"];
                };
            };
            /** @description The request was refused */
            "4XX": {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
            /** @description The server failed */
            "5XX": {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
        };
    };
    request_allowed_host_api_v1_egress_allowed_hosts_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["AllowedHostRequestBody"];
            };
        };
        responses: {
            /** @description Successful Response */
            202: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AllowedHostRequestView"];
                };
            };
            /** @description The request was refused */
            "4XX": {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
            /** @description The server failed */
            "5XX": {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
        };
    };
    remove_allowed_host_api_v1_egress_allowed_hosts__host_id__delete: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                host_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            204: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description The request was refused */
            "4XX": {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
            /** @description The server failed */
            "5XX": {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
        };
    };
    list_feedback_api_v1_feedback_get: {
        parameters: {
            query?: {
                limit?: number;
                /** @description Opaque cursor from a previous page. */
                cursor?: string | null;
            };
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["Page_FeedbackView_"];
                };
            };
            /** @description The request was refused */
            "4XX": {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
            /** @description The server failed */
            "5XX": {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
        };
    };
    submit_feedback_api_v1_feedback_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "multipart/form-data": components["schemas"]["Body_submit_feedback_api_v1_feedback_post"];
            };
        };
        responses: {
            /** @description Successful Response */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
            /** @description The request was refused */
            "4XX": {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
            /** @description The server failed */
            "5XX": {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
        };
    };
    read_attachment_api_v1_feedback__feedback_id__attachments__attachment_id__get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                feedback_id: string;
                attachment_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
            /** @description The request was refused */
            "4XX": {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
            /** @description The server failed */
            "5XX": {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
        };
    };
    health_api_v1_health_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HealthResponse"];
                };
            };
            /** @description The request was refused */
            "4XX": {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
            /** @description The server failed */
            "5XX": {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
        };
    };
    receive_lead_api_v1_intake_leads_post: {
        parameters: {
            query?: never;
            header?: {
                "x-dw-worker"?: string | null;
                "x-dw-event-id"?: string | null;
                "x-dw-timestamp"?: string | null;
                "x-dw-signature"?: string | null;
            };
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            202: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["Received"];
                };
            };
            /** @description The request was refused */
            "4XX": {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
            /** @description The server failed */
            "5XX": {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
        };
    };
    list_integrations_api_v1_integrations_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["IntegrationView"][];
                };
            };
            /** @description The request was refused */
            "4XX": {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
            /** @description The server failed */
            "5XX": {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
        };
    };
    list_documents_api_v1_knowledge_documents_get: {
        parameters: {
            query?: {
                /** @description Narrow the listing to one domain. */
                domain?: string | null;
                limit?: number;
                /** @description Opaque cursor from a previous page. */
                cursor?: string | null;
            };
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["Page_KnowledgeDocumentView_"];
                };
            };
            /** @description The request was refused */
            "4XX": {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
            /** @description The server failed */
            "5XX": {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
        };
    };
    upload_document_api_v1_knowledge_documents_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "multipart/form-data": components["schemas"]["Body_upload_document_api_v1_knowledge_documents_post"];
            };
        };
        responses: {
            /** @description Successful Response */
            202: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["IngestJobView"];
                };
            };
            /** @description The request was refused */
            "4XX": {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
            /** @description The server failed */
            "5XX": {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
        };
    };
    get_ingest_job_api_v1_knowledge_documents_jobs__job_id__get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                job_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["IngestJobView"];
                };
            };
            /** @description The request was refused */
            "4XX": {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
            /** @description The server failed */
            "5XX": {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
        };
    };
    delete_document_api_v1_knowledge_documents__document_id__delete: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                document_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            204: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description The request was refused */
            "4XX": {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
            /** @description The server failed */
            "5XX": {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
        };
    };
    me_api_v1_me_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["MeResponse"];
                };
            };
            /** @description The request was refused */
            "4XX": {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
            /** @description The server failed */
            "5XX": {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
        };
    };
    get_candidate_api_v1_memory_candidates__candidate_id__get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                candidate_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["MemoryCandidateView"];
                };
            };
            /** @description The request was refused */
            "4XX": {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
            /** @description The server failed */
            "5XX": {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
        };
    };
    list_items_api_v1_memory_items_get: {
        parameters: {
            query?: {
                limit?: number;
                /** @description Opaque cursor from a previous page. */
                cursor?: string | null;
            };
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["Page_MemoryItemView_"];
                };
            };
            /** @description The request was refused */
            "4XX": {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
            /** @description The server failed */
            "5XX": {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
        };
    };
    list_notifications_api_v1_notifications_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["InboxView"];
                };
            };
            /** @description The request was refused */
            "4XX": {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
            /** @description The server failed */
            "5XX": {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
        };
    };
    mark_all_notifications_read_api_v1_notifications_read_all_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            204: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description The request was refused */
            "4XX": {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
            /** @description The server failed */
            "5XX": {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
        };
    };
    mark_notification_read_api_v1_notifications__notification_id__read_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                notification_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            204: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description The request was refused */
            "4XX": {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
            /** @description The server failed */
            "5XX": {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
        };
    };
    freeze_platform_api_v1_platform_freeze_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["PlatformFreezeRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["PlatformFreezeView"];
                };
            };
            /** @description The request was refused */
            "4XX": {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
            /** @description The server failed */
            "5XX": {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
        };
    };
    list_operators_api_v1_platform_operators_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["OperatorView"][];
                };
            };
            /** @description The request was refused */
            "4XX": {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
            /** @description The server failed */
            "5XX": {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
        };
    };
    add_operator_api_v1_platform_operators_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["AddOperatorRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["UserRefView"];
                };
            };
            /** @description The request was refused */
            "4XX": {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
            /** @description The server failed */
            "5XX": {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
        };
    };
    remove_operator_api_v1_platform_operators__user_id__delete: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                user_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            204: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description The request was refused */
            "4XX": {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
            /** @description The server failed */
            "5XX": {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
        };
    };
    list_support_requests_api_v1_platform_support_requests_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["SupportRequestView"][];
                };
            };
            /** @description The request was refused */
            "4XX": {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
            /** @description The server failed */
            "5XX": {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
        };
    };
    assign_support_request_api_v1_platform_support_requests__grant_id__assign_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                grant_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["AssignSupportRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AssignedSupportGrantView"];
                };
            };
            /** @description The request was refused */
            "4XX": {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
            /** @description The server failed */
            "5XX": {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
        };
    };
    list_support_staff_api_v1_platform_support_staff_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["SupportStaffView"][];
                };
            };
            /** @description The request was refused */
            "4XX": {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
            /** @description The server failed */
            "5XX": {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
        };
    };
    add_support_staff_api_v1_platform_support_staff_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["AddSupportStaffRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["UserRefView"];
                };
            };
            /** @description The request was refused */
            "4XX": {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
            /** @description The server failed */
            "5XX": {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
        };
    };
    remove_support_staff_api_v1_platform_support_staff__user_id__delete: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                user_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            204: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description The request was refused */
            "4XX": {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
            /** @description The server failed */
            "5XX": {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
        };
    };
    list_tenants_api_v1_platform_tenants_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["TenantView"][];
                };
            };
            /** @description The request was refused */
            "4XX": {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
            /** @description The server failed */
            "5XX": {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
        };
    };
    create_tenant_api_v1_platform_tenants_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["CreateTenantRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["NewTenantView"];
                };
            };
            /** @description The request was refused */
            "4XX": {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
            /** @description The server failed */
            "5XX": {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
        };
    };
    rename_tenant_api_v1_platform_tenants__tenant_id__patch: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                tenant_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["RenameTenantRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["TenantView"];
                };
            };
            /** @description The request was refused */
            "4XX": {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
            /** @description The server failed */
            "5XX": {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
        };
    };
    freeze_tenant_api_v1_platform_tenants__tenant_id__freeze_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                tenant_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["PlatformFreezeRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["PlatformFreezeView"];
                };
            };
            /** @description The request was refused */
            "4XX": {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
            /** @description The server failed */
            "5XX": {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
        };
    };
    lock_tenant_api_v1_platform_tenants__tenant_id__lock_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                tenant_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            204: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description The request was refused */
            "4XX": {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
            /** @description The server failed */
            "5XX": {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
        };
    };
    get_offboarding_status_api_v1_platform_tenants__tenant_id__offboard_get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                tenant_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["OffboardingStatusView"];
                };
            };
            /** @description The request was refused */
            "4XX": {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
            /** @description The server failed */
            "5XX": {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
        };
    };
    initiate_offboarding_api_v1_platform_tenants__tenant_id__offboard_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                tenant_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            202: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["OffboardingStatusView"];
                };
            };
            /** @description The request was refused */
            "4XX": {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
            /** @description The server failed */
            "5XX": {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
        };
    };
    finalize_offboarding_api_v1_platform_tenants__tenant_id__offboard_finalize_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                tenant_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            204: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description The request was refused */
            "4XX": {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
            /** @description The server failed */
            "5XX": {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
        };
    };
    assign_org_admin_api_v1_platform_tenants__tenant_id__org_admins_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                tenant_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["AssignOrgAdminRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["UserRefView"];
                };
            };
            /** @description The request was refused */
            "4XX": {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
            /** @description The server failed */
            "5XX": {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
        };
    };
    unfreeze_tenant_api_v1_platform_tenants__tenant_id__unfreeze_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                tenant_id: string;
            };
            cookie?: never;
        };
        requestBody?: {
            content: {
                "application/json": components["schemas"]["PlatformUnfreezeRequest"] | null;
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["PlatformFreezeView"];
                };
            };
            /** @description The request was refused */
            "4XX": {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
            /** @description The server failed */
            "5XX": {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
        };
    };
    unlock_tenant_api_v1_platform_tenants__tenant_id__unlock_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                tenant_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            204: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description The request was refused */
            "4XX": {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
            /** @description The server failed */
            "5XX": {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
        };
    };
    unfreeze_platform_api_v1_platform_unfreeze_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["PlatformFreezeView"];
                };
            };
            /** @description The request was refused */
            "4XX": {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
            /** @description The server failed */
            "5XX": {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
        };
    };
    list_users_api_v1_platform_users_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["UserRefView"][];
                };
            };
            /** @description The request was refused */
            "4XX": {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
            /** @description The server failed */
            "5XX": {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
        };
    };
    check_unsubscribe_api_v1_public_unsubscribe__token__get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                token: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["UnsubscribeView"];
                };
            };
            /** @description The request was refused */
            "4XX": {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
            /** @description The server failed */
            "5XX": {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
        };
    };
    confirm_unsubscribe_api_v1_public_unsubscribe__token__post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                token: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["UnsubscribeView"];
                };
            };
            /** @description The request was refused */
            "4XX": {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
            /** @description The server failed */
            "5XX": {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
        };
    };
    ready_api_v1_ready_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ReadinessResponse"];
                };
            };
            /** @description The request was refused */
            "4XX": {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
            /** @description The server failed */
            "5XX": {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
        };
    };
    cancel_thread_api_v1_runs_threads__thread_id__cancel_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                thread_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["CancelResult"];
                };
            };
            /** @description The request was refused */
            "4XX": {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
            /** @description The server failed */
            "5XX": {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
        };
    };
    get_run_api_v1_runs__run_id__get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                run_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["RunView"];
                };
            };
            /** @description The request was refused */
            "4XX": {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
            /** @description The server failed */
            "5XX": {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
        };
    };
    get_timeline_api_v1_runs__run_id__timeline_get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                run_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["TimelineEvent"][];
                };
            };
            /** @description The request was refused */
            "4XX": {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
            /** @description The server failed */
            "5XX": {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
        };
    };
    get_run_usage_api_v1_runs__run_id__usage_get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                run_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["RunUsageView"];
                };
            };
            /** @description The request was refused */
            "4XX": {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
            /** @description The server failed */
            "5XX": {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
        };
    };
    list_artifacts_api_v1_studio_artifacts_get: {
        parameters: {
            query?: {
                /** @description Only this kind. */
                kind?: string | null;
                /** @description Only artifacts carrying this label. */
                label?: string | null;
                limit?: number;
                /** @description Opaque cursor from a previous page. */
                cursor?: string | null;
            };
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["Page_ArtifactView_"];
                };
            };
            /** @description The request was refused */
            "4XX": {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
            /** @description The server failed */
            "5XX": {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
        };
    };
    create_artifact_api_v1_studio_artifacts_post: {
        parameters: {
            query?: never;
            header?: {
                /** @description Optional. Retrying with the same key returns the first response instead of acting twice; reusing it for a different request, or another person's key, is a 409. */
                "Idempotency-Key"?: string | null;
            };
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["NewArtifact"];
            };
        };
        responses: {
            /** @description Successful Response */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ArtifactView"];
                };
            };
            /** @description The request was refused */
            "4XX": {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
            /** @description The server failed */
            "5XX": {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
        };
    };
    read_artifact_api_v1_studio_artifacts__artifact_id__get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                artifact_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ArtifactView"];
                };
            };
            /** @description The request was refused */
            "4XX": {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
            /** @description The server failed */
            "5XX": {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
        };
    };
    delete_artifact_api_v1_studio_artifacts__artifact_id__delete: {
        parameters: {
            query?: never;
            header?: {
                /** @description Required. The strong ETag of the version you read, for example "7". A stale or weak one is a 412; none, *, a list or a repeat is a 428. */
                "If-Match"?: string[] | null;
            };
            path: {
                artifact_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            204: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description The request was refused */
            "4XX": {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
            /** @description The server failed */
            "5XX": {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
        };
    };
    update_artifact_api_v1_studio_artifacts__artifact_id__patch: {
        parameters: {
            query?: never;
            header?: {
                /** @description Required. The strong ETag of the version you read, for example "7". A stale or weak one is a 412; none, *, a list or a repeat is a 428. */
                "If-Match"?: string[] | null;
            };
            path: {
                artifact_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ArtifactView"];
                };
            };
            /** @description The request was refused */
            "4XX": {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
            /** @description The server failed */
            "5XX": {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
        };
    };
    list_dependents_api_v1_studio_artifacts__artifact_id__dependents_get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                artifact_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["DependentsView"];
                };
            };
            /** @description The request was refused */
            "4XX": {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
            /** @description The server failed */
            "5XX": {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
        };
    };
    read_draft_api_v1_studio_artifacts__artifact_id__draft_get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                artifact_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ArtifactDraftView"];
                };
            };
            /** @description The request was refused */
            "4XX": {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
            /** @description The server failed */
            "5XX": {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
        };
    };
    save_draft_api_v1_studio_artifacts__artifact_id__draft_put: {
        parameters: {
            query?: never;
            header?: {
                /** @description Required. The strong ETag of the version you read, for example "7". A stale or weak one is a 412; none, *, a list or a repeat is a 428. */
                "If-Match"?: string[] | null;
            };
            path: {
                artifact_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["ArtifactDraftBody"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ArtifactDraftView"];
                };
            };
            /** @description The request was refused */
            "4XX": {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
            /** @description The server failed */
            "5XX": {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
        };
    };
    create_draft_api_v1_studio_artifacts__artifact_id__draft_post: {
        parameters: {
            query?: never;
            header?: {
                /** @description Optional. Retrying with the same key returns the first response instead of acting twice; reusing it for a different request, or another person's key, is a 409. */
                "Idempotency-Key"?: string | null;
                /** @description Required. The strong ETag of the version you read, for example "7". A stale or weak one is a 412; none, *, a list or a repeat is a 428. */
                "If-Match"?: string[] | null;
            };
            path: {
                artifact_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ArtifactDraftView"];
                };
            };
            /** @description The request was refused */
            "4XX": {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
            /** @description The server failed */
            "5XX": {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
        };
    };
    draft_dependencies_api_v1_studio_artifacts__artifact_id__draft_dependencies_get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                artifact_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ReferenceList"];
                };
            };
            /** @description The request was refused */
            "4XX": {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
            /** @description The server failed */
            "5XX": {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
        };
    };
    list_versions_api_v1_studio_artifacts__artifact_id__versions_get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                artifact_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["VersionList"];
                };
            };
            /** @description The request was refused */
            "4XX": {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
            /** @description The server failed */
            "5XX": {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
        };
    };
    read_version_api_v1_studio_artifacts__artifact_id__versions__version_no__get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                artifact_id: string;
                version_no: number;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["VersionView"];
                };
            };
            /** @description The request was refused */
            "4XX": {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
            /** @description The server failed */
            "5XX": {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
        };
    };
    catalog_api_v1_support_catalog_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["SupportScopeSetView"][];
                };
            };
            /** @description The request was refused */
            "4XX": {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
            /** @description The server failed */
            "5XX": {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
        };
    };
    list_grants_api_v1_support_grants_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["SupportGrantModel"][];
                };
            };
            /** @description The request was refused */
            "4XX": {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
            /** @description The server failed */
            "5XX": {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
        };
    };
    request_grant_api_v1_support_grants_post: {
        parameters: {
            query?: never;
            header?: {
                /** @description Optional. Retrying with the same key returns the first response instead of acting twice; reusing it for a different request, or another person's key, is a 409. */
                "Idempotency-Key"?: string | null;
            };
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["RequestSupportGrantBody"];
            };
        };
        responses: {
            /** @description Successful Response */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["SupportGrantModel"];
                };
            };
            /** @description The request was refused */
            "4XX": {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
            /** @description The server failed */
            "5XX": {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
        };
    };
    approve_grant_api_v1_support_grants__grant_id__approve_post: {
        parameters: {
            query?: never;
            header?: {
                /** @description Optional. Retrying with the same key returns the first response instead of acting twice; reusing it for a different request, or another person's key, is a 409. */
                "Idempotency-Key"?: string | null;
            };
            path: {
                grant_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["SupportGrantModel"];
                };
            };
            /** @description The request was refused */
            "4XX": {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
            /** @description The server failed */
            "5XX": {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
        };
    };
    reject_grant_api_v1_support_grants__grant_id__reject_post: {
        parameters: {
            query?: never;
            header?: {
                /** @description Optional. Retrying with the same key returns the first response instead of acting twice; reusing it for a different request, or another person's key, is a 409. */
                "Idempotency-Key"?: string | null;
            };
            path: {
                grant_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["RejectSupportGrantBody"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["SupportGrantModel"];
                };
            };
            /** @description The request was refused */
            "4XX": {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
            /** @description The server failed */
            "5XX": {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
        };
    };
    revoke_grant_api_v1_support_grants__grant_id__revoke_post: {
        parameters: {
            query?: never;
            header?: {
                /** @description Optional. Retrying with the same key returns the first response instead of acting twice; reusing it for a different request, or another person's key, is a 409. */
                "Idempotency-Key"?: string | null;
            };
            path: {
                grant_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["SupportGrantModel"];
                };
            };
            /** @description The request was refused */
            "4XX": {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
            /** @description The server failed */
            "5XX": {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
        };
    };
    my_grants_api_v1_support_my_grants_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["MySupportGrantModel"][];
                };
            };
            /** @description The request was refused */
            "4XX": {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
            /** @description The server failed */
            "5XX": {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
        };
    };
    get_usage_summary_api_v1_usage_summary_get: {
        parameters: {
            query?: {
                group_by?: "workspace" | "artifact" | "purpose";
                from?: string | null;
                to?: string | null;
                workspace_id?: string | null;
                artifact_kind?: ("agent" | "workflow") | null;
                artifact_id?: string | null;
            };
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["UsageSummaryView"];
                };
            };
            /** @description The request was refused */
            "4XX": {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
            /** @description The server failed */
            "5XX": {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
        };
    };
    list_work_items_api_v1_work_items_get: {
        parameters: {
            query?: {
                status?: ("open" | "in_progress" | "waiting_approval" | "waiting_timer" | "handed_off" | "done" | "failed" | "cancelled") | null;
                holder_kind?: ("digital_worker" | "person") | null;
                limit?: number;
                /** @description Opaque cursor from a previous page. */
                cursor?: string | null;
            };
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["Page_WorkItemView_"];
                };
            };
            /** @description The request was refused */
            "4XX": {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
            /** @description The server failed */
            "5XX": {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
        };
    };
    get_work_item_api_v1_work_items__item_id__get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                item_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["WorkItemView"];
                };
            };
            /** @description The request was refused */
            "4XX": {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
            /** @description The server failed */
            "5XX": {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
        };
    };
    complete_work_item_api_v1_work_items__item_id__complete_post: {
        parameters: {
            query?: never;
            header?: {
                /** @description Optional. Retrying with the same key returns the first response instead of acting twice; reusing it for a different request, or another person's key, is a 409. */
                "Idempotency-Key"?: string | null;
            };
            path: {
                item_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["WorkItemView"];
                };
            };
            /** @description The request was refused */
            "4XX": {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
            /** @description The server failed */
            "5XX": {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
        };
    };
    zalo_connect_api_v1_zalo_connect_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ZaloConnectView"];
                };
            };
            /** @description The request was refused */
            "4XX": {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
            /** @description The server failed */
            "5XX": {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
        };
    };
    zalo_disconnect_api_v1_zalo_disconnect_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            204: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description The request was refused */
            "4XX": {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
            /** @description The server failed */
            "5XX": {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
        };
    };
    zalo_status_api_v1_zalo_status_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ZaloStatusView"];
                };
            };
            /** @description The request was refused */
            "4XX": {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
            /** @description The server failed */
            "5XX": {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
        };
    };
    zalo_workspace_api_v1_zalo_workspace_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ZaloWorkspaceView"];
                };
            };
            /** @description The request was refused */
            "4XX": {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
            /** @description The server failed */
            "5XX": {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
        };
    };
    zalo_choose_workspace_api_v1_zalo_workspace_put: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["ZaloWorkspaceChoice"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ZaloWorkspaceView"];
                };
            };
            /** @description The request was refused */
            "4XX": {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
            /** @description The server failed */
            "5XX": {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
        };
    };
}
