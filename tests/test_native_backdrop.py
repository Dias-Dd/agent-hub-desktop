import ctypes as C
from types import SimpleNamespace
import unittest
from desktop.native_backdrop import AccentPolicy,CompositionData,VersionInfo,windows_build,apply


class Function:
    def __init__(self,callback):self.callback=callback
    def __call__(self,*args):return self.callback(*args)


class Backdrop(unittest.TestCase):
    def setUp(self):
        self.accents=[];self.attributes=[]
        def accent(hwnd,pointer):
            data=C.cast(pointer,C.POINTER(CompositionData)).contents
            policy=C.cast(data.data,C.POINTER(AccentPolicy)).contents
            self.accents.append((hwnd,data.attribute,data.size,policy.state,policy.color))
            return True
        def attribute(hwnd,number,pointer,size):
            self.attributes.append((number,C.cast(pointer,C.POINTER(C.c_int)).contents.value))
            return 0
        self.user=SimpleNamespace(SetWindowCompositionAttribute=Function(accent))
        self.dwm=SimpleNamespace(DwmSetWindowAttribute=Function(attribute))

    def material(self,build=19045,dark=False,allowed=True):
        return apply(123,dark,build=build,allowed=allowed,user=self.user,dwm=self.dwm)

    def test_windows_10_requests_acrylic_without_mica_attribute(self):
        self.assertEqual(self.material(),'acrylic')
        self.assertEqual(self.attributes,[])
        self.assertEqual(self.accents[0][:4],(123,19,C.sizeof(AccentPolicy),4))

    def test_acrylic_tint_changes_with_theme_and_has_readable_alpha(self):
        self.material();self.material(dark=True)
        self.assertNotEqual(self.accents[0][4],self.accents[1][4])
        self.assertGreaterEqual(self.accents[1][4]>>24,0xC0)

    def test_windows_11_retains_mica(self):
        self.assertEqual(self.material(22621),'mica')
        self.assertEqual(self.attributes,[(38,2)])
        self.assertEqual(self.accents,[])

    def test_first_windows_11_build_uses_legacy_mica(self):
        self.assertEqual(self.material(22000),'mica')
        self.assertEqual(self.attributes,[(1029,1)])

    def test_disabled_transparency_removes_acrylic(self):
        self.assertIsNone(self.material(allowed=False))
        self.assertEqual(self.accents[0][3],0)

    def test_unavailable_or_failed_acrylic_api_falls_back_to_solid(self):
        self.user=SimpleNamespace()
        self.assertIsNone(self.material())
        self.user=SimpleNamespace(SetWindowCompositionAttribute=Function(lambda *args:False))
        self.assertIsNone(self.material())

    def test_unsupported_older_windows_does_not_call_material_apis(self):
        self.assertIsNone(self.material(16299))
        self.assertEqual(self.accents,[])
        self.assertEqual(self.attributes,[])

    def test_version_detection_reads_real_build_without_manifest_assumption(self):
        def get_version(pointer):
            value=C.cast(pointer,C.POINTER(VersionInfo)).contents
            value.major=10;value.build=19045
            return 0
        self.assertEqual(windows_build(SimpleNamespace(RtlGetVersion=Function(get_version))),19045)
