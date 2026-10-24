import argparse
import json
import os
from .connectors import CodexProbe, antigravity_probe, DeepSeek
from .core import HubError

def main():
    p=argparse.ArgumentParser();p.add_argument('--provider',choices=['openai','antigravity','deepseek'],required=True)
    a=p.parse_args()
    if a.provider=='openai':result=CodexProbe().run()
    elif a.provider=='antigravity':result=antigravity_probe()
    else:
        try:result={'models':DeepSeek().models(),'inference_tested':False}
        except HubError as e:result={'error':str(e),'inference_tested':False}
    print(json.dumps(result,ensure_ascii=False,indent=2))

if __name__=='__main__':main()
