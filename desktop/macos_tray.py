"""Cocoa menu-bar equivalent of the Windows tray, using the same read-only cache."""
import AppKit as A
import Foundation as F
import objc
from .tray_status import menu_rows
from .ui_preferences import language


class MacTray(F.NSObject):
    def initWithOwner_status_(self,owner,status):
        self=objc.super(MacTray,self).init()
        if self is None:return None
        self.owner=owner;self.status=status;self.pending=[]
        self.item=A.NSStatusBar.systemStatusBar().statusItemWithLength_(A.NSVariableStatusItemLength)
        image=A.NSImage.alloc().initWithSize_((18,18));image.lockFocus()
        A.NSColor.blackColor().setStroke()
        for rect in ((2,3,6,12),(11,10,5,5),(11,3,5,5)):
            path=A.NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(A.NSMakeRect(*rect),1.5,1.5)
            path.setLineWidth_(1.5);path.stroke()
        path=A.NSBezierPath.bezierPath();path.moveToPoint_((8,12));path.lineToPoint_((11,12));path.moveToPoint_((8,5));path.lineToPoint_((11,5));path.stroke()
        image.unlockFocus();image.setTemplate_(True)
        self.item.button().setImage_(image);self.item.button().setToolTip_('Agent Hub')
        self.menu=A.NSMenu.alloc().init();self.menu.setDelegate_(self);self.item.setMenu_(self.menu)
        return self

    @objc.python_method
    def add(self,label,action=None,project=None):
        item=A.NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(label,action,'')
        item.setTarget_(self)
        if project:item.setRepresentedObject_(project)
        if not action:item.setEnabled_(False)
        self.menu.addItem_(item)

    def menuNeedsUpdate_(self,menu):
        english=language(self.status.directory)=='en'
        translate={'进行中的项目':'Active projects','暂无进行中的项目':'No active projects','Agent 状态':'Agent status',
                   '正在加载 Agent 状态':'Loading Agent status','状态暂未更新，保留上次记录':'Status unavailable; showing last reading',
                   '进行中':'In progress','暂停':'Paused','等待处理':'Waiting','待核查':'Needs review','待经理汇报':'Awaiting manager report'}
        self.menu.removeAllItems()
        self.add('Open workspace' if english else '打开工作台','show:')
        for event in self.pending:
            label=('Demo ready' if event.get('kind')=='demo' else 'Project completed') if english else ('产品演示已完成' if event.get('kind')=='demo' else '项目已完成')
            self.add(label+' · '+event.get('name',''),'project:',event.get('project'))
        for kind,label,project in menu_rows(self.status.value):
            if kind=='header':self.menu.addItem_(A.NSMenuItem.separatorItem())
            if english:
                for source,target in translate.items():label=label.replace(source,target)
            self.add(label,'project:' if project else None,project)
        self.menu.addItem_(A.NSMenuItem.separatorItem())
        self.add('Setup guide' if english else '配置指引','setup:')
        self.add('Quit application…' if english else '退出应用…','quit:')

    def show_(self,sender):self.owner.restore_(None)
    def setup_(self,sender):self.owner.restore_(None);self.owner.showSetup_(None)
    def quit_(self,sender):A.NSApp().terminate_(None)
    def project_(self,sender):
        project=sender.representedObject()
        self.pending=[e for e in self.pending if e.get('project')!=project]
        self.item.button().setTitle_('•' if self.pending else '')
        self.owner.open_project(project)

    @objc.python_method
    def observe(self,event):
        self.pending=([event]+self.pending)[:20]
        self.item.button().setTitle_('•')
        self.item.button().setToolTip_('Agent Hub · '+(event.get('name') or 'New completion'))

    @objc.python_method
    def close(self):
        self.menu.setDelegate_(None)
        A.NSStatusBar.systemStatusBar().removeStatusItem_(self.item)
