"""Resolve the implementation actually loaded by the public module ABI."""
import importlib
from hub.harness_adapters import prepare_layout
from hub.module_loader import load

def implementation(hub,kind):
 prepare_layout(hub.directory)
 entry=load(hub.directory/'adapters'/'builtin'/kind)[0]
 return importlib.import_module(entry.__package__+'.runtime')
