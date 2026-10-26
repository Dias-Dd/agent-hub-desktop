"""User-owned system notification preferences; delivery checks the latest cache."""
import json
from .core import HubError, uid
DEFAULTS={'enabled':True,'when':'always','demo':True,'project':True,'attention':False}

def read(db):
    try:
        row=db.execute("SELECT value FROM settings WHERE key='notification_settings'").fetchone()
        value=json.loads(row[0]) if row else {}
        if not isinstance(value,dict):return dict(DEFAULTS)
        cfg=dict(DEFAULTS)
        for k,v in value.items():
            if k=='when' and v in ('always','background'):cfg[k]=v
            elif k in DEFAULTS and type(v) is bool:cfg[k]=v
        return cfg
    except (ValueError,TypeError):return dict(DEFAULTS)

def allowed(config,event,foreground=False):
    cfg={**DEFAULTS,**config}
    if event.get('kind')=='test':return True
    return bool(cfg['enabled'] and cfg.get(event.get('kind'),False) and (cfg['when']=='always' or not foreground))

def wording(kind,english=False):
    titles={'demo':('产品演示已完成','Product demo ready'),'project':('项目已完成','Project completed'),'attention':('项目需要处理','Project needs attention'),'test':('测试通知','Test notification')}
    return titles.get(kind,titles['attention'])[int(english)]

def action(hub,actor,operation='read',config=None):
    hub.require(actor,{'user'})
    if operation=='save':
        if not isinstance(config,dict) or set(config)!=set(DEFAULTS) or config['when'] not in ('always','background') or any(type(config[k]) is not bool for k in ('enabled','demo','project','attention')):raise HubError('通知配置无效')
        with hub.tx():
            hub.db.execute("INSERT OR REPLACE INTO settings VALUES('notification_settings',?)",(json.dumps(config),))
            hub.audit(actor,'notifications.configured',config)
    elif operation=='test':
        from .desktop_notifications import enqueue
        with hub.tx():enqueue(hub,'test:'+uid(),'test',None)
        return {'queued':True}
    elif operation!='read':raise HubError('未知通知设置操作')
    with hub.lock:return read(hub.db)
