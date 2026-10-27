import unittest
from hub.mcp import TOOLS, vm_tool_description

class VmToolDescription(unittest.TestCase):
    def test_windows_does_not_receive_macos_requirements(self):
        description=vm_tool_description('win32')
        for word in ('Hyper-V','Windows UI Automation','PowerShell','desktop_launch'):
            self.assertIn(word,description)
        for word in ('Peekaboo','Tart','sudo','posix','VNC'):
            self.assertNotIn(word,description)
    def test_macos_retains_its_requirements(self):
        description=vm_tool_description('darwin')
        for word in ('Tart','Peekaboo','sudo -n','shell=posix','Guest Agent'):
            self.assertIn(word,description)
        for word in ('Hyper-V','PowerShell','Windows UI Automation'):
            self.assertNotIn(word,description)
    def test_protocol_and_modules_share_host_description(self):
        self.assertEqual(next(d for n,d,_ in TOOLS if n=='project_vm'),vm_tool_description())
