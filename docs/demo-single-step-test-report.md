# Static demo single-call completion and independent reviewer defaults

- Static design-review workflows complete/publish with the first project_complete call, without confirmation or a folder link. DesignFlow.finish now asserts completed=true and design_review_ready=true on that first call and issues no second confirmation. Formal production retains two-step self-confirmation and the existing folder-link requirement.
- Shared independent_reviewer helper preserves a valid participant choice, otherwise chooses the first allowed non-manager member, or None when no member exists. Applied to planning defaults, workflow start/roster repair, design setup, manager switches, deleted-member fallbacks and active legacy workflow defaults. Completed workflow history is not rewritten.
- UI default options track checked participants and exclude manager; editing project settings refreshes reviewer choices after member selection. Empty roster shows an unassigned choice. Suggestions do not create check tasks or completion gates.
- Manager instructions and MCP descriptions distinguish single-call demos from two-call production.

Verification: independent_reviewer 3; designs 13; required_folder_link 7; dynamic_manager_delete 26; manager_identity_audit 29; manager_force_stop_patrol 12; manager_queue 10; automation 26 passed. Reviewer browser interaction passed (member selection/removal/no-manager fallback). Mandatory manager-layout, reading, nine-agent browser checks passed; design browser review and actual reload passed at three sizes. All local fake-provider/browser checks, no live inference or project mutation.

Backup: ../agent-message-hub-before-demo-single-step-app.zip. Immutable release, running Hub not restarted.

Packaged startup smoke passed (16 assets, native desktop and VM helper present).
