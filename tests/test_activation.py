import inspect
import json
import os
from pathlib import Path
import tempfile
import time
import subprocess
import unittest
from unittest.mock import patch
from dataclasses import dataclass
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives import serialization
from core import activation as A
from tools.activation_owner import issue

IDENTITY='f77d3076-411b-4b14-a464-e8d76c04f8c9'


def _find_interop():
    override=os.environ.get('VERTEXVIEWER_INTEROP')
    candidates=[Path(override)] if override else []
    here=Path(__file__).resolve()
    for base in list(here.parents)[1:5]:
        candidates.append(base/'dfmap_activation_site/tests/viewer-interop.mjs')
    for candidate in candidates:
        if candidate.is_file(): return candidate
    return candidates[-1]


INTEROP=_find_interop()


class LicenseTests(unittest.TestCase):
    def setUp(self):
        self.key=Ed25519PrivateKey.generate()
        self.public=self.key.public_key().public_bytes(serialization.Encoding.Raw,serialization.PublicFormat.Raw)
        self.machine=A.machine_code(IDENTITY)
        self.config=dict(algorithm='Ed25519',public_key=A.b64(self.public),issuer_url='https://example.com')
        self.token=issue(self.key,self.machine,'授权测试 🙂',2000,1000)

    def test_machine_checksum_product_and_privacy(self):
        self.assertEqual(A.normalize_machine(self.machine.lower()+'\n'),self.machine)
        self.assertNotIn(IDENTITY,self.machine)
        self.assertNotEqual(self.machine,A.machine_code('16eb6cda-b1db-44a8-9904-2218bcb41cc2'))
        for bad in ('',self.machine[:-1]+'Z',self.machine.replace('DFV1','DFM1')):
            with self.assertRaises(A.ActivationError):A.normalize_machine(bad)

    def test_name_and_expiry_are_signed_and_checked(self):
        result=A.verify(self.token,self.machine,self.public,now=1999)
        self.assertEqual((result['name'],result['issued_at'],result['expires_at']),('授权测试 🙂',1000,2000))
        with self.assertRaisesRegex(A.ActivationError,'到期'):A.verify(self.token,self.machine,self.public,now=2000)
        with self.assertRaisesRegex(A.ActivationError,'系统时间'):A.verify(self.token,self.machine,self.public,now=600)
        forever=issue(self.key,self.machine,'永久授权',None,1000)
        self.assertIsNone(A.verify(forever,self.machine,self.public,now=100000)['expires_at'])
        with self.assertRaisesRegex(A.ActivationError,'本机'):
            A.verify(self.token,A.machine_code('16eb6cda-b1db-44a8-9904-2218bcb41cc2'),self.public,now=1000)

    def test_tampering_name_expiry_or_signature_is_rejected(self):
        prefix,payload,signature=self.token.split('.')
        for field,value in (('name','另一个人'),('expires_at',None),('product','OtherViewer')):
            claims=json.loads(A.unb64(payload));claims[field]=value
            token=prefix+'.'+A.b64(A.canonical(claims))+'.'+signature
            with self.assertRaises(A.ActivationError):A.verify(token,self.machine,self.public,now=1000)
        for invalid in ('bad',self.token+'.extra','DFVA1.!.$',self.token[:-20],self.token+'A','x'*9000):
            with self.assertRaises(A.ActivationError):A.verify(invalid,self.machine,self.public,now=1000)

    def test_signed_invalid_schema_names_and_periods_are_rejected(self):
        claims=json.loads(A.unb64(self.token.split('.')[1]))
        for key,value in (('name',''),('name','a\nb'),('name','x'*81),('name',' leading'),
                          ('expires_at',True),('expires_at',1000),('expires_at',A.MAX_TIME+1),('issued_at',True)):
            current=dict(claims);current[key]=value
            payload=A.canonical(current)
            token='DFVA1.'+A.b64(payload)+'.'+A.b64(self.key.sign(A.DOMAIN+payload))
            with self.assertRaises(A.ActivationError):A.verify(token,self.machine,self.public,now=1000)

    def test_saved_license_expiry_renewal_and_clock_rollback(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'activation.json'
            A.save_license(self.token,self.machine,self.public,path,now=1000)
            A.saved_license(self.machine,self.public,path,now=1800,touch=True)
            with self.assertRaisesRegex(A.ActivationError,'回退'):
                A.saved_license(self.machine,self.public,path,now=1200)
            with self.assertRaisesRegex(A.ActivationError,'到期'):
                A.saved_license(self.machine,self.public,path,now=2000)
            newer=issue(self.key,self.machine,'续期用户',4000,2000)
            A.save_license(newer,self.machine,self.public,path,now=2001)
            self.assertEqual(A.saved_license(self.machine,self.public,path,now=2002)['name'],'续期用户')
            with self.assertRaises(A.ActivationError):A.save_license('bad',self.machine,self.public,path,now=2002)
            self.assertEqual(A.saved_license(self.machine,self.public,path,now=2002)['name'],'续期用户')

    @unittest.skipUnless(INTEROP.is_file(), '需要签发站点源码（dfmap_activation_site/tests/viewer-interop.mjs）')
    def test_browser_generated_code_is_accepted_by_python(self):
        pem=self.key.private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,serialization.NoEncryption()).decode('ascii')
        source=INTEROP
        data=dict(pem=pem,public_key=A.b64(self.public),machine=self.machine,
                  claims=dict(name='网页授权 · 测试 🙂',issued_at=1000,expires_at=2000))
        result=subprocess.run(['node',str(source)],input=json.dumps(data),encoding='utf-8',capture_output=True,check=True)
        claims=A.verify(result.stdout,self.machine,self.public,now=1000)
        self.assertEqual(claims['name'],data['claims']['name'])
        self.assertEqual(claims['expires_at'],2000)


class LicenseUiTests(LicenseTests):
    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication
        cls.app=QApplication.instance() or QApplication([])
        cls.app.setQuitOnLastWindowClosed(False)

    def test_native_dialog_and_verified_name_display(self):
        from app.activation import activation_dialog
        from fluentpy import widgets as W
        dialog=activation_dialog(self.machine,self.config,clock=lambda:1000)
        self.addCleanup(dialog.deleteLater)
        self.assertIs(type(dialog),W.FramelessDialog)
        self.assertIs(type(dialog.machine_edit),W.LineEdit)
        self.assertIs(type(dialog.code_edit),W.TextEdit)
        self.assertIs(type(dialog.notice),W.InfoBar)
        dialog.code_edit.setPlainText('bad');dialog.yes_button.click()
        self.assertEqual(dialog.result(),0);self.assertTrue(dialog.notice.detail())
        with tempfile.TemporaryDirectory() as directory,patch.object(A,'license_path',return_value=Path(directory)/'activation.json'):
            dialog.code_edit.setPlainText(self.token)
            self.assertIn('授权测试 🙂',dialog.license_details.text())
            dialog.yes_button.click();self.assertEqual(dialog.result(),dialog.DialogCode.Accepted)
            self.assertEqual(A.status(now=1000)[0],None) # real public key does not trust the test key

    def test_gate_requires_matching_saved_code(self):
        from app.activation import require_activation
        with tempfile.TemporaryDirectory() as directory,patch.object(A,'license_path',return_value=Path(directory)/'activation.json'),\
             patch.object(A,'machine_code',return_value=self.machine),patch.object(A,'public_config',return_value=self.config),\
             patch('app.activation.activation_dialog') as factory:
            factory.return_value.exec.return_value=0;factory.return_value.DialogCode.Accepted=1
            self.assertFalse(require_activation(clock=lambda:1000));factory.assert_called_once();factory.reset_mock()
            A.save_license(self.token,self.machine,self.public,now=1000)
            self.assertTrue(require_activation(clock=lambda:1000));factory.assert_not_called()
            self.assertFalse(require_activation(clock=lambda:2000));factory.assert_called_once()

    def test_running_guard_locks_expired_app_and_uses_monotonic_time(self):
        from app.activation import LicenseGuard
        with patch('app.activation.time.time',return_value=1000),patch('app.activation.time.monotonic',return_value=50):
            guard=LicenseGuard(self.app)
        self.addCleanup(guard.deleteLater);guard.timer.stop()
        with patch('app.activation.time.time',return_value=500),patch('app.activation.time.monotonic',return_value=1050):
            self.assertEqual(guard.current_time(),2000)
        with patch.object(A,'status',return_value=(None,'授权已到期')),patch('app.activation.require_activation',return_value=False) as gate,\
             patch.object(self.app,'quit') as quit_app,patch.object(self.app,'closeAllWindows'):
            guard.check();gate.assert_called_once();quit_app.assert_called_once()
            self.assertFalse(guard.timer.isActive())

    def test_startup_gates_verification_and_environment_shortcuts(self):
        from app.__main__ import main,_run
        self.assertNotIn('--verify-release',inspect.getsource(main))
        source=inspect.getsource(_run)
        gate=source.index('if not require_activation()')
        for entry in ('from app.main_window import VertexViewerWindow',"argv[1]=='--verify-release'",'VERTEXVIEWER_AUTOSHOT','VERTEXVIEWER_NOSPLASH'):
            self.assertLess(gate,source.index(entry))


if __name__=='__main__':unittest.main()
