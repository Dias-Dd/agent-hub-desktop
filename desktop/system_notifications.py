"""Windows notification-center delivery, invoked only for completion events."""
import base64
import subprocess
import sys
from xml.etree import ElementTree as ET

APP_ID = 'AgentHub.Desktop'


def send(title, message):
    if sys.platform=='darwin':
        from .macos_notifications import send as native_send
        return native_send(title,message)
    import winreg
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, 'Software\\Classes\\AppUserModelId\\' + APP_ID) as key:
        winreg.SetValueEx(key, 'DisplayName', 0, winreg.REG_SZ, 'Agent Hub')
        winreg.SetValueEx(key, 'ShowInSettings', 0, winreg.REG_DWORD, 1)
    toast = ET.Element('toast')
    binding = ET.SubElement(ET.SubElement(toast, 'visual'), 'binding', template='ToastGeneric')
    ET.SubElement(binding, 'text').text = title
    ET.SubElement(binding, 'text').text = message
    payload = base64.b64encode(ET.tostring(toast, encoding='utf-8')).decode('ascii')
    script = """$ErrorActionPreference='Stop'
[Windows.UI.Notifications.ToastNotificationManager,Windows.UI.Notifications,ContentType=WindowsRuntime] > $null
[Windows.UI.Notifications.ToastNotification,Windows.UI.Notifications,ContentType=WindowsRuntime] > $null
[Windows.Data.Xml.Dom.XmlDocument,Windows.Data.Xml.Dom.XmlDocument,ContentType=WindowsRuntime] > $null
$xml=New-Object Windows.Data.Xml.Dom.XmlDocument
$xml.LoadXml([Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('PAYLOAD')))
$toast=[Windows.UI.Notifications.ToastNotification]::new($xml)
[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier('AgentHub.Desktop').Show($toast)
""".replace('PAYLOAD', payload)
    encoded = base64.b64encode(script.encode('utf-16-le')).decode('ascii')
    result = subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-EncodedCommand', encoded],
                            capture_output=True, timeout=20,
                            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    if result.returncode:
        raise RuntimeError('Windows notification delivery failed')
