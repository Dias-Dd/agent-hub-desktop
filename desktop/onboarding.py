"""Separate first-run application; its only shared host is configuration code."""
import argparse
import json
import os
from pathlib import Path
import queue
import subprocess
import sys
import threading
import tkinter as tk
from tkinter import ttk, messagebox

if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from desktop.onboarding_service import SetupService

DEFAULT_DATA=Path(os.environ.get('LOCALAPPDATA',Path.home()))/'AgentMessageHubDesktop'/'data'


def main_executable():
    root=Path(sys.executable).parent if getattr(sys,'frozen',False) else Path(__file__).resolve().parent/'installer-stage'
    manifest=json.loads((root/'installation.json').read_text(encoding='utf-8'))
    relative=Path(manifest['main'])
    target=(root/relative).resolve()
    if relative.is_absolute() or not target.is_relative_to(root.resolve()) or target.suffix.lower()!='.exe' or not target.is_file():
        raise RuntimeError('安装目录缺少主程序，请重新安装 Agent Hub。')
    return target


class Wizard:
    def __init__(self, root, service, language=None):
        self.root=root;self.service=service;self.step=0;self.finished=False
        from desktop.ui_preferences import language as saved_language
        self.language=saved_language(service.directory,language or 'zh-CN');self.status_source='';self.translating=False
        self.skip_agents=True;self.skip_vm=True;self.manager='';self.pending=False
        self.events=queue.Queue();self.connections=[];self.catalog=[];self.selected_connection=''
        self.worker=None;self.closing=False
        root.title('Agent Hub · 初次配置');root.geometry('860x690');root.minsize(640,540)
        icon=Path(getattr(sys,'_MEIPASS',Path(__file__).resolve().parents[1]))/'desktop/app.ico'
        if icon.is_file():root.iconbitmap(default=str(icon))
        root.configure(bg='#f7f8f8')
        style=ttk.Style(root);style.theme_use('clam')
        style.configure('.',font=('Microsoft YaHei UI',10),background='#f7f8f8',foreground='#26312f')
        style.configure('TButton',padding=(14,8),background='#ffffff',borderwidth=1)
        style.map('TButton',background=[('active','#e7efed'),('pressed','#d8e7e3')])
        style.configure('Accent.TButton',background='#087d70',foreground='white')
        style.map('Accent.TButton',background=[('active','#06685e')])
        style.configure('Title.TLabel',font=('Microsoft YaHei UI',21,'bold'))
        style.configure('Heading.TLabel',font=('Microsoft YaHei UI',12,'bold'))
        self.header=ttk.Frame(root,padding=(28,20,28,14));self.header.pack(fill='x')
        ttk.Label(self.header,text='AGENT HUB',foreground='#087d70').pack(anchor='w')
        self.title=ttk.Label(self.header,style='Title.TLabel');self.title.pack(anchor='w',pady=(8,0))
        self.progress=ttk.Label(self.header);self.progress.pack(anchor='w',pady=(8,0))
        self.language_box=ttk.Combobox(self.header,state='readonly',values=['简体中文','English'],width=14)
        self.language_box.set('English' if self.language=='en' else '简体中文');self.language_box.pack(anchor='e')
        self.language_box.bind('<<ComboboxSelected>>',lambda event:self.change_language('en' if self.language_box.current()==1 else 'zh-CN'))
        ttk.Separator(root).pack(fill='x',padx=28)
        container=ttk.Frame(root);container.pack(fill='both',expand=True,padx=28,pady=12)
        self.canvas=tk.Canvas(container,bg='#f7f8f8',highlightthickness=0,height=1)
        scrollbar=ttk.Scrollbar(container,orient='vertical',command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side='right',fill='y');self.canvas.pack(side='left',fill='both',expand=True)
        self.body=ttk.Frame(self.canvas,padding=(1,4,14,12));window=self.canvas.create_window((0,0),window=self.body,anchor='nw')
        self.body.bind('<Configure>',lambda e:self.canvas.configure(scrollregion=self.canvas.bbox('all')))
        self.canvas.bind('<Configure>',lambda e:self.canvas.itemconfigure(window,width=e.width))
        root.bind_all('<MouseWheel>',self.wheel)
        self.status=tk.StringVar();self.status_label=ttk.Label(root,textvariable=self.status,wraplength=760,padding=(28,8));self.status_label.pack(fill='x')
        self.status.trace_add('write',self.translate_status)
        root.bind('<Configure>',self.reflow)
        self.footer=ttk.Frame(root,padding=(28,10,28,20));self.footer.pack(fill='x')
        # Reserve actions before the expanding viewport, including high-DPI Tk.
        container.pack_forget();self.status_label.pack_forget();self.footer.pack_forget()
        self.footer.pack(side='bottom',fill='x');self.status_label.pack(side='bottom',fill='x')
        container.pack(fill='both',expand=True,padx=28,pady=12)
        root.protocol('WM_DELETE_WINDOW',self.close)
        root.after(75,self.drain);self.show(0)

    def t(self,source):
        from desktop.localization import translate
        return translate(source,self.language)

    def translate_status(self,*args):
        if self.translating:return
        self.status_source=self.status.get();self.translating=True
        try:self.status.set(self.t(self.status_source))
        finally:self.translating=False

    def localize(self):
        self.root.title(self.t('Agent Hub · 初次配置'))
        def visit(parent):
            for widget in parent.winfo_children():
                if isinstance(widget,(ttk.Label,ttk.Button,ttk.Checkbutton)) and widget!=self.status_label:
                    current=str(widget.cget('text'))
                    previous=getattr(widget,'_translation',None)
                    source=previous[0] if previous and current==previous[1] else current
                    output=self.t(source);widget._translation=(source,output)
                    if output!=current:widget.configure(text=output)
                visit(widget)
        visit(self.root)

    def change_language(self,value):
        from desktop.ui_preferences import save_language
        self.language=value;save_language(self.service.directory,value);self.localize()
        self.translating=True
        try:self.status.set(self.t(self.status_source))
        finally:self.translating=False

    def reflow(self,event):
        if event.widget!=self.root:return
        self.status_label.configure(wraplength=max(400,event.width-60))
        for widget in self.body.winfo_children():
            if isinstance(widget,ttk.Label):widget.configure(wraplength=max(400,event.width-90))
        if self.step==1 and hasattr(self,'provider_actions') and self.provider_actions.winfo_exists():
            for button in self.provider_actions.winfo_children():button.pack_configure(side='top' if event.width<780 else 'left')

    def wheel(self,event):
        if self.canvas.bbox('all') and self.canvas.bbox('all')[3]>self.canvas.winfo_height():self.canvas.yview_scroll(int(-event.delta/120),'units')

    def close(self):
        if self.pending:
            self.status.set('正在处理连接，请稍候完成后关闭。');return
        self.closing=True;self.root.destroy()

    def drain(self):
        try:
            while True:
                callback,result,error=self.events.get_nowait();self.pending=False
                for button in self.disabled:
                    if button.winfo_exists():button.configure(state='normal')
                if error:self.status.set(str(error))
                else:
                    self.status.set('');callback(result);self.localize()
        except queue.Empty:pass
        if not self.closing:self.root.after(75,self.drain)

    def background(self,operation,callback):
        if self.pending:return
        self.pending=True;self.status.set('正在处理，请稍候…')
        self.disabled=[]
        def collect(parent):
            for widget in parent.winfo_children():
                if isinstance(widget,ttk.Button):self.disabled.append(widget);widget.configure(state='disabled')
                collect(widget)
        collect(self.body);collect(self.footer)
        def work():
            try:result=operation();self.events.put((callback,result,None))
            except Exception as error:self.events.put((callback,None,error))
        self.worker=threading.Thread(target=work,daemon=True);self.worker.start()

    def label(self,text,heading=False):
        widget=ttk.Label(self.body,text=text,wraplength=max(500,self.canvas.winfo_width()-35),justify='left',style='Heading.TLabel' if heading else 'TLabel')
        widget.pack(anchor='w',fill='x',pady=(4,10));return widget

    def button(self,text,command,parent=None,accent=False,side=None):
        widget=ttk.Button(parent or self.body,text=text,command=command,style='Accent.TButton' if accent else 'TButton')
        widget.pack(side=side or 'top',anchor='w',pady=5,padx=(0,8));return widget

    def show(self,step):
        self.step=step
        for parent in (self.body,self.footer):
            for widget in parent.winfo_children():widget.destroy()
        self.status.set('');self.canvas.yview_moveto(0)
        titles=['让工作台准备就绪','接入你的 Agent','指定项目经理','连接虚拟机','账号与连接设置','准备完成']
        self.title.configure(text=titles[step]);self.progress.configure(text=f'{step+1} / 6  ·  Agent 接入  →  经理  →  虚拟机')
        if step>0:self.button('上一步',lambda:self.show(step-1 if step!=3 or not self.skip_agents else 1),self.footer,side='left')
        getattr(self,'page_'+str(step))()
        self.localize()

    def next(self,label,step):self.button(label,lambda:self.show(step),self.footer,True,'right')

    def page_0(self):
        self.label('使用你自己的模型账号、订阅或 API。接入后，选择一位经理来统筹项目。',True)
        self.label('这份引导独立于工作台运行。配置过程中不会启动 Agent 任务，也不会发送付费推理请求。')
        self.label('虚拟机通过 Windows Hyper‑V 连接。没有准备好也没关系，Agent 和虚拟机都可以跳过，稍后从开始菜单打开“Agent Hub 配置引导”继续。')
        self.next('开始配置',1)

    def page_1(self):
        self.connections=self.service.connections()
        self.label('选择 Harness 或 API 接入。自定义模块也会在这里出现。')
        self.provider=ttk.Combobox(self.body,state='readonly',values=[c['name'] for c in self.connections]);self.provider.pack(fill='x',pady=6)
        index=next((i for i,c in enumerate(self.connections) if c['id']==self.selected_connection),0)
        self.provider.current(index);self.provider.bind('<<ComboboxSelected>>',lambda e:self.change_provider())
        self.info=ttk.Label(self.body,wraplength=720,justify='left');self.info.pack(fill='x',pady=10)
        row=ttk.Frame(self.body);row.pack(fill='x');self.provider_actions=row
        self.button('官网 / 安装说明',self.website,row,side='left')
        self.button('打开登录界面',lambda:self.background(lambda:self.service.open_login(self.connection()['id']),lambda r:self.status.set('请在官方界面完成登录，然后重新检查。')),row,side='left')
        self.button('检查登录 / 读取模型',self.detect,row,side='left')
        self.button('配置 API 环境变量',self.service.open_environment)
        self.keyrow=ttk.Frame(self.body)
        self.dskey=tk.StringVar()
        ttk.Entry(self.keyrow,textvariable=self.dskey,show='●').pack(side='left',fill='x',expand=True)
        def save_key():
            key=self.dskey.get();self.dskey.set('')
            self.background(lambda:self.service.save_deepseek_key(key),lambda r:self.status.set('DeepSeek 凭据已加密保存，请再次检查。'))
        self.button('保存 DeepSeek 凭据',save_key,self.keyrow,side='left')
        self.manual=tk.BooleanVar(value=False)
        ttk.Checkbutton(self.body,text='已在官方界面确认登录（仅用于没有登录检测接口的接入）',variable=self.manual).pack(anchor='w',pady=6)
        self.models=ttk.Combobox(self.body,state='readonly');self.models.pack(fill='x',pady=6)
        self.label('Agent 名称（留空则自动命名）')
        self.name=tk.StringVar();ttk.Entry(self.body,textvariable=self.name).pack(fill='x',pady=6)
        self.consent=tk.BooleanVar(value=False)
        ttk.Checkbutton(self.body,text='允许此接入执行任务；了解所选权限及提供商费用',variable=self.consent).pack(anchor='w',pady=6)
        self.button('添加 Agent',self.add,accent=True)
        self.added=ttk.Label(self.body,wraplength=720);self.added.pack(fill='x',pady=8)
        self.update_added();self.change_provider()
        if self.root.winfo_width()<780:
            for button in row.winfo_children():button.pack_configure(side='top')
        self.button('暂时跳过 Agent',self.skip_agent_flow,self.footer,side='right')
        self.button('选择经理',self.choose_manager,self.footer,True,'right')

    def connection(self):return self.connections[self.provider.current()]
    def change_provider(self):
        c=self.connection();self.selected_connection=c['id'];self.catalog=[];self.models.configure(values=[]);self.models.set('');self.name.set('');self.manual.set(False);self.consent.set(False)
        self.dskey.set('')
        if c['setup'].get('requires_api_key'):self.keyrow.pack(fill='x',pady=4,after=self.info)
        else:self.keyrow.pack_forget()
        spec=c['setup'];self.info.configure(text=('已检测到本机接入。' if c['installed'] else '本机未安装，请先打开官网安装，再点击检查。')+'\n'+spec.get('note','此模块可声明 setup_status / setup_login 来接入登录流程。')+'\n执行权限：'+('工作区访问' if c.get('permission')=='workspace' else '完全访问')+' · 工作目录：'+c['cwd'])
        self.localize()
    def website(self):
        url=self.connection()['setup'].get('website')
        if url:self.service.open_url(url)
        else:self.status.set('这个自定义模块尚未提供官网链接，请参考模块作者的说明。')
    def detect(self):
        c=self.connection();confirmed=self.manual.get()
        self.background(lambda:self.service.probe(c['id'],confirmed),self.detected)
    def detected(self,result):
        if result.get('login_required'):self.status.set(result['message']+' 完成后请再次检查。');return
        self.catalog=result.get('models',[]);self.models.configure(values=[m.get('name',m['id']) for m in self.catalog])
        if self.catalog:self.models.current(0)
        self.status.set(f'已读取 {len(self.catalog)} 个模型。目录可读不代表账号一定拥有全部模型权限。')
    def add(self):
        if self.models.current()<0:self.status.set('请先读取并选择模型。');return
        c=self.connection();model=self.catalog[self.models.current()]['id'];name=self.name.get();consent=self.consent.get()
        self.background(lambda:self.service.add_agent(c['id'],model,name,consent),lambda r:self.update_added())
    def update_added(self):self.added.configure(text='已接入：'+('、'.join(a['name'] for a in self.service.agents()) or '暂无'))
    def skip_agent_flow(self):self.skip_agents=True;self.manager='';self.show(3)
    def choose_manager(self):
        if not self.service.agents():self.status.set('请至少添加一位 Agent，或选择跳过。');return
        self.skip_agents=False;self.show(2)

    def page_2(self):
        self.label('选择一位经理。经理负责拆分任务、协调成员和汇报项目进度。',True)
        self.manager_agents=self.service.agents()
        self.manager_box=ttk.Combobox(self.body,state='readonly',values=[a['name']+' · '+a['model'] for a in self.manager_agents]);self.manager_box.pack(fill='x',pady=12)
        if self.manager_agents:self.manager_box.current(next((i for i,a in enumerate(self.manager_agents) if a['id']==self.manager),0))
        def proceed():
            if self.manager_box.current()<0:self.status.set('请选择经理。');return
            self.manager=self.manager_agents[self.manager_box.current()]['id'];self.show(3)
        self.button('继续',proceed,self.footer,True,'right')

    def page_3(self):
        installed=self.service.hyperv()['installed']
        self.label('使用 Hyper‑V 创建并启动一台 Windows 虚拟机。',True)
        self.label('已检测到 Hyper‑V 管理工具。' if installed else '尚未检测到 Hyper‑V 管理工具。打开“Windows 功能”，勾选 Hyper‑V 平台及 Hyper‑V 管理工具，按提示重启电脑后重新打开引导。')
        self.label('Windows 家庭版不提供 Hyper‑V。需要支持 Hyper‑V 的系统版本、硬件虚拟化和管理员权限；可先跳过。')
        self.button('打开 Hyper‑V 管理器' if installed else '打开 Windows 功能',self.service.open_hyperv,accent=True)
        self.button('查看微软官方安装指引',lambda:self.service.open_url('https://learn.microsoft.com/en-us/windows-server/virtualization/hyper-v/get-started/Install-Hyper-V'))
        self.label('在 Hyper‑V 管理器中：\n1. 新建第 2 代虚拟机，分配内存、网络和虚拟磁盘。\n2. 挂载 Windows 安装镜像并完成系统安装。\n3. 启动虚拟机，为来宾系统设置账号和密码（不是 PIN）。\n4. 返回引导，继续配置账号与连接。')
        self.button('重新检测',lambda:self.show(3))
        self.button('暂时跳过虚拟机',self.skip_vm_flow,self.footer,side='right')
        self.next('账号与连接设置',4)

    def skip_vm_flow(self):self.skip_vm=True;self.show(5)

    def page_4(self):
        self.label('选择虚拟机并填写来宾系统账号。连接时 Windows 可能会要求管理员授权。')
        self.vms=ttk.Combobox(self.body);self.vms.pack(fill='x',pady=6)
        self.button('读取虚拟机列表',self.list_vms)
        self.label('来宾账号（例如 VM\用户名 或 用户名）')
        self.user=tk.StringVar();ttk.Entry(self.body,textvariable=self.user).pack(fill='x',pady=4)
        self.label('来宾密码')
        self.password=tk.StringVar();ttk.Entry(self.body,textvariable=self.password,show='●').pack(fill='x',pady=4)
        self.remember=tk.BooleanVar(value=True);self.unattended=tk.BooleanVar(value=False)
        ttk.Checkbutton(self.body,text='记住连接凭据（Windows 加密，仅当前用户可用）',variable=self.remember).pack(anchor='w',pady=6)
        ttk.Checkbutton(self.body,text='配置无人值守：来宾自动登录、解锁及不休眠',variable=self.unattended).pack(anchor='w',pady=6)
        self.label('无人值守会修改来宾系统的登录与电源设置；不勾选时只建立连接。')
        self.button('连接并验证',self.connect_vm,accent=True)
        saved=self.service.vm.saved_connections()
        if saved:
            self.saved=ttk.Combobox(self.body,state='readonly',values=[x.get('vm','') for x in saved]);self.saved.pack(fill='x',pady=6);self.saved.current(0)
            def saved_connect():
                vm=self.saved.get()
                self.background(lambda:self.vm_job('connect_saved',vm_name=vm),self.connected)
            self.button('使用已保存的连接',saved_connect)
        self.button('暂时跳过虚拟机',self.skip_vm_flow,self.footer,side='right')
        self.button('继续',self.vm_continue,self.footer,True,'right')

    def vm_job(self,action,**kwargs):
        import time
        queued=self.service.vm.control(action=action,**kwargs)
        if 'request_id' not in queued:return queued
        for _ in range(515):
            result=self.service.vm.control(action='result',request_id=queued['request_id'])
            if result.get('state') not in ('pending','queued','running'):
                if result.get('error'):raise RuntimeError(str(result['error']))
                return result
            time.sleep(.7)
        raise RuntimeError('连接等待超时。请检查 Hyper‑V 和来宾状态后重试。')

    def list_vms(self):
        def listed(result):
            data=result.get('result',result);items=data.get('vms',[]) if isinstance(data,dict) else data
            self.vms.configure(values=[v.get('Name',v.get('name','')) for v in items] if isinstance(items,list) else [])
            if self.vms['values']:self.vms.current(0)
            self.status.set('已读取虚拟机列表。')
        self.background(lambda:self.vm_job('list'),listed)

    def connect_vm(self):
        vm=self.vms.get();username=self.user.get();password=self.password.get();self.password.set('')
        remember=self.remember.get();unattended=self.unattended.get()
        self.background(lambda:self.vm_job('connect',vm_name=vm,username=username,password=password,remember=remember,unattended=unattended),self.connected)

    def connected(self,result):
        state=self.service.vm.status()
        if state.get('connected'):self.skip_vm=False;self.status.set('虚拟机命令连接已建立。桌面状态：'+('已就绪' if state.get('desktop',{}).get('ready') else '尚未就绪，请在来宾中完成登录。'))
        else:self.status.set('连接尚未建立，请检查来宾账号、密码和运行状态。')

    def vm_continue(self):
        if not self.service.vm.status().get('connected'):self.status.set('请先连接虚拟机，或选择跳过。');return
        self.skip_vm=False;self.show(5)

    def page_5(self):
        agents={a['id']:a for a in self.service.agents()}
        self.label('Agent：已跳过，稍后可以添加。' if self.skip_agents else '项目经理：'+agents.get(self.manager,{}).get('name','尚未选择'),True)
        self.label('虚拟机：已跳过，稍后可以连接。' if self.skip_vm else '虚拟机：已建立连接。',True)
        self.label('完成后打开工作台。可以随时从开始菜单重新打开配置引导。')
        def finish():
            try:self.service.complete(self.skip_agents,self.manager,self.skip_vm)
            except Exception as error:self.status.set(str(error));return
            self.finished=True;self.close()
        self.button('完成并打开工作台',finish,self.footer,True,'right')


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--configure',action='store_true');parser.add_argument('--data-dir',type=Path,default=DEFAULT_DATA)
    parser.add_argument('--language',choices=['en','zh-CN'])
    parser.add_argument('--self-test',type=Path);args=parser.parse_args()
    if args.self_test:
        # Isolated packaged Tk/backend test; never opens production data/VM.
        import tempfile
        with tempfile.TemporaryDirectory() as folder:
            root=tk.Tk();service=SetupService(folder);wizard=Wizard(root,service)
            for selected in ('zh-CN','en'):
                wizard.change_language(selected)
                for step in (0,1,2,3,4,5):wizard.show(step);root.update()
            service.complete(True,'',True);root.destroy();service.close()
        args.self_test.write_text(json.dumps({'ok':True,'pages':6,'languages':['zh-CN','en'],'engine':'tkinter','configuration_only':True}),encoding='utf-8');return
    root=tk.Tk();root.withdraw()
    try:
        launch=main_executable()
        marker=args.data_dir/'onboarding.completed.json'
        completed=False
        try:completed=json.loads(marker.read_text(encoding='utf-8')).get('version')==1
        except (OSError,ValueError,AttributeError):pass
        if completed and not args.configure:
            root.destroy();subprocess.Popen([str(launch)],cwd=launch.parent);return
        service=SetupService(args.data_dir)
        try:
            from desktop.ui_preferences import save_language,language
            selected=language(args.data_dir,args.language or 'zh-CN');save_language(args.data_dir,selected)
            root.deiconify();wizard=Wizard(root,service,selected);root.mainloop();finished=wizard.finished
        finally:service.close()
        if finished:
            # Keep the owner of the VM helper alive without polling/UAC handoff.
            subprocess.Popen([str(launch)],cwd=launch.parent).wait()
    except Exception as error:
        from desktop.localization import translate
        messagebox.showerror('Agent Hub Setup',translate(str(error),args.language or 'zh-CN'));root.destroy()


if __name__=='__main__':main()
