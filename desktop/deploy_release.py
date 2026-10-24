"""Publish immutable onedir releases without touching a running executable path."""
import hashlib,shutil,uuid
from pathlib import Path

def digest(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def publish(source,target):
 source=Path(source);target=Path(target);target.mkdir(parents=True,exist_ok=True)
 exe=source/'AgentMessageHubDesktop.exe'
 for folder in source.glob('_runtime-*'):
  dest=target/folder.name
  if dest.exists():
   incoming={str(p.relative_to(folder)):digest(p) for p in folder.rglob('*') if p.is_file()}
   existing={str(p.relative_to(dest)):digest(p) for p in dest.rglob('*') if p.is_file()}
   if incoming!=existing:raise RuntimeError('Runtime directory already exists with different contents; rebuild with a new immutable runtime ID.')
  else:shutil.copytree(folder,dest)
 release=target/('AgentMessageHubDesktop-'+digest(exe)[:12]+'.exe')
 if release.exists():
  if digest(release)!=digest(exe):raise RuntimeError('Release filename collision')
 else:
  temp=release.with_suffix('.'+uuid.uuid4().hex+'.tmp');shutil.copy2(exe,temp);temp.replace(release)
 # Never rename/replace AgentMessageHubDesktop.exe here. Existing processes may
 # reopen that exact path using archive offsets cached before an update.
 companion=source/'AgentHubMcp.exe'
 if companion.is_file():
  destination=target/release.name.replace('AgentMessageHubDesktop','AgentHubMcp')
  if not destination.exists():shutil.copy2(companion,destination)
  elif digest(destination)!=digest(companion):raise RuntimeError('MCP companion collision')
 return release
