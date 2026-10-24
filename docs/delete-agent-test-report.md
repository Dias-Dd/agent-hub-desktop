# Agent deletion fix

Deleting an unchanged identity no longer revalidates obsolete model/effort catalogue entries. New or edited configurations retain validation. Busy-agent and active-manager checks, project roster cleanup, history and notifications remain unchanged.

Validation: dynamic-manager/deletion suite 26 passed; quota/roster suite 16 passed; packaged smoke ok (16 assets, native and VM helper available). No live model calls or project changes.
