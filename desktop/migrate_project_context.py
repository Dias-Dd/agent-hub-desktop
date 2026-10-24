"""Migrate and converge project context into the desktop application data directory.

Performs a read-only online backup from the live Hub database, sanitizes
and converges active task/message/execution states to prevent desktop worker race
conditions or token consumption, exports a bundled seed database, and merges
the full project history into %LOCALAPPDATA%\\AgentMessageHubDesktop\\data\\hub.sqlite3.
"""

import argparse
import json
from pathlib import Path
import sqlite3
import sys

TARGET_PROJECT_ID = "2481457293934dd183a2aa78f8776465"
DEFAULT_TARGET_DATA = Path(sys.platform.startswith('win') and Path.home() / 'AppData' / 'Local' or Path.home() / '.local' / 'share') / 'AgentMessageHubDesktop' / 'data'
ROOT_DIR = Path(__file__).resolve().parents[1]


def find_source_db(explicit_path=None):
    if explicit_path:
        p = Path(explicit_path).resolve()
        if p.is_file():
            return p
        raise FileNotFoundError(f"Explicit source database not found: {explicit_path}")

    # Check candidates for outer live Hub database
    candidates = [
        # Outer outputs/agent-message-hub/data/hub.sqlite3
        Path(__file__).resolve().parents[4] / "hub.sqlite3",
        Path(__file__).resolve().parents[5] / "data" / "hub.sqlite3",
        Path.cwd().parents[3] / "data" / "hub.sqlite3",
        Path.cwd().parents[4] / "data" / "hub.sqlite3",
        Path(r"C:\Users\ASUS\Documents\Codex\2026-10-17\referenced-chatgpt-conversation-this-is-an\outputs\agent-message-hub\data\hub.sqlite3"),
        # Bundled seed database in desktop/
        ROOT_DIR / "desktop" / "seed_context.sqlite3",
        Path(getattr(sys, "_MEIPASS", ROOT_DIR)) / "desktop" / "seed_context.sqlite3",
    ]
    for c in candidates:
        if c.is_file():
            return c.resolve()
    return None


def sanitize_and_converge(mem_conn):
    """Safely converge active execution states to prevent desktop worker race conditions."""
    with mem_conn:
        # 1. messages: converge active (pending, delivered, acknowledged, active) to completed
        mem_conn.execute("""
            UPDATE messages
            SET status = 'completed',
                result = COALESCE(result, '已导入桌面端历史展示'),
                lease = NULL
            WHERE status IN ('pending', 'delivered', 'acknowledged', 'active')
        """)
        mem_conn.execute("UPDATE messages SET lease = NULL WHERE lease IS NOT NULL")

        # 2. wakeups: mark all handled so desktop worker doesn't fire model executions
        try:
            mem_conn.execute("UPDATE wakeups SET status = 'handled' WHERE status != 'handled'")
        except sqlite3.OperationalError:
            pass

        # 3. workflow_events: mark all handled
        try:
            mem_conn.execute("UPDATE workflow_events SET status = 'handled' WHERE status != 'handled'")
        except sqlite3.OperationalError:
            pass

        # 3b. workflows: converge in-flight workflows to paused while preserving all history and reports
        try:
            wf_rows = mem_conn.execute("SELECT id, body FROM workflows").fetchall()
            for wf_id, wf_body in wf_rows:
                if wf_body:
                    try:
                        w_data = json.loads(wf_body)
                        if isinstance(w_data, dict):
                            if w_data.get('status') in ('active', 'running', 'needs_attention', 'blocked', 'executing'):
                                w_data['status'] = 'paused'
                                mem_conn.execute("UPDATE workflows SET body = ? WHERE id = ?", (json.dumps(w_data, ensure_ascii=False), wf_id))
                    except Exception:
                        pass
        except sqlite3.OperationalError:
            pass

        # 4. executions: converge running or non-terminal executions to completed
        try:
            mem_conn.execute("""
                UPDATE executions
                SET status = 'completed',
                    result = COALESCE(result, '外层已执行/桌面端只读展示')
                WHERE status NOT IN ('completed', 'failed', 'cancelled')
            """)
        except sqlite3.OperationalError:
            pass

        # 5. calls: mark running calls cancelled
        try:
            mem_conn.execute("""
                UPDATE calls
                SET status = 'cancelled',
                    result = COALESCE(result, '桌面端离线快照')
                WHERE status = 'running'
            """)
        except sqlite3.OperationalError:
            pass

        # 6. agents: reset status to offline and clear active task
        try:
            mem_conn.execute("UPDATE agents SET status = 'offline', active = NULL")
        except sqlite3.OperationalError:
            pass

        # 6b. tasks: converge assigned/working tasks to done so desktop worker does not re-dispatch
        try:
            mem_conn.execute("UPDATE tasks SET status = 'done', progress = 100 WHERE status IN ('assigned', 'working')")
        except sqlite3.OperationalError:
            pass

        # 6c. workflows: pause active/needs_attention workflows so desktop instance does not auto-patrol live workflows
        try:
            wf_rows = mem_conn.execute("SELECT id, body FROM workflows").fetchall()
            for wf_id, wf_body in wf_rows:
                try:
                    w = json.loads(wf_body)
                    if isinstance(w, dict) and w.get('status') in ('active', 'needs_attention'):
                        w['status'] = 'paused'
                        w['phase'] = 'paused'
                        w['next_inspection'] = None
                        w['report'] = '已从外层同步上下文（默认暂停自动巡检防双实例抢跑；在桌面端可随时恢复）'
                        mem_conn.execute("UPDATE workflows SET body = ? WHERE id = ?", (json.dumps(w, ensure_ascii=False), wf_id))
                except Exception:
                    pass
        except sqlite3.OperationalError:
            pass

        # 6d. planning_sessions: clear pending execution references
        try:
            ps_rows = mem_conn.execute("SELECT id, body FROM planning_sessions").fetchall()
            for ps_id, ps_body in ps_rows:
                try:
                    ps = json.loads(ps_body)
                    if isinstance(ps, dict) and (ps.get('pending') is not None or ps.get('state') == 'thinking'):
                        ps['pending'] = None
                        if ps.get('state') == 'thinking':
                            ps['state'] = 'draft'
                        mem_conn.execute("UPDATE planning_sessions SET body = ? WHERE id = ?", (json.dumps(ps, ensure_ascii=False), ps_id))
                except Exception:
                    pass
        except sqlite3.OperationalError:
            pass

        # 6e. sessions: clear provider CLI conversation IDs so desktop instance never collides with or kills outer live CLI sessions
        try:
            mem_conn.execute("DELETE FROM sessions")
        except sqlite3.OperationalError:
            pass

        # 7. settings: scrub any secret keys/tokens to prevent credential leakage
        try:
            settings_rows = mem_conn.execute("SELECT key, value FROM settings").fetchall()
            for k, val in settings_rows:
                k_lower = k.lower()
                if any(s in k_lower for s in ('key', 'secret', 'token', 'credential')):
                    mem_conn.execute("DELETE FROM settings WHERE key = ?", (k,))
                else:
                    try:
                        data = json.loads(val)
                        if isinstance(data, dict):
                            modified = False
                            for sub_k in list(data.keys()):
                                if any(s in sub_k.lower() for s in ('api_key', 'secret', 'token', 'access_key')):
                                    data[sub_k] = '***REDACTED***'
                                    modified = True
                            if modified:
                                mem_conn.execute("UPDATE settings SET value = ? WHERE key = ?", (json.dumps(data, ensure_ascii=False), k))
                    except Exception:
                        pass
        except sqlite3.OperationalError:
            pass

        # 8. backfill project_id for messages, tasks, calls and ensure TARGET_PROJECT_ID in hub_projects
        try:
            for table in ('tasks', 'messages', 'calls'):
                cols = [c[1] for c in mem_conn.execute(f"PRAGMA table_info({table})").fetchall()]
                if 'project_id' not in cols:
                    mem_conn.execute(f"ALTER TABLE {table} ADD COLUMN project_id TEXT")
            mem_conn.execute("UPDATE tasks SET project_id = ? WHERE project_id IS NULL", (TARGET_PROJECT_ID,))
            mem_conn.execute("UPDATE messages SET project_id = ? WHERE project_id IS NULL", (TARGET_PROJECT_ID,))
            mem_conn.execute("UPDATE calls SET project_id = ? WHERE project_id IS NULL", (TARGET_PROJECT_ID,))
            mem_conn.execute("UPDATE messages SET project_id = ? WHERE (sender='argon' AND recipient='user') OR (sender='user' AND recipient='argon')", (TARGET_PROJECT_ID,))
            mem_conn.execute("CREATE TABLE IF NOT EXISTS hub_projects(id TEXT PRIMARY KEY,name TEXT,cwd TEXT,created REAL)")
            mem_conn.execute("INSERT OR IGNORE INTO hub_projects VALUES(?,?,?,?)", (TARGET_PROJECT_ID, "当前项目 · agent-message-hub", "", 0.0))
        except sqlite3.OperationalError:
            pass


def merge_into_target(mem_conn, target_path):
    target_path = Path(target_path).resolve()
    target_path.parent.mkdir(parents=True, exist_ok=True)

    if not target_path.exists() or target_path.stat().st_size == 0:
        # Directly backup into target
        target_conn = sqlite3.connect(str(target_path))
        mem_conn.backup(target_conn)
        target_conn.close()
        return

    # Target already exists: open target connection and attach mem_conn via URI or iterate tables
    # Using python connection to target and copying rows
    target_conn = sqlite3.connect(str(target_path), isolation_level=None)
    target_conn.execute("PRAGMA busy_timeout=5000;")
    target_conn.execute("PRAGMA foreign_keys=OFF;")

    tables = [r[0] for r in mem_conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'").fetchall()]

    with target_conn:
        for tbl in tables:
            # Ensure table exists in target
            create_sql = mem_conn.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name=?", (tbl,)).fetchone()[0]
            target_create = create_sql.replace("CREATE TABLE", "CREATE TABLE IF NOT EXISTS", 1)
            target_conn.execute(target_create)

            # Determine matching columns
            cols_src = [c[1] for c in mem_conn.execute(f"PRAGMA table_info({tbl})").fetchall()]
            cols_tgt = [c[1] for c in target_conn.execute(f"PRAGMA table_info({tbl})").fetchall()]
            common_cols = [c for c in cols_src if c in cols_tgt]
            if not common_cols:
                continue

            col_names = ", ".join(f'"{c}"' for c in common_cols)
            placeholders = ", ".join("?" for _ in common_cols)
            insert_sql = f'INSERT OR REPLACE INTO "{tbl}" ({col_names}) VALUES ({placeholders})'

            rows = mem_conn.execute(f'SELECT {col_names} FROM "{tbl}"').fetchall()
            if rows:
                target_conn.executemany(insert_sql, rows)

    # Ensure target DB is also fully converged
    sanitize_and_converge(target_conn)
    target_conn.close()


def migrate(source_db=None, target_db=None, seed_path=None, seed_only=False):
    src_path = find_source_db(source_db)
    if not src_path:
        raise RuntimeError("No source database or seed database could be found.")

    print(f"Reading source DB: {src_path}")
    # Read-only online backup from source
    src_uri = f"file:{src_path.as_posix()}?mode=ro"
    src_conn = sqlite3.connect(src_uri, uri=True)
    mem_conn = sqlite3.connect(":memory:")
    src_conn.backup(mem_conn)
    src_conn.close()

    # Sanitize and converge active states
    sanitize_and_converge(mem_conn)

    # Export seed DB if requested / default
    if seed_path is None:
        seed_path = ROOT_DIR / "desktop" / "seed_context.sqlite3"
    seed_path = Path(seed_path).resolve()
    seed_path.parent.mkdir(parents=True, exist_ok=True)
    if seed_path.exists():
        try:
            seed_path.unlink()
        except OSError:
            pass
    print(f"Exporting sanitized seed database: {seed_path}")
    seed_conn = sqlite3.connect(str(seed_path))
    mem_conn.backup(seed_conn)
    seed_conn.close()

    if seed_only:
        print("Seed-only mode completed successfully.")
        return {"ok": True, "source": str(src_path), "seed": str(seed_path)}

    # Target merge
    if target_db is None:
        target_db = DEFAULT_TARGET_DATA / "hub.sqlite3"
    target_path = Path(target_db).resolve()
    print(f"Merging sanitized context into target DB: {target_path}")
    merge_into_target(mem_conn, target_path)

    # Verify target project presence
    check_conn = sqlite3.connect(f"file:{target_path.as_posix()}?mode=ro", uri=True)
    cur = check_conn.cursor()
    proj_count = cur.execute("SELECT count(*) FROM hub_projects WHERE id = ?", (TARGET_PROJECT_ID,)).fetchone()[0]
    total_projects = cur.execute("SELECT count(*) FROM hub_projects").fetchone()[0]
    total_messages = cur.execute("SELECT count(*) FROM messages").fetchone()[0]
    check_conn.close()

    print(f"Migration completed. Target projects: {total_projects}, target messages: {total_messages}, contains target project: {proj_count > 0}")
    return {
        "ok": True,
        "source": str(src_path),
        "seed": str(seed_path),
        "target": str(target_path),
        "target_project_present": proj_count > 0,
        "total_projects": total_projects,
        "total_messages": total_messages
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=None, help="Source hub.sqlite3 path")
    parser.add_argument("--target", type=Path, default=None, help="Target hub.sqlite3 path")
    parser.add_argument("--seed-path", type=Path, default=None, help="Seed database output path")
    parser.add_argument("--seed-only", action="store_true", help="Only produce seed_context.sqlite3 without modifying target")
    args = parser.parse_args(argv)

    try:
        res = migrate(source_db=args.source, target_db=args.target, seed_path=args.seed_path, seed_only=args.seed_only)
        print(json.dumps(res, indent=2, ensure_ascii=False))
        return 0
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
