"""Generic passwords in the user's Keychain; secrets never enter argv or files."""
import ctypes as C
import hashlib
from pathlib import Path
from .core import HubError


class Keychain:
    def __init__(self, directory, account='deepseek-api'):
        scope = hashlib.sha256(str(Path(directory).resolve()).encode()).hexdigest()
        self.service = ('AgentHub.Desktop.' + scope).encode()
        self.account = account.encode()
        self.api = C.CDLL('/System/Library/Frameworks/Security.framework/Security')
        self.api.SecKeychainFindGenericPassword.argtypes = [C.c_void_p, C.c_uint32, C.c_char_p,
            C.c_uint32, C.c_char_p, C.POINTER(C.c_uint32), C.POINTER(C.c_void_p), C.POINTER(C.c_void_p)]
        self.api.SecKeychainAddGenericPassword.argtypes = [C.c_void_p, C.c_uint32, C.c_char_p,
            C.c_uint32, C.c_char_p, C.c_uint32, C.c_void_p, C.POINTER(C.c_void_p)]
        self.api.SecKeychainItemModifyAttributesAndData.argtypes = [C.c_void_p, C.c_void_p, C.c_uint32, C.c_void_p]
        self.api.SecKeychainItemFreeContent.argtypes = [C.c_void_p, C.c_void_p]
        self.api.SecKeychainItemDelete.argtypes = [C.c_void_p]
        self.cf = C.CDLL('/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation')
        self.cf.CFRelease.argtypes = [C.c_void_p]

    def find(self, content=True):
        length = C.c_uint32()
        data = C.c_void_p()
        item = C.c_void_p()
        code = self.api.SecKeychainFindGenericPassword(None, len(self.service), self.service,
            len(self.account), self.account, C.byref(length) if content else None,
            C.byref(data) if content else None, C.byref(item))
        if code == -25300: return None, None
        if code: raise HubError('macOS Keychain 访问失败（OSStatus %s）；未降级为明文存储' % code)
        try:
            return C.string_at(data, length.value).decode('utf-8') if content else True, item
        finally:
            if data:self.api.SecKeychainItemFreeContent(None, data)

    def get(self):
        value, item = self.find()
        if item:self.cf.CFRelease(item)
        return value

    def set(self, value):
        raw = value.encode('utf-8')
        _, item = self.find(False)
        try:
            if item:
                code = self.api.SecKeychainItemModifyAttributesAndData(item, None, len(raw), raw)
            else:
                code = self.api.SecKeychainAddGenericPassword(None, len(self.service), self.service,
                    len(self.account), self.account, len(raw), raw, None)
            if code:raise HubError('macOS Keychain 保存失败（OSStatus %s）；密钥未写入文件' % code)
        finally:
            if item:self.cf.CFRelease(item)

    def delete(self):
        _, item = self.find(False)
        if item:
            try:
                code = self.api.SecKeychainItemDelete(item)
                if code:raise HubError('macOS Keychain 删除失败（OSStatus %s）' % code)
            finally:self.cf.CFRelease(item)


def present(directory):
    # Marker is an observation, not proof Keychain access is currently authorized.
    return (Path(directory) / 'deepseek-key.keychain').is_file()


def save(directory, value):
    Keychain(directory).set(value)
    (Path(directory) / 'deepseek-key.keychain').write_text('macOS Keychain reference; no secret\n', encoding='utf-8')
