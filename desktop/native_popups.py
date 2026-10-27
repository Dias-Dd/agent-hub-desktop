"""Owned Win32 windows for WebView2 window.open; shares the main environment.
Vtable positions verified against Microsoft's WebView2.h (1.0.2651.64).
Only the local popup shell receives opener access and native modality.
"""
import ctypes as C
from ctypes import wintypes as W
import uuid
from urllib.parse import urlsplit, parse_qs


def popup_request(uri, origin):
    parsed=urlsplit(uri);base=urlsplit(origin)
    if (parsed.scheme,parsed.netloc,parsed.path)!=(base.scheme,base.netloc,'/popup.html'):
        return None
    args=parse_qs(parsed.fragment)
    def value(key,default=''):return args.get(key,[default])[0]
    def dimension(key,default):
        try:return max(300,min(2400,int(value(key,str(default)))))
        except ValueError:return default
    identity=value('id')
    if not identity:return None
    return {'id':identity,'owner':value('owner'),'modal':value('modal')=='1','title':value('title','Agent Hub')[:160],
            'width':dimension('width',900),'height':dimension('height',700)}


def popup_style(config):
    # Review is a full workspace; small dialogs keep their existing caption controls.
    return 0x00CC0000 | (0x00030000 if config['id']=='designReviewDialog' else 0)


class NativePopups:
    def __init__(self,user,kernel,ole,call,check,handler,environment,parent,origin,instance,icon,theme,log,zoom=lambda:1):
        self.user,self.ole,self.call,self.check,self.handler=user,ole,call,check,handler
        self.environment,self.parent,self.origin=environment,parent,origin
        self.instance,self.theme,self.log,self.zoom=instance,theme,log,zoom
        self.windows={};self.disabled={};self.created=0;self.closed=0
        self.name='AgentHubPopup'+str(parent)
        self.HR=C.c_long;self.PTR=C.c_void_p
        self.WNDPROC=C.WINFUNCTYPE(C.c_ssize_t,W.HWND,W.UINT,W.WPARAM,W.LPARAM)
        class WC(C.Structure):
            _fields_=[('style',W.UINT),('lpfnWndProc',self.WNDPROC),('cbClsExtra',C.c_int),('cbWndExtra',C.c_int),('hInstance',W.HINSTANCE),('hIcon',W.HICON),('hCursor',W.HANDLE),('hbrBackground',W.HBRUSH),('lpszMenuName',W.LPCWSTR),('lpszClassName',W.LPCWSTR)]
        self.proc=self.WNDPROC(self.wndproc);self.wc=WC();self.wc.lpfnWndProc=self.proc;self.wc.hInstance=instance;self.wc.hIcon=icon;self.wc.lpszClassName=self.name
        if not user.RegisterClassW(C.byref(self.wc)):raise C.WinError()
        user.UnregisterClassW.argtypes=[W.LPCWSTR,W.HINSTANCE]
        user.EnableWindow.argtypes=[W.HWND,W.BOOL];user.IsWindowEnabled.argtypes=[W.HWND];user.IsWindowEnabled.restype=W.BOOL
        user.SetForegroundWindow.argtypes=[W.HWND];user.SetFocus.argtypes=[W.HWND]
        ole.CoTaskMemFree.argtypes=[self.PTR]

    def listen(self,core,slot,fn):
        token=C.c_longlong();cb=self.handler([self.PTR,self.PTR],fn)
        self.check(self.call(core,slot,self.HR,[self.PTR,C.POINTER(C.c_longlong)],cb,C.byref(token)))

    def bind(self,core):
        def requested(sender,args):
            try:self.requested(sender,args)
            except Exception as error:
                # A failed secondary window must never terminate the workspace.
                self.log('popup_request_failed',error=str(error))
        self.listen(core,44,requested)

    def release_request(self,item):
        if item.get('deferral'):
            self.call(item['deferral'],3,self.HR,[]);self.call(item['deferral'],2,W.ULONG,[]);item['deferral']=None
        if item.get('args'):
            self.call(item['args'],2,W.ULONG,[]);item['args']=None

    def requested(self,sender,args):
        address=self.PTR();self.check(self.call(args,3,self.HR,[C.POINTER(self.PTR)],C.byref(address)))
        try:uri=C.wstring_at(address) if address else ''
        finally:self.ole.CoTaskMemFree(address)
        config=popup_request(uri,self.origin)
        if not config:return
        self.check(self.call(args,6,self.HR,[W.BOOL],True))
        deferral=self.PTR();self.check(self.call(args,9,self.HR,[C.POINTER(self.PTR)],C.byref(deferral)))
        self.call(args,1,W.ULONG,[])
        owner=next((w for w,v in self.windows.items() if v['id']==config['owner']),self.parent)
        rect=W.RECT();self.user.GetWindowRect(owner,C.byref(rect))
        # Requested dimensions are logical pixels; cap at the monitor work area.
        area=W.RECT();self.user.SystemParametersInfoW(0x30,0,C.byref(area),0)
        try:scale=self.user.GetDpiForWindow(owner)/96
        except AttributeError:scale=1
        width=min(round(config['width']*scale),area.right-area.left-32);height=min(round(config['height']*scale),area.bottom-area.top-32)
        x=max(area.left,min(area.right-width,(rect.left+rect.right-width)//2));y=max(area.top,min(area.bottom-height,(rect.top+rect.bottom-height)//2))
        hwnd=self.user.CreateWindowExW(0,self.name,config['title']+' · Agent Hub',popup_style(config),x,y,width,height,owner,None,self.instance,None)
        item={**config,'owner_hwnd':owner,'args':args,'deferral':deferral,'controller':None,'core':None}
        if not hwnd:
            self.release_request(item);self.log('popup_create_failed');return
        self.windows[hwnd]=item;self.created+=1;self.theme(hwnd)
        if config['modal']:
            if owner not in self.disabled:self.disabled[owner]=[0,bool(self.user.IsWindowEnabled(owner))]
            self.disabled[owner][0]+=1;self.user.EnableWindow(owner,False)
        self.user.ShowWindow(hwnd,5);self.user.SetForegroundWindow(hwnd)
        self.log('popup_open',id=config['id'],modal=config['modal'],hwnd=hwnd,owner=owner)
        def created(hr,controller):
            # A user may close a window while controller creation is pending.
            if hwnd not in self.windows:
                if hr>=0 and controller:self.call(controller,24,self.HR,[])
                return
            try:
                self.check(hr);self.call(controller,1,W.ULONG,[]);item['controller']=controller
                core=self.PTR();self.check(self.call(controller,25,self.HR,[C.POINTER(self.PTR)],C.byref(core)));item['core']=core
                settings=self.PTR();self.check(self.call(core,3,self.HR,[C.POINTER(self.PTR)],C.byref(settings)))
                try:
                    for slot in (10,12,16):self.call(settings,slot,self.HR,[W.BOOL],False)
                    iid=(C.c_ubyte*16).from_buffer_copy(uuid.UUID('cb56846c-4168-4d53-b04f-03b6d6796ff2').bytes_le);extended=self.PTR()
                    if self.call(settings,0,self.HR,[self.PTR,C.POINTER(self.PTR)],C.byref(iid),C.byref(extended))>=0:
                        try:
                            for slot in (26,28):self.call(extended,slot,self.HR,[W.BOOL],False)
                        finally:self.call(extended,2,W.ULONG,[])
                finally:self.call(settings,2,W.ULONG,[])
                self.call(controller,8,self.HR,[C.c_double],self.zoom())
                self.listen(core,59,lambda *_:self.user.PostMessageW(hwnd,0x8015,0,0))
                self.listen(core,25,lambda *_:self.user.PostMessageW(hwnd,0x8015,0,0))
                self.bind(core);self.resize(hwnd)
                self.check(self.call(controller,4,self.HR,[W.BOOL],True))
                self.check(self.call(args,4,self.HR,[self.PTR],core))
            except Exception as error:
                self.log('popup_controller_failed',error=str(error));self.user.PostMessageW(hwnd,0x8015,0,0)
            finally:self.release_request(item)
        hr=self.call(self.environment,3,self.HR,[W.HWND,self.PTR],hwnd,self.handler([self.HR,self.PTR],created))
        if hr<0:self.release_request(item);self.destroy(hwnd)

    def resize(self,hwnd):
        item=self.windows.get(hwnd)
        if item and item['controller']:
            rect=W.RECT();self.user.GetClientRect(hwnd,C.byref(rect));self.call(item['controller'],6,self.HR,[W.RECT],rect)

    def destroy(self,hwnd):
        item=self.windows.pop(hwnd,None)
        if not item:return
        for child,v in list(self.windows.items()):
            if v['owner_hwnd']==hwnd:self.destroy(child)
        self.user.KillTimer(hwnd,2);self.release_request(item)
        if item['controller']:
            self.call(item['controller'],24,self.HR,[]);self.call(item['controller'],2,W.ULONG,[])
        if item['core']:self.call(item['core'],2,W.ULONG,[])
        owner=item['owner_hwnd']
        if item['modal'] and owner in self.disabled:
            self.disabled[owner][0]-=1
            if not self.disabled[owner][0]:
                _,was_enabled=self.disabled.pop(owner);self.user.EnableWindow(owner,was_enabled)
                if was_enabled:self.user.SetForegroundWindow(owner)
        self.user.DestroyWindow(hwnd);self.closed+=1;self.log('popup_closed',id=item['id'])

    def wndproc(self,hwnd,msg,wp,lp):
        try:
            item=self.windows.get(hwnd)
            if msg==5:self.resize(hwnd);return 0
            if msg==0x2e0:
                r=C.cast(lp,C.POINTER(W.RECT)).contents;self.user.SetWindowPos(hwnd,None,r.left,r.top,r.right-r.left,r.bottom-r.top,0x14);self.resize(hwnd);return 0
            if msg==3 and item and item['controller']:self.call(item['controller'],23,self.HR,[])
            if msg==0x10 and item:
                if item.get('closing'):return 0
                item['closing']=True
                if item['core']:
                    # Give the page a chance to return live DOM/drafts before
                    # destroying its controller. Timer handles an unresponsive page.
                    cb=self.handler([self.HR,W.LPCWSTR],lambda *_:self.user.PostMessageW(hwnd,0x8015,0,0))
                    self.call(item['core'],29,self.HR,[W.LPCWSTR,self.PTR],'window.HubPopupClose?.()',cb)
                    self.user.SetTimer(hwnd,2,2000,None)
                else:self.destroy(hwnd)
                return 0
            if msg==0x8015 or (msg==0x113 and wp==2):self.destroy(hwnd);return 0
            if msg==2:return 0 # A child must never terminate the main message loop.
        except Exception as error:
            self.log('popup_window_error',error=str(error));self.destroy(hwnd);return 0
        return self.user.DefWindowProcW(hwnd,msg,wp,lp)

    def close_all(self):
        for hwnd in list(self.windows):self.destroy(hwnd)

    def dispose(self):
        self.close_all();self.user.UnregisterClassW(self.name,self.instance)

# Runs only in an isolated native-window test, never in a live project.
POPUP_PROBE=r"""(()=>{
 if(!window.HubWindows||!window.HubDesktop)return {phase:'loading'};
 if(!window.__popupProbe){
  window.__popupProbe={phase:'starting'};
  (async()=>{const p=window.__popupProbe,wait=ms=>new Promise(r=>setTimeout(r,ms));
   const attached=async id=>{for(let n=0;n<50;n++){const e=HubWindows.entries.get(id);if(e&&e.root.ownerDocument!==document&&e.win?.HubPopupClose){for(const button of e.root.querySelectorAll('.dialog-close,.close-modal-btn,#setupClose'))if(e.win.getComputedStyle(button).display!=='none')throw Error('Duplicate close button visible');return e;}await wait(100);}throw Error('Popup attach timed out: '+id);};
   if(!document.getElementById('nativeTitlebar'))throw Error('Custom title bar missing');
   window.chrome.webview.postMessage({type:'hub-window',command:'maximize'});await wait(300);
   if(!document.querySelector('#nativeTitlebar button[aria-label="还原"]'))throw Error('Custom maximize failed');
   window.chrome.webview.postMessage({type:'hub-window',command:'maximize'});await wait(300);
   if(!document.querySelector('#nativeTitlebar button[aria-label="最大化"]'))throw Error('Custom restore failed');
   const toggle=document.getElementById('configModalToggle');toggle.checked=true;
   let e=await attached('configModal');
   const settings=e.root.querySelector('.config-modal-dialog'),settingsBounds=settings.getBoundingClientRect();
   if(Math.abs(settingsBounds.left)>2||Math.abs(settingsBounds.top)>2||Math.abs(settingsBounds.width-e.win.innerWidth)>2||Math.abs(settingsBounds.height-e.win.innerHeight)>2)throw Error('Settings did not fill native client: '+JSON.stringify(settingsBounds.toJSON()));
   if(e.win.document.documentElement.classList.contains('native-backdrop')||e.win.getComputedStyle(e.win.document.body).backgroundColor==='rgba(0, 0, 0, 0)')throw Error('Detached settings inherited transparent main-window canvas');

   const input=document.getElementById('storageRoot');input.value='native draft';input.dispatchEvent(new Event('input'));
   p.phase='modeless';for(let n=0;HubWindows.entries.has('configModal');n++){if(n>60)throw Error('Native modeless close timed out');await wait(100);}await wait(250);
   if(document.getElementById('storageRoot').value!=='native draft')throw Error('Draft lost on window close');
   const d=document.getElementById('newProjectDialog');d.showModal();e=await attached(d.id);
   const name=document.getElementById('hubProjectName'),header=d.querySelector('.project-dialog-header'),form=document.getElementById('hubProjectCreate');
   if(header.getBoundingClientRect().bottom>name.getBoundingClientRect().top)throw Error('Project heading overlaps the name input');
   form.scrollTop=form.scrollHeight;
   if(header.getBoundingClientRect().top<0||form.getBoundingClientRect().top<header.getBoundingClientRect().bottom-1)throw Error('Project form scrolling covers the heading');
   form.scrollTop=0;name.value='window test';p.phase='modal';for(let n=0;HubWindows.entries.has(d.id);n++){if(n>60)throw Error('Native modal close timed out');await wait(100);}await wait(300);
   if(d.open||HubWindows.entries.size)throw Error('Popup not released');
   if(name.value!=='window test')throw Error('Form draft lost');
   toggle.checked=true;e=await attached('configModal');if(document.getElementById('storageRoot').value!=='native draft')throw Error('Reopen draft lost');
   e.win.HubPopupClose();await wait(250);
   const review=document.getElementById('designReviewDialog');review.hidden=false;e=await attached(review.id);await wait(1300);
   const stage=document.getElementById('designStage'),canvas=document.getElementById('designCanvas');
   if(stage.clientHeight<150||stage.clientWidth<150)throw Error('Review canvas clipped');
   const overall=document.getElementById('designOverallFeedback');overall.value='review draft';
   document.getElementById('designZoomIn').click();
   if(!Number.isFinite(parseFloat(e.win.getComputedStyle(canvas).zoom)))throw Error('Detached design zoom missing');
   document.getElementById('designSelectRegion').click();
   const overlay=document.getElementById('designOverlay'),r=overlay.getBoundingClientRect();
   overlay.dispatchEvent(new PointerEvent('pointerdown',{button:0,clientX:r.left+10,clientY:r.top+10}));
   overlay.dispatchEvent(new PointerEvent('pointerup',{button:0,clientX:r.left+80,clientY:r.top+80}));
   if(!(Number(document.getElementById('designSelection').getAttribute('width'))>0))throw Error('Detached annotation failed');
   review.hidden=true;await wait(200);
   if(overall.value!=='review draft')throw Error('Review draft lost');
   const integrations=document.getElementById('integrationsDialog'),agentList=document.getElementById('integrationAgentList');
   for(let n=0;n<20;n++){const row=document.createElement('article');row.className='agent-manager-row';row.textContent='Test agent '+n+' / model / test passed';agentList.append(row);}
   integrations.hidden=false;e=await attached(integrations.id);
   const area=integrations.querySelector('.agent-manager-content'),fixedHeader=integrations.querySelector('.integrations-header');area.scrollTop=area.scrollHeight;
   if(area.scrollTop<100||area.getBoundingClientRect().top<fixedHeader.getBoundingClientRect().bottom-1)throw Error('Agent list scroll overlaps the heading');
   const toolbar=integrations.querySelector('.agent-manager-toolbar');if(e.win.getComputedStyle(toolbar).position==='sticky')throw Error('Agent toolbar overlays rows');
   area.scrollTop=0;
   document.getElementById('agentName').value='new agent draft';integrations.hidden=true;await wait(200);
   const quota=document.getElementById('quotaQuickPanel');quota.hidden=false;if(quota.ownerDocument!==document||HubWindows.entries.has(quota.id))throw Error('Quota should stay in the workbench');quota.hidden=true;await wait(200);
   // Dynamically-created HTML dialogs use the same native lifecycle.
   const dynamic=document.createElement('dialog');dynamic.textContent='dynamic confirmation';document.body.append(dynamic);dynamic.showModal();e=await attached(dynamic.id);dynamic.close('cancel');await wait(200);dynamic.remove();
   if(HubWindows.entries.size)throw Error('Window registry leaked');
   p.phase='done';p.ready=true;
  })().catch(e=>{window.__popupProbe.error=e.stack;});
 }
 return window.__popupProbe;
})()"""
