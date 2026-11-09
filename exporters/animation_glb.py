"""Self-contained glTF 2.0 skeletal animation, including the animated hand socket."""
from io import BytesIO
import json
import os
from pathlib import Path
import struct
import tempfile

import numpy as np
from PIL import Image

from core.inspection import SkinPlayer, world_matrices
from core.inspection_scene import item_mount_offset


def gl_pose(pose):
    """Conjugate UE local TRS into the same reflected metre basis as geometry."""
    p=np.asarray(pose,dtype=np.float32)
    out=p.copy()
    out[...,:4]=p[..., [1,2,0,3]]*[-1,-1,1,1]
    out[...,:4]/=np.maximum(np.linalg.norm(out[...,:4],axis=-1,keepdims=True),1e-12)
    out[...,4:7]=p[..., [5,6,4]]*[.01,.01,-.01]
    out[...,7:10]=p[..., [8,9,7]]
    return out


class _Document:
    def __init__(self):
        self.data=bytearray()
        self.doc=dict(asset=dict(version='2.0',generator='VertexViewer'),scene=0,
                      scenes=[dict(nodes=[])],nodes=[],meshes=[],skins=[],animations=[],
                      accessors=[],bufferViews=[],materials=[],images=[],textures=[])
        self.textures={}

    def blob(self,raw,target=None):
        self.data.extend(b'\0'*(-len(self.data)%4))
        view=dict(buffer=0,byteOffset=len(self.data),byteLength=len(raw))
        if target is not None: view['target']=target
        self.data.extend(raw);self.doc['bufferViews'].append(view)
        return len(self.doc['bufferViews'])-1

    def accessor(self,array,kind,target=None,bounds=False):
        a=np.ascontiguousarray(array)
        component={('f',4):5126,('u',2):5123,('u',4):5125}[(a.dtype.kind,a.dtype.itemsize)]
        item=dict(bufferView=self.blob(a.tobytes(),target),componentType=component,
                  count=len(a),type=kind)
        if bounds:
            item['min']=np.min(a,axis=0).reshape(-1).tolist()
            item['max']=np.max(a,axis=0).reshape(-1).tolist()
        self.doc['accessors'].append(item)
        return len(self.doc['accessors'])-1

    def texture(self,path,textures,role='color'):
        if not path: return None
        key=(path,role)
        if key in self.textures: return self.textures[key]
        texture=next((t for t in textures if t.pak_path==path and t.rgba is not None),None)
        if texture is None: return None
        rgba=np.asarray(texture.rgba,np.uint8)
        if role=='mra':rgba=rgba[:,:,[2,1,0,3]]  # game MRA -> glTF ORM
        elif role=='normal' and ('ncemap' in path.casefold() or texture.source_format.upper() in ('BC5','PF_BC5')):
            rgba=rgba.copy();xy=rgba[:,:,:2].astype(np.float32)/127.5-1
            rgba[:,:,2]=np.rint((np.sqrt(np.maximum(1-np.sum(xy*xy,axis=2),0))*.5+.5)*255).astype(np.uint8)
            rgba[:,:,3]=255
        out=BytesIO();Image.fromarray(rgba).save(out,format='PNG')
        self.doc['images'].append(dict(name=texture.name,bufferView=self.blob(out.getvalue()),mimeType='image/png'))
        self.doc['textures'].append(dict(source=len(self.doc['images'])-1))
        self.textures[key]=len(self.doc['textures'])-1
        return self.textures[key]

    def material(self,material,textures):
        pbr=dict(baseColorFactor=list(material.base_color),metallicFactor=float(np.clip(material.metallic,0,1)),
                 roughnessFactor=float(np.clip(material.roughness,0,1)))
        base=self.texture(material.base_color_texture,textures)
        if base is not None:pbr['baseColorTexture']=dict(index=base)
        item=dict(name=material.name,pbrMetallicRoughness=pbr,doubleSided=material.two_sided,
                  extras=dict(source=material.pak_path))
        normal=self.texture(material.normal_texture,textures,'normal')
        if normal is not None: item['normalTexture']=dict(index=normal)
        orm=self.texture(material.orm_texture,textures,'mra')
        if orm is not None:
            pbr.update(metallicRoughnessTexture=dict(index=orm),metallicFactor=1.0,roughnessFactor=1.0)
            item['occlusionTexture']=dict(index=orm)
        emission=self.texture(material.emissive_texture,textures)
        if emission is not None:
            item['emissiveTexture']=dict(index=emission)
            item['emissiveFactor']=[1,1,1]
        blend=material.blend_mode.casefold()
        if blend=='masked': item.update(alphaMode='MASK',alphaCutoff=.5)
        elif blend in ('translucent','additive','alpha'): item['alphaMode']='BLEND'
        self.doc['materials'].append(item)
        return len(self.doc['materials'])-1

    def actor(self,bundle,clip,animation,parent=None):
        mesh=bundle.mesh;lod=mesh.lods[0]
        player=SkinPlayer(mesh,clip)  # Validate every weighted bone before writing.
        d=self.doc
        first=len(d['nodes'])
        refs=gl_pose(clip.reference)
        for i,name in enumerate(clip.bones):
            pose=refs[i]
            node=dict(name=name,rotation=pose[:4].tolist(),translation=pose[4:7].tolist(),scale=pose[7:10].tolist())
            d['nodes'].append(node)
        roots=[]
        for i,p in enumerate(clip.parents):
            if p>=0:d['nodes'][first+p].setdefault('children',[]).append(first+i)
            elif parent is None:roots.append(first+i)
            else:d['nodes'][parent].setdefault('children',[]).append(first+i)
        d['scenes'][0]['nodes'].extend(roots)
        basis=player.basis
        inv=np.linalg.inv(world_matrices(clip.reference,clip.parents))
        for i,mapping in enumerate(player.mapping):
            if mapping>=0: inv[mapping]=player.inverse_bind[i]
        inv=basis @ inv @ player.inverse_basis
        skin=dict(name=mesh.name,joints=list(range(first,first+len(clip.bones))),
                  inverseBindMatrices=self.accessor(inv.transpose(0,2,1).astype('<f4').reshape(-1,16),'MAT4'))
        d['skins'].append(skin)
        attributes=dict(POSITION=self.accessor(lod.positions.astype('<f4'),'VEC3',34962,True),
                        NORMAL=self.accessor(lod.normals.astype('<f4'),'VEC3',34962))
        if lod.uvs is not None:attributes['TEXCOORD_0']=self.accessor(lod.uvs.astype('<f4'),'VEC2',34962)
        if lod.tangents is not None:
            tangent=lod.tangents.astype('<f4').copy()
            tangent[:,:3]-=lod.normals*np.sum(tangent[:,:3]*lod.normals,axis=1,keepdims=True)
            length=np.linalg.norm(tangent[:,:3],axis=1,keepdims=True)
            if np.all(length>1e-8):
                tangent[:,:3]/=length
                tangent[:,3]=np.where(tangent[:,3]<0,-1,1)
                attributes['TANGENT']=self.accessor(tangent,'VEC4',34962)
        # Keep all influences, including meshes with eight weights per vertex.
        weights=np.asarray(lod.bone_weights,np.float32)
        weights=weights/np.maximum(weights.sum(axis=1,keepdims=True),1e-12)
        joints=player.mapping[lod.bone_indices]
        for slot,start in enumerate(range(0,weights.shape[1],4)):
            w=weights[:,start:start+4];j=joints[:,start:start+4]
            if w.shape[1]<4:
                w=np.pad(w,((0,0),(0,4-w.shape[1])))
                j=np.pad(j,((0,0),(0,4-j.shape[1])))
            j=np.where(w>0,j,0)
            attributes['JOINTS_'+str(slot)]=self.accessor(np.maximum(j,0).astype('<u2'),'VEC4',34962)
            attributes['WEIGHTS_'+str(slot)]=self.accessor(w.astype('<f4'),'VEC4',34962)
        from core.types import Material,Section
        materials=bundle.materials
        by_path={m.pak_path:m for m in materials}
        primitives=[]
        for i,section in enumerate(lod.sections or [Section(num_triangles=lod.triangle_count)]):
            indices=np.asarray(lod.indices[section.first_index:section.first_index+section.num_triangles*3],'<u4')
            if not len(indices):continue
            if indices.max()>=lod.vertex_count:raise ValueError('模型包含越界三角面')
            mat=by_path.get(section.material_path) or (materials[min(i,len(materials)-1)] if materials else Material(name='Default'))
            primitives.append(dict(attributes=attributes,indices=self.accessor(indices,'SCALAR',34963),
                                   material=self.material(mat,bundle.textures)))
        if not primitives:raise ValueError('模型没有可导出的三角面')
        d['meshes'].append(dict(name=mesh.name,primitives=primitives))
        node=len(d['nodes']);d['nodes'].append(dict(name=mesh.name,mesh=len(d['meshes'])-1,skin=len(d['skins'])-1,
                                                  extras=dict(source=mesh.pak_path)))
        d['scenes'][0]['nodes'].append(node)
        poses=gl_pose(clip.poses)
        # Consistent signs prevent interpolation across opposite quaternion hemispheres.
        for i in range(1,len(poses)):
            flip=np.sum(poses[i,:,:4]*poses[i-1,:,:4],axis=1)<0
            poses[i,flip,:4]*=-1
        times=self.accessor((np.arange(len(poses),dtype='<f4')/clip.fps),'SCALAR',bounds=True)
        for bone in range(len(clip.bones)):
            for path,sl,kind in [('translation',slice(4,7),'VEC3'),('rotation',slice(0,4),'VEC4'),('scale',slice(7,10),'VEC3')]:
                values=poses[:,bone,sl]
                output=self.accessor(values.astype('<f4'),kind)
                sampler=len(animation['samplers'])
                animation['samplers'].append(dict(input=times,output=output,interpolation='LINEAR'))
                animation['channels'].append(dict(sampler=sampler,target=dict(node=first+bone,path=path)))
        return first


def export_animation(bundle,clip,path,*,hands=None,track=None):
    """Atomically write current action, rest geometry, textures and both animated rigs."""
    writer=_Document();animation=dict(name=clip.name,samplers=[],channels=[])
    parent=None
    if hands is not None and track is not None:
        first=writer.actor(hands,track['clip'],animation)
        socket=first+track['socket']
        basis=np.array([[0,.01,0,0],[0,0,.01,0],[-.01,0,0,0],[0,0,0,1]],float)
        mount=basis @ item_mount_offset(bundle.mesh) @ np.linalg.inv(basis)
        parent=len(writer.doc['nodes'])
        writer.doc['nodes'].append(dict(name='ItemMount',matrix=mount.T.reshape(-1).tolist()))
        writer.doc['nodes'][socket].setdefault('children',[]).append(parent)
        camera=track.get('camera')
        if camera is not None:
            local=basis @ camera['local'] @ np.linalg.inv(basis)
            writer.doc['cameras']=[dict(name='第一人称检视相机',type='perspective',
                                        perspective=dict(yfov=float(np.deg2rad(60)),znear=.003))]
            node=len(writer.doc['nodes'])
            writer.doc['nodes'].append(dict(name='FPPCamera',camera=0,matrix=local.T.reshape(-1).tolist()))
            writer.doc['nodes'][first+camera['bone']].setdefault('children',[]).append(node)
    writer.actor(bundle,clip,animation,parent)
    d=writer.doc;d['animations'].append(animation)
    d['buffers']=[dict(byteLength=len(writer.data))]
    for key in ('materials','images','textures'):
        if not d[key]:d.pop(key)
    metadata=json.dumps(d,ensure_ascii=False,separators=(',',':'),allow_nan=False).encode('utf-8')
    metadata+=b' '*(-len(metadata)%4)
    writer.data.extend(b'\0'*(-len(writer.data)%4))
    path=Path(path).resolve();path.parent.mkdir(parents=True,exist_ok=True)
    tmp=None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent,prefix='.animation-',suffix='.tmp',delete=False) as f:
            tmp=f.name
            f.write(struct.pack('<III',0x46546c67,2,12+8+len(metadata)+8+len(writer.data)))
            f.write(struct.pack('<II',len(metadata),0x4e4f534a));f.write(metadata)
            f.write(struct.pack('<II',len(writer.data),0x004e4942));f.write(writer.data)
        os.replace(tmp,path);tmp=None
    finally:
        if tmp:os.unlink(tmp)
    return dict(path=str(path),bytes=path.stat().st_size,frames=len(clip.poses),duration=clip.duration,
                actors=2 if parent is not None else 1)
