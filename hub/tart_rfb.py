"""Small local RFB client for Tart's experimental console.

Preserve ServerInit pixel format and encodings: Apple's VNC server can crash
when clients negotiate RAW-only encodings. No guest services or TCC bypasses.
"""
import ctypes
import socket
import struct
import time
import zlib
from urllib.parse import urlparse, unquote

from .core import HubError


class Console:
    KEYS = {'cmd': 0xffe9, 'command': 0xffe9, 'option': 0xffe7, 'alt': 0xffe7,
            'ctrl': 0xffe3, 'control': 0xffe3, 'shift': 0xffe1, 'enter': 0xff0d,
            'return': 0xff0d, 'escape': 0xff1b, 'esc': 0xff1b, 'tab': 0xff09,
            'backspace': 0xff08, 'delete': 0xffff, 'left': 0xff51, 'up': 0xff52,
            'right': 0xff53, 'down': 0xff54, 'home': 0xff50, 'end': 0xff57,
            'pageup': 0xff55, 'pagedown': 0xff56, 'space': 32}

    def __init__(self, endpoint):
        parsed = urlparse(endpoint)
        if parsed.scheme != 'vnc' or parsed.hostname not in ('127.0.0.1', 'localhost', '::1'):
            raise HubError('只允许连接 Tart 本机控制台')
        self.sock = socket.create_connection((parsed.hostname, parsed.port or 5900), 8)
        self.sock.settimeout(15)
        try:
            version = self.read(12)
            if not version.startswith(b'RFB 003.'):
                raise HubError('控制台协议无效')
            self.sock.sendall(b'RFB 003.008\n')
            types = self.read(self.read(1)[0])
            if 2 not in types: raise HubError('控制台不支持密码认证')
            self.sock.sendall(b'\x02')
            challenge = self.read(16)
            password = unquote(parsed.password or parsed.username or '').encode()[:8].ljust(8, b'\0')
            key = bytes(int(f'{n:08b}'[::-1], 2) for n in password)
            api = ctypes.CDLL('/usr/lib/system/libcommonCrypto.dylib')
            fn = api.CCCrypt
            fn.argtypes = [ctypes.c_uint32, ctypes.c_uint32, ctypes.c_uint32, ctypes.c_void_p,
                           ctypes.c_size_t, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_size_t,
                           ctypes.c_void_p, ctypes.c_size_t, ctypes.POINTER(ctypes.c_size_t)]
            fn.restype = ctypes.c_int
            out = ctypes.create_string_buffer(32); length = ctypes.c_size_t()
            if fn(0, 1, 2, ctypes.create_string_buffer(key), 8, None,
                  ctypes.create_string_buffer(challenge), 16, out, 32, ctypes.byref(length)) or length.value != 16:
                raise HubError('控制台认证加密失败')
            self.sock.sendall(out.raw[:16])
            if struct.unpack('!I', self.read(4))[0]: raise HubError('控制台认证失败；请重新启动此虚拟机的桌面通道')
            self.sock.sendall(b'\x01')
            self.width, self.height = struct.unpack('!HH', self.read(4))
            self.pixel = struct.unpack('!BBBBHHHBBBxxx', self.read(16))
            length = struct.unpack('!I', self.read(4))[0]
            if length > 65536: raise HubError('控制台名称过长')
            self.read(length)
            self.validate_size()
            self.frame = bytearray(self.width * self.height * 3)
        except Exception:
            self.close(); raise

    def validate_size(self):
        if not (1 <= self.width <= 4096 and 1 <= self.height <= 4096):
            raise HubError('控制台分辨率超出支持范围')
        if self.pixel[0] not in (16, 32) or not self.pixel[3]:
            raise HubError('控制台像素格式不支持')

    def read(self, size):
        data = bytearray()
        while len(data) < size:
            part = self.sock.recv(size - len(data))
            if not part: raise HubError('控制台连接已关闭')
            data.extend(part)
        return bytes(data)

    def close(self):
        self.sock.close()

    def screenshot(self):
        self.sock.sendall(struct.pack('!BBHHHH', 3, 0, 0, 0, self.width, self.height))
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            kind = self.read(1)[0]
            if kind == 2: continue  # bell
            if kind == 3:
                self.read(3); size = struct.unpack('!I', self.read(4))[0]
                if size > 8 * 1024 * 1024: raise HubError('控制台剪贴板过大')
                self.read(size); continue
            if kind != 0: raise HubError('未知控制台消息')
            count = struct.unpack('!xH', self.read(3))[0]
            for _ in range(count):
                x, y, w, h, encoding = struct.unpack('!HHHHi', self.read(12))
                if encoding == -224: break
                if encoding == -223:
                    self.width, self.height = w, h; self.validate_size()
                    self.frame = bytearray(w * h * 3); continue
                if encoding != 0: raise HubError('控制台返回未支持的编码：' + str(encoding))
                if x+w > self.width or y+h > self.height: raise HubError('控制台矩形越界')
                bpp, _, big, _, rm, gm, bm, rs, gs, bs = self.pixel
                raw = self.read(w * h * (bpp//8)); step = bpp//8
                for row in range(h):
                    target = ((y+row)*self.width+x)*3
                    line = bytearray(w*3)
                    for col in range(w):
                        offset = (row*w+col)*step
                        pixel = int.from_bytes(raw[offset:offset+step], 'big' if big else 'little')
                        line[col*3:col*3+3] = bytes(((pixel>>rs & rm)*255//rm,
                                                  (pixel>>gs & gm)*255//gm,
                                                  (pixel>>bs & bm)*255//bm))
                    self.frame[target:target+w*3] = line
            # A freshly booted console may expose a black placeholder frame.
            if any(self.frame): return self.png()
            self.sock.sendall(struct.pack('!BBHHHH', 3, 0, 0, 0, self.width, self.height))
            time.sleep(.15)
        raise HubError('控制台仍为黑屏，桌面尚未就绪')

    def png(self):
        def chunk(kind, data):
            return struct.pack('!I', len(data))+kind+data+struct.pack('!I', zlib.crc32(kind+data))
        scan = b''.join(b'\0'+self.frame[y*self.width*3:(y+1)*self.width*3] for y in range(self.height))
        return b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',struct.pack('!IIBBBBB',self.width,self.height,8,2,0,0,0))+chunk(b'IDAT',zlib.compress(scan))+chunk(b'IEND',b'')

    def key(self, key, down):
        self.sock.sendall(struct.pack('!BBHI', 4, int(down), 0, key))

    def chord(self, keys):
        if not isinstance(keys, list) or not 1 <= len(keys) <= 8: raise HubError('按键组合需要 1–8 个键')
        codes = []
        for key in keys:
            if not isinstance(key, str): raise HubError('按键名称无效')
            value = self.KEYS.get(key.lower())
            if value is None and len(key) == 1: value = ord(key.lower())
            if value is None: raise HubError('未知按键：'+key)
            codes.append(value)
        held = []
        try:
            for code in codes:
                self.key(code, True); held.append(code); time.sleep(.08)
        finally:
            for code in reversed(held): self.key(code, False)
        time.sleep(.12)

    def text(self, text):
        if not isinstance(text, str) or len(text) > 512: raise HubError('单次直接输入最多 512 字符；长文本请使用文件传输')
        # Validate everything before sending to avoid partial unsupported input.
        if any(ord(c) > 127 or (ord(c) < 32 and c not in '\n\t') for c in text):
            raise HubError('当前 Tart 直接输入只支持 ASCII；中文请通过文件传输，未发送部分文本')
        shifted = dict(zip('~!@#$%^&*()_+{}|:"<>?', '`1234567890-=[]\\;\',./'))
        for char in text:
            if char == '\n': self.chord(['enter'])
            elif char == '\t': self.chord(['tab'])
            elif char.isupper(): self.chord(['shift', char.lower()])
            elif char in shifted: self.chord(['shift', shifted[char]])
            else: self.chord([char])

    def pointer(self, x, y, mask=0):
        if type(x) is not int or type(y) is not int or not (0 <= x < self.width and 0 <= y < self.height):
            raise HubError('坐标必须位于控制台屏幕内')
        self.sock.sendall(struct.pack('!BBHH',5,mask,x,y))
