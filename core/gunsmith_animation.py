"""Keep the current gunsmith layout and bind each accessory to its moving mount."""
from copy import deepcopy
import numpy as np

from core import gunsmith as gs,loader
from core.inspection import related_models
from core.inspection_catalog import inspection_catalog
from core.inspection_scene import native_sockets


def _rig(base,path,cancel):
    mesh=base.mesh;lod=gs._lod0(base)
    index=inspection_catalog()
    if mesh.reference_pose is not None and lod.bone_weights is not None and index.animations(path):return base,path
    paths=related_models(path)
    paths.sort(key=lambda p:('_1p' not in p.casefold(),len(p)))
    for candidate in paths:
        if cancel is not None and cancel.is_set():raise InterruptedError()
        if not index.animations(candidate):continue
        result=loader.load_model(candidate)
        if result.mesh.reference_pose is not None and gs._lod0(result).bone_weights is not None:return result,candidate
    raise ValueError('该主件没有可用于检视的骨骼模型，请选择同枪型的机匣。')


def assemble_animation(base,parts,path,*,cancel=None):
    """Use the same placements/scales as static assembly; never skin a baked pose."""
    base,animation_path=_rig(base,path,cancel)
    parts=[(deepcopy(spec),bundle) for spec,bundle in parts if gs._lod0(bundle) is not None]
    if cancel is not None and cancel.is_set():raise InterruptedError()
    combo=gs.assemble(base,parts,base_vpath=path)
    lod=gs._lod0(base);names=lod.bones;lookup={n.casefold():i for i,n in enumerate(names)}
    default=next((lookup[n] for n in ('s_root','root') if n in lookup),0)
    mounts={}
    for candidate in (path,base.mesh.pak_path):
        try:
            for socket in native_sockets(loader.PAK_DIR,candidate):
                bone=lookup.get(str(socket.get('BoneName','')).casefold())
                if bone is not None:mounts[str(socket.get('SocketName','')).casefold()]=bone
        except (OSError,KeyError,ValueError):pass
    width=max(4,lod.bone_weights.shape[1])
    weights=[np.pad(lod.bone_weights,((0,0),(0,width-lod.bone_weights.shape[1])))]
    indices=[np.pad(lod.bone_indices,((0,0),(0,width-lod.bone_indices.shape[1])))]
    spans=[];offset=lod.vertex_count
    resolved={}
    def mount_bone(spec,seen):
        if id(spec) in resolved:return resolved[id(spec)]
        if id(spec) in seen:return default
        seen=seen|{id(spec)};socket=spec.socket.casefold()
        if socket in lookup:bone=lookup[socket]
        elif socket in mounts:bone=mounts[socket]
        else:
            # Nested attachments follow their selected parent's animated mount.
            owners=[]
            for other,bundle in parts:
                if other is spec:continue
                try:
                    if socket and socket in {n.casefold() for n in gs._sockets.socket_names(other.vpath)}:owners.append(other)
                except (OSError,KeyError,ValueError):pass
            if len(owners)==1:bone=mount_bone(owners[0],seen)
            elif spec.slot=='mag':bone=lookup.get('mag_point',default)
            else:bone=default
        resolved[id(spec)]=bone
        return bone
    for spec,bundle in parts:
        if cancel is not None and cancel.is_set():raise InterruptedError()
        part=gs._lod0(bundle);bone=mount_bone(spec,set());n=part.vertex_count
        w=np.zeros((n,width),np.float32);j=np.zeros((n,width),np.uint16)
        w[:,0]=1;j[:,0]=bone
        weights.append(w);indices.append(j)
        spans.append(dict(path=spec.vpath,slot=spec.slot,start=offset,end=offset+n,bone=names[bone]))
        offset+=n
    combined=combo.mesh.lods[0]
    if offset!=combined.vertex_count:raise ValueError('装配顶点与骨骼绑定数量不一致，已停止检视准备。')
    combined.bones=list(names)
    combined.bone_weights=np.concatenate(weights).astype(np.float32)
    combined.bone_indices=np.concatenate(indices).astype(np.uint16)
    combo.mesh.bone_parents=list(base.mesh.bone_parents)
    combo.mesh.reference_pose=base.mesh.reference_pose.copy()
    combo.mesh.source_format='SkeletalMesh'
    combo.mesh.pak_path=base.mesh.pak_path or path
    combo.inspection_assembly=True
    combo.inspection_path=animation_path
    combo.inspection_parts=spans
    combo.display_name_cn='当前改枪方案'
    return combo
