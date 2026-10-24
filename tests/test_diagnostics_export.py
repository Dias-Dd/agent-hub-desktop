import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
import zipfile
from desktop.export_diagnostics import export


class Diagnostics(unittest.TestCase):
    def test_live_wal_snapshot_redacts_credentials_without_modifying_database(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            db = sqlite3.connect(root / 'hub.sqlite3')
            db.execute('PRAGMA journal_mode=WAL')
            db.execute('CREATE TABLE settings(key TEXT,value TEXT)')
            db.execute('CREATE TABLE executions(id TEXT,status TEXT,result TEXT)')
            db.execute('INSERT INTO settings VALUES(?,?)', ('api_key', 'private-value'))
            db.execute('INSERT INTO executions VALUES(?,?,?)', ('run', 'running', json.dumps({'message':'stuck token-value-secret-123456','authorization':'private'})))
            db.commit()
            (root / 'credentials.json').write_text(json.dumps({'user':'token-value-secret-123456'}))
            path = export(root, root / 'report.zip')
            with zipfile.ZipFile(path) as report:
                raw = '\n'.join(report.read(x).decode() for x in report.namelist())
                self.assertNotIn('token-value-secret-123456', raw)
                self.assertNotIn('private-value', raw)
                self.assertNotIn('credentials.json', report.namelist())
                self.assertEqual(json.loads(report.read('database/executions.json'))[0]['status'], 'running')
            self.assertEqual(db.execute('SELECT status FROM executions').fetchone()[0], 'running')
            db.close()
