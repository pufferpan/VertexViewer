"""Offline Ed25519 licenses binding product, machine, owner name and expiry."""
from __future__ import annotations
import base64
import binascii
from datetime import datetime,timezone
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import time
import uuid
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

# 冻结：已签发的激活码签在这串字节上，改名会导致存量授权全部失效。
DOMAIN = b'DFViewer license v1\0'
PRODUCT = 'DFViewer'
MAX_TIME = 4102444800
CLOCK_TOLERANCE = 300


class ActivationError(ValueError):
    pass


def b64(data):
    return base64.urlsafe_b64encode(data).decode('ascii').rstrip('=')


def unb64(text):
    if not isinstance(text,str) or not re.fullmatch(r'[A-Za-z0-9_-]+',text):
        raise ActivationError('激活码格式不正确，请完整复制。')
    try:
        return base64.b64decode(text+'='*(-len(text)%4),altchars=b'-_',validate=True)
    except (ValueError,binascii.Error) as exc:
        raise ActivationError('激活码格式不正确，请完整复制。') from exc


def machine_code(identity=None):
    if identity is None:
        if sys.platform != 'win32': raise ActivationError('机器码目前仅支持 Windows。')
        import winreg
        try:
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,r'SOFTWARE\Microsoft\Cryptography',
                                0,winreg.KEY_READ|winreg.KEY_WOW64_64KEY) as key:
                identity=winreg.QueryValueEx(key,'MachineGuid')[0]
        except OSError as exc:
            raise ActivationError('无法读取 Windows 设备标识，请检查系统权限。') from exc
    try:
        identity=str(uuid.UUID(str(identity).strip()))
    except (ValueError,AttributeError) as exc:
        raise ActivationError('Windows 设备标识无效。') from exc
    digest=hashlib.sha256(b'DFViewer machine v1\0'+identity.encode('ascii')).digest()[:20]
    body=base64.b32encode(digest).decode('ascii')
    checksum=hashlib.sha256(('DFV1:'+body).encode('ascii')).hexdigest()[:4].upper()
    return 'DFV1-'+'-'.join(body[i:i+8] for i in range(0,32,8))+'-'+checksum


def normalize_machine(text):
    compact=re.sub(r'[\s-]+','',str(text).upper())
    if not re.fullmatch(r'DFV1[A-Z2-7]{32}[0-9A-F]{4}',compact):
        raise ActivationError('请完整复制模型查看器中 DFV1 开头的机器码。')
    body,checksum=compact[4:36],compact[36:]
    if hashlib.sha256(('DFV1:'+body).encode('ascii')).hexdigest()[:4].upper()!=checksum:
        raise ActivationError('机器码校验失败，请重新复制。')
    return 'DFV1-'+'-'.join(body[i:i+8] for i in range(0,32,8))+'-'+checksum


def canonical(claims):
    return json.dumps(claims,sort_keys=True,separators=(',',':'),ensure_ascii=True).encode('ascii')


def valid_name(name):
    return (isinstance(name,str) and name==name.strip() and 1<=len(name)<=80
            and not re.search(r'[\x00-\x1f\x7f-\x9f\ud800-\udfff]',name))


def verify(token,machine,public_key,*,now=None):
    token=re.sub(r'\s+','',str(token))
    if len(token)>8192: raise ActivationError('激活码过长，请检查复制的内容。')
    parts=token.split('.')
    if len(parts)!=3 or parts[0]!='DFVA1':
        raise ActivationError('请输入模型查看器 DFVA1. 开头的完整激活码。')
    payload,signature=unb64(parts[1]),unb64(parts[2])
    try:
        Ed25519PublicKey.from_public_bytes(public_key).verify(signature,DOMAIN+payload)
    except (InvalidSignature,ValueError) as exc:
        raise ActivationError('激活码签名无效，请完整复制或联系软件提供者。') from exc
    try:
        claims=json.loads(payload)
        valid=(isinstance(claims,dict) and set(claims)=={'v','product','machine','name','issued_at','expires_at'}
               and type(claims['v']) is int and claims['v']==1 and claims['product']==PRODUCT
               and valid_name(claims['name']) and type(claims['issued_at']) is int
               and 0<=claims['issued_at']<=MAX_TIME and canonical(claims)==payload
               and (claims['expires_at'] is None or (type(claims['expires_at']) is int
                    and claims['issued_at']<claims['expires_at']<=MAX_TIME)))
    except (ValueError,UnicodeError,TypeError):
        valid=False
    if not valid: raise ActivationError('激活码授权信息无效或版本不兼容。')
    if claims['machine']!=normalize_machine(machine):
        raise ActivationError('此激活码不属于本机，请使用当前机器码重新签发。')
    current=time.time() if now is None else now
    if claims['issued_at']>current+CLOCK_TOLERANCE:
        raise ActivationError('当前系统时间早于签发时间，请校准系统时间。')
    if claims['expires_at'] is not None and current>=claims['expires_at']:
        raise ActivationError('授权已到期（'+format_time(claims['expires_at'])+'），请联系软件提供者续期。')
    return claims


def format_time(value):
    if value is None: return '永久有效'
    instant=datetime.fromtimestamp(value,tz=timezone.utc)
    try: instant=instant.astimezone()
    except OSError: pass
    return instant.strftime('%Y-%m-%d %H:%M:%S %Z')


def public_config():
    root=Path(getattr(sys,'_MEIPASS',Path(__file__).resolve().parents[1]))
    try:
        config=json.loads((root/'assets/activation-public.json').read_text(encoding='utf-8'))
        if config['algorithm']!='Ed25519' or len(unb64(config['public_key']))!=32: raise ValueError('key')
        if not config['issuer_url'].startswith('https://'): raise ValueError('url')
        return config
    except (OSError,KeyError,ValueError,TypeError) as exc:
        raise ActivationError('软件缺少有效的激活公钥，请重新下载完整软件。') from exc


def license_path():
    base=Path(os.environ.get('LOCALAPPDATA',str(Path.home())))
    current=base/'VertexViewer/activation.json'
    # 旧版本把激活记录放在 DFViewer 目录，升级后继续沿用已有授权。
    legacy=base/'DFViewer/activation.json'
    if not current.exists() and legacy.exists(): return legacy
    return current


def _record(path):
    path=Path(path)
    if not path.exists(): raise ActivationError('请先激活模型查看器。')
    try:
        if path.stat().st_size>16384: raise ValueError('record size')
        record=json.loads(path.read_text(encoding='utf-8'))
        if record['schema']!=1 or not isinstance(record['token'],str): raise ValueError('record')
        if type(record['last_seen']) is not int or record['last_seen']<0: raise ValueError('clock')
        return record
    except (OSError,KeyError,TypeError,ValueError) as exc:
        raise ActivationError('本机激活记录损坏，请重新输入激活码。') from exc


def _write(path,token,seen):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    temporary=path.with_name(path.name+'.'+uuid.uuid4().hex+'.tmp')
    try:
        with temporary.open('x',encoding='utf-8') as stream:
            json.dump(dict(schema=1,token=re.sub(r'\s+','',token),last_seen=int(seen)),stream)
            stream.flush();os.fsync(stream.fileno())
        os.replace(temporary,path)
    finally:
        temporary.unlink(missing_ok=True)


def saved_license(machine,public_key,path=None,*,now=None,touch=False):
    path=Path(path or license_path());record=_record(path)
    current=time.time() if now is None else now
    claims=verify(record['token'],machine,public_key,now=current)
    if current+CLOCK_TOLERANCE<record['last_seen']:
        raise ActivationError('检测到系统时间回退，请校准时间后重新启动。')
    if touch and current-record['last_seen']>=60:
        _write(path,record['token'],current)
    return claims


def save_license(token,machine,public_key,path=None,*,now=None):
    current=time.time() if now is None else now
    claims=verify(token,machine,public_key,now=current)
    path=Path(path or license_path())
    try: seen=_record(path)['last_seen']
    except ActivationError: seen=0
    if current+CLOCK_TOLERANCE<seen:
        raise ActivationError('检测到系统时间回退，请先校准系统时间。')
    _write(path,token,max(seen,current))
    return claims


def status(*,now=None,touch=False):
    try:
        config=public_config()
        return saved_license(machine_code(),unb64(config['public_key']),now=now,touch=touch),''
    except (ActivationError,OSError) as exc:
        return None,str(exc)
