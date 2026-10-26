import json
from pathlib import Path
from .runtime import execute, configuration, probe, configure

def setup_status(registry,connection):
    from .runtime import node
    node()
    try:configuration(registry,connection)
    except Exception as e:return {'state':'login','message':str(e)}
    return {'state':'ready','message':'API 配置已保存；请使用接入测试验证模型权限。'}
