"""Walk the cooked asset's actual native metadata, without header scanning."""
import sys,struct
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from core import loader,uasset

name=sys.argv[1] if len(sys.argv)>1 else 'M_Kai_Haavk_049_Body_3P_HD'
vp=next(p for p in loader.index() if p.endswith('/'+name+'.uasset'))
b=loader.load_blobs(vp);p=uasset.Package(b['uasset'],b.get('uexp'),b.get('ubulk'),vp)
ex=p.find_exports('SkeletalMesh')[0];r=p.export_reader(ex);props=p.read_properties(r);raw=p.virtual();o=r.pos+34
def i():
 global o
 v=struct.unpack_from('<i',raw,o)[0];o+=4;return v
def array(stride):
 global o
 n=i();assert 0<=n<1000000,(o,n);o+=stride*n;return n
n=i()
for _ in range(n):
 o+=12;imported=i();o+=8*imported;o+=24
print('MAT',n,'REF start',o)
for stride in (12,40,12):print('REF ARRAY',stride,array(stride),o)
print('COOKED',i(),'LODS',i(),o)
for lod in range(10):
 try:
  print('LOD',lod,'start',o,'flags',raw[o:o+2].hex());o+=2
  print('OUT',i(),'INLINED',i(),'required',array(2));ns=i();print('SECTIONS',ns,o)
  assert 0<ns<128
  for j in range(ns):
   st=o;flags=raw[o:o+2];o+=2;mat=struct.unpack_from('<h',raw,o)[0];o+=2;base=i();tri=i();recompute=i();mask=raw[o];o+=4;shadow=i();vb=i()
   cloth=array(64);bones=array(2);num=i();infs=i();o+=22
   if not(flags[1]&1):array(4);array(8)
   disabled=i();print('SEC',j,mat,base,tri,vb,num,cloth,bones,infs,disabled,'length',o-st)
  print('ACTIVE',array(2));size=i();start=o
  print('BUFF',size,start,'next',start+size,'bytes',raw[start:start+16].hex(' '));o=start+size
 except Exception as exc:
  print('STOP',o,repr(exc));break
