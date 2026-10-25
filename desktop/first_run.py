"""User-only first-run state, shared by the native Mac guide and HTTP service."""
import json
import time
from .ui_preferences import language
from hub.core import HubError


def action(hub, actor, operation='status', skip_vm=True):
    hub.require(actor, {'user'})
    path=hub.directory/'macos-onboarding.completed.json'
    if operation=='status':
        try:
            value=json.loads(path.read_text(encoding='utf8'))
            completed=isinstance(value,dict) and value.get('version') in (1,2) and isinstance(value.get('completed_at'),(int,float))
        except (OSError,ValueError):completed=False
        return {'needed':not completed,'data_directory':str(hub.directory.resolve()),
                'language':language(hub.directory)}
    if operation!='complete' or type(skip_vm) is not bool:raise HubError('首次配置操作无效')
    from hub.vm_bridge import VmBridge
    if not skip_vm and not VmBridge(hub.directory).status().get('connected'):
        raise HubError('虚拟机尚未验证连接，可以选择稍后配置')
    value={'version':2,'completed_at':time.time(),'vm_skipped':skip_vm}
    temporary=path.with_suffix('.tmp');temporary.write_text(json.dumps(value),encoding='utf8');temporary.replace(path)
    with hub.tx():hub.audit(actor,'desktop.onboarding_completed',value)
    return {'completed':True,**value}
