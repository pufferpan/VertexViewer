"""Owner-only issuance; private keys are never included in application builds."""
import argparse
from datetime import datetime,timedelta
from pathlib import Path
import sys
import time
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from core import activation


def load_key(path):
    key=serialization.load_pem_private_key(Path(path).read_bytes(),password=None)
    if not isinstance(key,Ed25519PrivateKey): raise ValueError('需要配套的 Ed25519 签发私钥。')
    configured=activation.unb64(activation.public_config()['public_key'])
    public=key.public_key().public_bytes(serialization.Encoding.Raw,serialization.PublicFormat.Raw)
    if public!=configured: raise ValueError('私钥与当前模型查看器公钥不匹配。')
    return key


def issue(key,machine,name,expires_at,issued_at=None):
    issued_at=int(time.time()) if issued_at is None else issued_at
    claims=dict(v=1,product=activation.PRODUCT,machine=activation.normalize_machine(machine),
                name=name.strip(),issued_at=issued_at,expires_at=expires_at)
    payload=activation.canonical(claims)
    token='DFVA1.'+activation.b64(payload)+'.'+activation.b64(key.sign(activation.DOMAIN+payload))
    public=key.public_key().public_bytes(serialization.Encoding.Raw,serialization.PublicFormat.Raw)
    activation.verify(token,machine,public,now=issued_at)
    return token


def main():
    parser=argparse.ArgumentParser(description='VertexViewer 管理者授权签发：名称与有效期均签入激活码。')
    parser.add_argument('--private-key',required=True)
    parser.add_argument('--machine',required=True)
    parser.add_argument('--name',required=True)
    period=parser.add_mutually_exclusive_group(required=True)
    period.add_argument('--days',type=int)
    period.add_argument('--expires',help='到期时间 ISO 8601；不含时区时按本机时间。')
    period.add_argument('--forever',action='store_true')
    parser.add_argument('--out',required=True)
    args=parser.parse_args()
    now=int(time.time())
    if args.days is not None:
        if args.days<1: parser.error('--days 必须大于 0')
        expires=now+args.days*86400
    elif args.expires:
        expires=int(datetime.fromisoformat(args.expires).timestamp())
    else: expires=None
    token=issue(load_key(args.private_key),args.machine,args.name,expires,now)
    Path(args.out).write_text(token+'\n',encoding='utf-8')
    print('已签发：'+args.name+' · '+activation.format_time(expires))


if __name__=='__main__': main()
