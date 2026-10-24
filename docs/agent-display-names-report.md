# Agent display names

Live operation initial rendering and streaming updates now resolve agent profile names rather than internal IDs. Manager headers, live sender, chat metadata, artifact sender and pending notices use the same name resolver. Dispatch identities, provider sessions and message bodies are unchanged. Missing generated IDs use an Agent label until names arrive.

Verified custom agent-a5e4a441b5 as Gemini Flash 1 in actual rendered operation and chat footer. Agent name browser, manager layout, reading browser and nine browser checks pass. Existing live browser selection fixture still fails in all three sizes; verified identical failures against unmodified pre-change assets, not reported as passing.

Verified current running extracted asset hashes against backup before copying only changed UI assets. No service restart or agent interruption. Refresh panel to load names. Desktop executable and source archive also updated.
