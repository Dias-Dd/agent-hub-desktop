"""Read-only support export; can run independently while the workspace is stuck."""
import argparse
import datetime
import json
import os
from pathlib import Path
import platform
import re
import sqlite3
import tempfile
import zipfile

SECRET = re.compile(r'(?i)(token|password|secret|authorization|api.?key|credential)')


def sanitize(value, secrets=()):
    if isinstance(value, dict):
        if isinstance(value.get('key'), str) and SECRET.search(value['key']):
            return {**value, 'value': '[redacted]'}
        return {k: ('[redacted]' if SECRET.search(k) else sanitize(v, secrets)) for k, v in value.items()}
    if isinstance(value, list):
        return [sanitize(x, secrets) for x in value]
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except (ValueError, TypeError):
            parsed = None
        if isinstance(parsed, (dict, list)):
            return sanitize(parsed, secrets)
        for secret in secrets:
            value = value.replace(secret, '[redacted]')
        value = re.sub(r'(?i)Bearer\s+[^\s"\x27]+', 'Bearer [redacted]', value)
        return re.sub(r'\bsk-[A-Za-z0-9_-]{12,}', '[redacted]', value)
    return value


def export(data, destination):
    data = Path(data).resolve()
    database = data / 'hub.sqlite3'
    if not database.is_file():
        raise FileNotFoundError(f'Cannot find application database: {database}')
    secrets = []
    # Used only as a redaction dictionary; credentials are never added to the ZIP.
    for name in ('credentials.json', 'tokens.json'):
        path = data / name
        if path.is_file():
            try:
                def collect(v):
                    if isinstance(v, dict):
                        for item in v.values(): collect(item)
                    elif isinstance(v, list):
                        for item in v: collect(item)
                    elif isinstance(v, str) and len(v) >= 12: secrets.append(v)
                collect(json.loads(path.read_text(encoding='utf-8-sig')))
            except (ValueError, OSError): pass
    destination = Path(destination).resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as folder:
        source = sqlite3.connect(database.as_uri() + '?mode=ro', uri=True, timeout=10)
        snapshot = sqlite3.connect(str(Path(folder) / 'snapshot.sqlite3'))
        try:
            source.backup(snapshot, pages=128, sleep=.05)
            snapshot.row_factory = sqlite3.Row
            tables = [r[0] for r in snapshot.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
            with zipfile.ZipFile(destination, 'w', zipfile.ZIP_DEFLATED) as bundle:
                bundle.writestr('environment.json', json.dumps({'time': datetime.datetime.now().astimezone().isoformat(), 'platform': platform.platform(), 'data_directory': str(data), 'format': 1}, ensure_ascii=False, indent=2))
                for table in tables:
                    if SECRET.search(table): continue
                    quoted = '"' + table.replace('"', '""') + '"'
                    rows = [sanitize(dict(r), secrets) for r in snapshot.execute('SELECT * FROM ' + quoted)]
                    bundle.writestr('database/' + table + '.json', json.dumps(rows, ensure_ascii=False, indent=2))
                for relative in ('vm-bridge/status.json', 'ui-preferences.json', 'first-run.json'):
                    path = data / relative
                    if path.is_file():
                        try: bundle.writestr(relative, json.dumps(sanitize(json.loads(path.read_text(encoding='utf-8-sig')), secrets), ensure_ascii=False, indent=2))
                        except (OSError, ValueError): pass
                bundle.writestr('README.txt', 'Diagnostic snapshot: messages, execution records, workflow state and settings. Credentials and project source files are excluded. Review the archive before sharing; conversation content and local paths are included. The running application was not modified.\n')
        finally:
            snapshot.close()
            source.close()
    return destination


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--data', default=str(Path(os.environ.get('LOCALAPPDATA', str(Path.home()))) / 'AgentMessageHubDesktop/data'))
    parser.add_argument('--output', default=str(Path.home() / 'Desktop' / ('AgentHub-diagnostics-' + datetime.datetime.now().strftime('%Y%m%d-%H%M%S') + '.zip')))
    parser.add_argument('--quiet', action='store_true', help='Suppress completion dialog')
    args = parser.parse_args()
    try:
        path = export(args.data, args.output)
        print(f'Diagnostic archive / 诊断包: {path}')
        if os.name == 'nt' and not args.quiet:
            import ctypes
            ctypes.windll.user32.MessageBoxW(None, str(path), 'Agent Hub · Diagnostics / 诊断包已导出', 0)
        return 0
    except Exception as exc:
        if os.name == 'nt' and not args.quiet:
            import ctypes
            ctypes.windll.user32.MessageBoxW(None, str(exc), 'Agent Hub · Export failed', 16)
        print(str(exc))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
