"""Probe the actual DF render-section layout against all vertex/index bounds."""
import struct
import sys
from pathlib import Path
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core import loader, uasset, mesh

name = sys.argv[1] if len(sys.argv)>1 else 'M_Kai_Haavk_049_Body_3P_HD'
vp=next(p for p in loader.index() if p.endswith('/'+name+'.uasset'))
b=loader.load_blobs(vp); pkg=uasset.Package(b['uasset'],b.get('uexp'),b.get('ubulk'),vp)
exp=pkg.find_exports('SkeletalMesh')[0];r=pkg.export_reader(exp);props=pkg.read_properties(r)
raw=pkg.virtual();heads=mesh._find_position_headers(raw,r.pos,r.end)
pos,nv=heads[0];lead=mesh._locate_leading_container(raw,pos,r.pos,nv); total=lead[2]//3
stop=lead[0]-4
def i(o):return struct.unpack_from('<i',raw,o)[0]
def read_section(o,ray=4,nested=False,dfgap=3):
 start=o;flags=raw[o:o+2];mat=struct.unpack_from('<h',raw,o+2)[0];base=i(o+4);tris=i(o+8);o+=12
 if mat<0 or mat>31 or base<0 or base%3 or tris<1 or tris>total:return
 if i(o) not in (0,1):return
 o+=4+1+dfgap
 if i(o) not in (0,1):return
 o+=4
 if ray and i(o) not in (0,1):return
 o+=ray;vbase=i(o);o+=4
 if vbase<0 or vbase>=nv:return
 count=i(o);o+=4
 if count<0 or count>8:return
 if nested:
  for _ in range(count):
   c=i(o);o+=4
   if c<0 or c>nv:return
   o+=c*64
 else:o+=count*64
 nb=i(o);o+=4
 if nb<0 or nb>512:return
 bones=np.frombuffer(raw,dtype='<u2',count=nb,offset=o);o+=2*nb
 if nb and bones.max()>2000:return
 num=i(o);inf=i(o+4);o+=8
 if num<=0 or vbase+num>nv or inf<1 or inf>16:return
 o+=2+20
 if not(flags[1]&1):
  a=i(o);o+=4
  if a<0 or a>nv*10:return
  o+=a*4;b=i(o);o+=4
  if b<0 or b>nv*10:return
  o+=b*8
 if i(o) not in (0,1):return
 o+=4
 return o,(mat,base,tris,vbase,num,nb,flags.hex(),o-start)

hits=[]
for off in range(r.pos,stop-80):
 if raw[off+4:off+8]!=b'\0'*4:continue
 for ray in (4,0):
  for nested in (False,True):
   try:
    first=read_section(off,ray,nested)
    if not first or first[1][3]!=0:continue
    end,sec=first;secs=[sec];count=struct.unpack_from('<i',raw,off-4)[0]
    if not 1<=count<=32:continue
    for _ in range(count-1):
     got=read_section(end,ray,nested)
     if not got:break
     end,sec=got;secs.append(sec)
    if len(secs)==count and sum(s[2] for s in secs)==total and sum(s[4] for s in secs)==nv:
     hits.append((off,ray,nested,end,secs))
   except (IndexError,ValueError,struct.error):pass
print('HEAD',r.pos,pos,nv,total,'HITS',len(hits))
for hit in hits:print(hit)
