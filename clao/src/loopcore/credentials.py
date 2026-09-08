"""Windows Credential Manager, fixed CLAO namespace; never enumerate user keys."""
import ctypes
from ctypes import wintypes as w
import os
from .model_profiles import REFERENCE


class CredentialError(ValueError):
    pass


class _Credential(ctypes.Structure):
    _fields_=[('Flags',w.DWORD),('Type',w.DWORD),('TargetName',w.LPWSTR),('Comment',w.LPWSTR),
              ('LastWritten',w.FILETIME),('CredentialBlobSize',w.DWORD),
              ('CredentialBlob',ctypes.POINTER(ctypes.c_ubyte)),('Persist',w.DWORD),
              ('AttributeCount',w.DWORD),('Attributes',ctypes.c_void_p),
              ('TargetAlias',w.LPWSTR),('UserName',w.LPWSTR)]


class WindowsCredentials:
    def __init__(self, namespace='CLAO/BigModel'):
        # Tests use only their own random namespace; production never takes this from HTTP/config.
        self.namespace=namespace

    def _target(self, ref):
        if not isinstance(ref,str) or not REFERENCE.fullmatch(ref):
            raise CredentialError('凭据名称格式不合法')
        return self.namespace+'/'+ref

    def _api(self):
        if os.name != 'nt':
            raise CredentialError('Windows 系统凭据存储不可用；不会回退到明文文件')
        try:
            api=ctypes.WinDLL('Advapi32.dll',use_last_error=True)
            api.CredReadW.argtypes=[w.LPCWSTR,w.DWORD,w.DWORD,ctypes.POINTER(ctypes.POINTER(_Credential))]
            api.CredWriteW.argtypes=[ctypes.POINTER(_Credential),w.DWORD]
            api.CredDeleteW.argtypes=[w.LPCWSTR,w.DWORD,w.DWORD]
            for name in ('CredReadW','CredWriteW','CredDeleteW'):getattr(api,name).restype=w.BOOL
            api.CredFree.argtypes=[ctypes.c_void_p];api.CredFree.restype=None
            return api
        except OSError:
            raise CredentialError('Windows 系统凭据存储不可用') from None

    def read(self, ref):
        target=self._target(ref);api=self._api();ptr=ctypes.POINTER(_Credential)()
        if not api.CredReadW(target,1,0,ctypes.byref(ptr)):
            if ctypes.get_last_error()==1168:return None
            raise CredentialError('无法读取 Windows 凭据；请检查当前 Windows 用户会话')
        try:
            value=ctypes.string_at(ptr.contents.CredentialBlob,ptr.contents.CredentialBlobSize).decode('utf-8')
            self._validate(value)
            return value
        except UnicodeError:
            raise CredentialError('凭据格式不可读取，请重新保存') from None
        finally:api.CredFree(ptr)

    def configured(self, ref):
        return self.read(ref) is not None

    @staticmethod
    def _validate(value):
        if not isinstance(value,str) or not 1 <= len(value) <= 2048 or any(not 33 <= ord(c) <= 126 for c in value):
            raise CredentialError('凭据必须是非空、无空白的 API Key（最多 2048 字符）')

    def save(self, ref, value):
        target=self._target(ref);self._validate(value);api=self._api()
        data=value.encode('utf-8');buf=(ctypes.c_ubyte*len(data)).from_buffer_copy(data)
        record=_Credential(Type=1,TargetName=target,CredentialBlobSize=len(data),CredentialBlob=buf,
                           Persist=2,UserName='CLAO BigModel')
        try:
            if not api.CredWriteW(ctypes.byref(record),0):
                raise CredentialError('Windows 凭据保存失败；未写入明文备用文件')
        finally:ctypes.memset(buf,0,len(data))

    def delete(self, ref):
        target=self._target(ref);api=self._api()
        if not api.CredDeleteW(target,1,0) and ctypes.get_last_error()!=1168:
            raise CredentialError('Windows 凭据删除失败')


def credentials():
    return WindowsCredentials()
