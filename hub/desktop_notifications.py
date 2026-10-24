"""Durable completion events, committed with the state transition."""
import time

def enqueue(hub,ident,kind,project):
    # Caller holds the same transaction as the completed workflow/demo save.
    hub.db.execute('CREATE TABLE IF NOT EXISTS desktop_notifications(id TEXT PRIMARY KEY,kind TEXT,project_id TEXT,created REAL)')
    hub.db.execute('INSERT OR IGNORE INTO desktop_notifications VALUES(?,?,?,?)',(ident,kind,project,time.time()))
