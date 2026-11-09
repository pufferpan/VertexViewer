"""Pair authored body/item tracks and attach the item to its animated hand joint."""
from copy import copy, deepcopy
from pathlib import PurePosixPath
import re
from functools import lru_cache

import numpy as np

from core.inspection import (SkinPlayer, decode_animation, related_animations,
                             sample_pose, world_matrices)
from core.types import Mesh, ModelBundle


@lru_cache(maxsize=96)
def native_sockets(game_dir,path):
    from core import loader,uasset
    ua=loader.read_entry(path);sibling=loader.siblings(path).get('uexp')
    pkg=uasset.Package(ua,loader.read_entry(sibling) if sibling else None,None,path)
    return [pkg.read_properties(pkg.export_reader(e)) for e in pkg.exports
            if pkg.export_class(e)=='SkeletalMeshSocket']


def camera_mount(mesh_path,clip):
    from core import loader
    from core.sockets import fr_matrix
    bones={n.casefold():i for i,n in enumerate(clip.bones)}
    for path in (mesh_path,mesh_path[:-7]+'_Skeleton.uasset'):
        try:
            for socket in native_sockets(loader.PAK_DIR,path):
                bone=bones.get(str(socket.get('BoneName','')).casefold())
                if str(socket.get('SocketName','')).casefold()=='fppcamera' and bone is not None:
                    matrix=np.eye(4);matrix[:3,:3]=fr_matrix(socket.get('RelativeRotation',(0,0,0)))
                    matrix[:3,3]=socket.get('RelativeLocation',(0,0,0))
                    return dict(bone=bone,local=matrix)
        except (OSError,KeyError,ValueError):pass
    bone=bones.get('camera_joint')
    if bone is not None:
        # Character animation authoring faces +Y; FPPCamera normally declares
        # this exact 90-degree camera socket on Camera_Joint.
        matrix=np.eye(4);matrix[:3,:3]=fr_matrix((0,90,0))
        return dict(bone=bone,local=matrix)
    return None


def action_key(path):
    # UI duplicate numbers are import variants, not different body actions.
    stem=PurePosixPath(path).stem.casefold()
    return re.sub(r'(?:_\d+)?_ui$', '', stem)


def companion_candidates(model_path, animation, index):
    """Exact action identity only; timing and rig are checked before decoding."""
    from core import loader
    key=action_key(animation)
    nearby={r[0] for r in related_animations(model_path,index.catalog)}
    candidates=set(nearby)
    # Shared gun body tracks live outside the receiver directory. Some are
    # absent from the legacy class catalog, but are present in the actual pak.
    if '/models/weapons/' in model_path.casefold():
        for p in loader.index():
            low=p.casefold()
            if low.endswith('.uasset') and '/models/weapons/guns/' in low:
                if action_key(p)==key: candidates.add(p)
    meta=index.metadata(animation)
    if not meta: return []
    out=[]
    for p in sorted(candidates):
        if p==animation or action_key(p)!=key: continue
        m=index.metadata(p)
        if (not m or m['duration']<=0 or m['skeleton']==meta['skeleton']
                or not m['skeleton'].endswith('_1p_skeleton')): continue
        # Different-length Start/Loop/End or magazine variants cannot be paired.
        if abs(m['duration']-meta['duration']) > max(.04,meta['duration']*.015): continue
        out.append(p)
    return sorted(out,key=lambda p:(p not in nearby,p))


def load_companion(record, model_path, index, cancel, bundles=None):
    from core import loader
    result=dict(record,hands_checked=True,hands=None)
    bundles=bundles if bundles is not None else {}
    failures=[]
    for path in companion_candidates(model_path,record['animation'],index):
        if cancel.is_set(): raise InterruptedError()
        try:
            skeleton=index.metadata(path)['skeleton']
            # The skeleton's own first-person mesh gives the authored hand rig;
            # never substitute a whole third-person character or a random skin.
            asset=skeleton.removesuffix('_skeleton')
            mesh_path=next((p for p,c in index.catalog.items() if c=='SkeletalMesh'
                            and ('/game/'+p.split('/Content/',1)[-1].removesuffix('.uasset')).casefold()==asset),None)
            if mesh_path is None: continue
            clips=decode_animation(path,cancel)
            if mesh_path not in bundles: bundles[mesh_path]=loader.load_model(mesh_path)
            bundle=bundles[mesh_path]
            paired=[]
            for item in record['clips']:
                matches=[c for c in clips if not c.additive and abs(c.duration-item.duration)<max(.04,item.duration*.015)
                         and (len(clips)==len(record['clips'])==1 or action_key(c.name)==action_key(item.name))]
                if len(matches)!=1: paired.append(None); continue
                body=matches[0]
                SkinPlayer(bundle.mesh,body)
                joints={n.casefold():i for i,n in enumerate(body.bones)}
                socket=next((joints[n] for n in ('b_ik_gun','weapon_righthand_joint','weapon_lefthand_joint') if n in joints),None)
                paired.append(dict(clip=body,socket=socket,camera=camera_mount(mesh_path,body)) if socket is not None else None)
            if any(paired):
                result['hands']=dict(bundle=bundle,path=mesh_path,animation=path,tracks=paired)
                return result
        except InterruptedError: raise
        except Exception as exc: failures.append(str(exc).splitlines()[0])
    result['hands_note']='配套手臂加载失败：'+failures[0] if failures else '该动作没有可匹配的第一人称手臂资源'
    return result


def item_mount_offset(mesh):
    """Convert the item's authored root reference frame into the hand socket frame.

    UE reference skeletons put the root first. Its bind rotation is already
    represented by the body socket; applying it again turns some props sideways.
    Keep child bone offsets and animation untouched, and derive this from the
    actual item rig rather than applying a fixed rotation to every item.
    """
    return np.linalg.inv(world_matrices(mesh.reference_pose,mesh.bone_parents)[0])


class InspectionScene:
    """Private deforming meshes; immutable sources also feed the GLB exporter."""
    def __init__(self, bundle, clip, hands=None, track=None,*,show_hands=True):
        self.source=bundle
        self.bundle=copy(bundle); self.bundle.mesh=deepcopy(bundle.mesh)
        self.item=SkinPlayer(self.bundle.mesh,clip)
        self.clip=clip
        self.hands_source=hands if show_hands else None
        self.track=track
        self._mount_offset=item_mount_offset(bundle.mesh) if track is not None else None
        self.body=None
        self._body_world=None
        self.display=self.bundle
        if hands is not None and track is not None and show_hands:
            from core.gunsmith import merge
            self.hands=copy(hands); self.hands.mesh=deepcopy(hands.mesh)
            self.body=SkinPlayer(self.hands.mesh,track['clip'])
            lod,materials=merge([(self.bundle.mesh.lods[0],bundle.materials),
                                 (self.hands.mesh.lods[0],hands.materials)])
            self.display=ModelBundle(mesh=Mesh(name=bundle.mesh.name,lods=[lod]),materials=materials,
                                     textures=bundle.textures+hands.textures)
        self.sample(0)

    def sample(self, seconds):
        self.item.sample(seconds)
        if self.track is None:return
        if self.body is not None:self.body.sample(seconds)
        body_clip=self.track['clip']
        world=world_matrices(sample_pose(body_clip,seconds),body_clip.parents)
        self._body_world=world
        transform=self.item.basis @ world[self.track['socket']] @ self._mount_offset @ self.item.inverse_basis
        item=self.bundle.mesh.lods[0]
        item.positions=item.positions @ transform[:3,:3].T+transform[:3,3]
        item.normals=item.normals @ np.linalg.inv(transform[:3,:3])
        item.normals/=np.maximum(np.linalg.norm(item.normals,axis=1,keepdims=True),1e-9)
        if item.tangents is not None:
            item.tangents[:,:3]=item.tangents[:,:3] @ transform[:3,:3].T
        if self.body is None:return
        body=self.hands.mesh.lods[0]
        target=self.display.mesh.lods[0]
        n=item.vertex_count
        target.positions[:n]=item.positions;target.positions[n:]=body.positions
        target.normals[:n]=item.normals;target.normals[n:]=body.normals
        if item.tangents is not None: target.tangents[:n]=item.tangents
        if body.tangents is not None: target.tangents[n:]=body.tangents

    def camera_pose(self):
        mount=self.track.get('camera') if self.track else None
        if mount is None or self._body_world is None:return None
        world=self._body_world[mount['bone']] @ mount['local']
        basis=self.item.basis[:3,:3]
        eye=basis @ world[:3,3]
        forward=basis @ world[:3,0];forward/=np.linalg.norm(forward)
        up=basis @ world[:3,2];up/=np.linalg.norm(up)
        return eye,forward,up
