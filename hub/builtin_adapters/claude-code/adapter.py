from hub.module_sdk import runtime_view
from . import config


def execute(host,run):
    from .runtime import execute as run_cli
    return run_cli(runtime_view(host,provider='claude-code'),run)


def probe(registry,connection):
    return config.catalog(connection)


def setup_status(registry,connection):
    return config.inspect(connection)


def setup_login(registry,connection):
    from hub.builtin_adapters._shared.setup import login
    return login(registry,connection,'claude-code',{'login_args':['auth','login'],'terminal':True})
