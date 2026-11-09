"""Discover nearby animations, decode ACL in isolation, and skin real mesh vertices."""
from __future__ import annotations

from dataclasses import dataclass
from bisect import bisect_left
import hashlib
import json
import os
import re
from pathlib import Path, PurePosixPath
import subprocess
import sys
import tempfile

import numpy as np


_VARIANT = re.compile(r'_(?:1p|3p|ui|lay|hd|skin|sk|lod\d+)$', re.I)
_GENERIC_FOLDERS = {'body', 'weapon', 'model', 'models', 'mesh', 'meshes',
                    'animation', 'animations', 'ani', '1p', '3p', 'ui', 'hd'}


def _identity(path):
    stem = PurePosixPath(path).stem.casefold()
    while True:
        bare = _VARIANT.sub('', stem)
        if bare == stem: return stem
        stem = bare


def _group_prefix(vpath):
    parent = PurePosixPath(vpath).parent
    while parent.name.casefold() in _GENERIC_FOLDERS:
        parent = parent.parent
    return str(parent).casefold().rstrip('/') + '/'


def belongs_to_model(model, asset):
    """Keep folder proximity from pairing two different items in a shared folder."""
    prefix = _group_prefix(model)
    if not asset.casefold().startswith(prefix): return False
    model_key, asset_key = _identity(model), _identity(asset)
    model_ids = set(re.findall(r'(?<!\d)\d{4,}(?!\d)', model_key))
    if not model_ids:
        model_ids = set(re.findall(r'(?<!\d)\d{4,}(?!\d)', PurePosixPath(prefix.rstrip('/')).name))
    asset_ids = set(re.findall(r'(?<!\d)\d{4,}(?!\d)', asset[len(prefix):].casefold()))
    if model_ids and asset_ids and not model_ids.intersection(asset_ids): return False
    folder_key = _identity(prefix.rstrip('/') + '.uasset')
    # A dedicated item folder may use generic action names such as Open/Loop.
    if folder_key and (folder_key in model_key or model_key in folder_key): return True
    if model_ids and model_ids.intersection(set(re.findall(r'(?<!\d)\d{4,}(?!\d)', prefix))): return True
    if model_ids and model_ids.intersection(asset_ids): return True
    ignored = {'prop','props','collect','sm','sk','skm','skeletal','static','model','body','weapon'}
    model_words = set(re.split(r'[_\W]+', model_key)) - ignored
    asset_words = set(re.split(r'[_\W]+', asset_key)) - ignored
    return any(len(word) >= 3 and not word.isdigit() for word in model_words.intersection(asset_words))


def related_models(vpath):
    from core import loader
    prefix = _group_prefix(vpath)
    return [p for p,c in loader.catalog().items() if p.casefold().startswith(prefix)
            and 'SkeletalMesh' in c and belongs_to_model(vpath, p)]


_ANIMATION_INDEX = (None, [], [])


def related_animations(vpath, catalog=None):
    global _ANIMATION_INDEX
    from core import loader
    catalog = catalog if catalog is not None else loader.catalog()
    prefix = _group_prefix(vpath)
    if _ANIMATION_INDEX[0] is not catalog:
        pairs = sorted((p.casefold(), p) for p,c in catalog.items()
                       if c in {"AnimSequence", "AnimMontage", "AnimComposite"})
        _ANIMATION_INDEX = (catalog, [p[0] for p in pairs], [p[1] for p in pairs])
    _, keys, paths = _ANIMATION_INDEX
    start, stop = bisect_left(keys, prefix), bisect_left(keys, prefix+'\uffff')
    rows = [(p, PurePosixPath(p).stem, catalog[p], "", "") for p in paths[start:stop]
            if belongs_to_model(vpath, p)]
    return sorted(rows, key=lambda r: (1 if '/body/' in r[0].lower() else 0,
                                      0 if any(t in r[0].lower() for t in ('inspect','check','_ui','_open','_loop')) else 1, r[0]))


def bridge_dir():
    root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[1]))
    return root / "assets" / "animation"


def decode_animation(vpath, cancel=None, *, force_decoder=False):
    from core import loader
    from core.custom_parts import library_dir
    payload = bridge_dir()
    executable = payload / "VertexViewer.AnimationBridge.exe"
    if not executable.exists(): raise RuntimeError("缺少动画解码组件，请使用完整新版程序")
    blobs = loader.load_blobs(vpath)
    digest = hashlib.sha256(b"inspection-v4-resolved-additive" + os.path.realpath(loader.PAK_DIR).encode('utf-8'))
    digest.update((payload/'VertexViewer.AnimationBridge.dll').read_bytes())
    for key in sorted(blobs): digest.update(blobs[key])
    cache = library_dir().parent / "animation-cache" / digest.hexdigest()
    if not force_decoder and (cache / "clips.json").exists(): return read_clips(cache)
    cache.parent.mkdir(parents=True, exist_ok=True)
    # The cache is committed only after every binary clip passes validation.
    with tempfile.TemporaryDirectory(prefix="decode-", dir=cache.parent) as directory:
        tmp = Path(directory)
        cfg = dict(PaksDirectory=loader.PAK_DIR, Recursive=True, KeyFile=loader.data_file("AESKey1.json"),
                   OodlePath=str(payload/"oo2core_9_win64.dll"), Game="GAME_DeltaForce")
        config = tmp / "config.json"
        config.write_text(json.dumps(cfg), encoding="utf-8")
        with (tmp/"decoder.log").open('wb') as log:
            process = subprocess.Popen([str(executable), str(config), vpath, str(tmp)],
                                       stdout=log, stderr=log, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            try:
                import time
                started = time.monotonic()
                while process.poll() is None:
                    if cancel is not None and cancel.is_set(): raise InterruptedError("已取消动画加载")
                    if time.monotonic()-started > 180: raise TimeoutError("动画解码超时")
                    time.sleep(0.05)
            finally:
                if process.poll() is None:
                    process.kill()
                    process.wait()
        if process.returncode:
            detail = (tmp/"decoder.log").read_text(encoding='utf-8', errors='replace')[-1800:]
            raise RuntimeError("无法解码该动作：" + detail)
        clips = read_clips(tmp)
        config.unlink()
        import shutil
        if not cache.exists(): shutil.copytree(tmp, cache)
        return clips


@dataclass
class Clip:
    name: str
    fps: float
    bones: list
    parents: list
    reference: np.ndarray
    poses: np.ndarray
    additive: bool = False

    @property
    def duration(self): return max(0, len(self.poses)-1) / self.fps


def read_clips(folder):
    folder = Path(folder)
    meta = json.loads((folder/"clips.json").read_text(encoding='utf-8'))
    clips = []
    for item in meta['clips']:
        count, frames = len(item['bones']), int(item['frames'])
        fps = float(item['fps'])
        if not (0 < count <= 4096 and 0 < frames <= 30000 and 0 < fps <= 1000):
            raise ValueError("无效的动画元数据")
        path = folder / item['file']
        if path.parent != folder or path.suffix != '.bin': raise ValueError("无效的动画缓存路径")
        poses = np.fromfile(path, '<f4').reshape(frames, count, 10)
        if not np.isfinite(poses).all(): raise ValueError("动画包含无效变换")
        clips.append(Clip(item['name'], fps, item['bones'], item['parents'],
                          np.asarray(item['reference'], np.float32), poses, bool(item.get('additive'))))
    if not clips: raise ValueError("没有可播放的动作")
    return clips


def local_matrices(pose):
    q = np.asarray(pose[:, :4], np.float64)
    q = q / np.maximum(np.linalg.norm(q, axis=1, keepdims=True), 1e-12)
    x,y,z,w = q.T
    m = np.zeros((len(pose),4,4), np.float64)
    m[:,0,0]=1-2*(y*y+z*z); m[:,0,1]=2*(x*y-z*w); m[:,0,2]=2*(x*z+y*w)
    m[:,1,0]=2*(x*y+z*w); m[:,1,1]=1-2*(x*x+z*z); m[:,1,2]=2*(y*z-x*w)
    m[:,2,0]=2*(x*z-y*w); m[:,2,1]=2*(y*z+x*w); m[:,2,2]=1-2*(x*x+y*y)
    m[:,:3,:3] *= pose[:,None,7:10]
    m[:,:3,3]=pose[:,4:7]
    m[:,3,3]=1
    return m


def world_matrices(pose, parents):
    matrices = local_matrices(pose)
    for i,parent in enumerate(parents):
        if parent >= i or parent < -1: raise ValueError("动画骨骼层级无效")
        if parent >= 0: matrices[i] = matrices[parent] @ matrices[i]
    return matrices


def sample_pose(clip, seconds):
    frame = np.clip(seconds*clip.fps, 0, len(clip.poses)-1)
    lo = int(frame); hi = min(lo+1,len(clip.poses)-1); alpha = frame-lo
    a,b = clip.poses[lo],clip.poses[hi]
    pose = a*(1-alpha)+b*alpha
    qa,qb=a[:,:4],b[:,:4].copy()
    qb[np.sum(qa*qb,axis=1)<0]*=-1
    pose[:,:4]=qa*(1-alpha)+qb*alpha
    return pose


class SkinPlayer:
    def __init__(self, mesh, clip):
        self.mesh, self.clip = mesh, clip
        lod = mesh.lods[0]
        if lod.bone_weights is None or mesh.reference_pose is None:
            raise ValueError("这个模型没有可用的骨骼权重，请选择同目录的骨骼模型")
        if clip.additive: raise ValueError("这是叠加动作，需要游戏中的基础姿势；请选择普通检视动作")
        lookup = {n.casefold(): i for i,n in enumerate(clip.bones)}
        self.mapping = np.array([lookup.get(n.casefold(), -1) for n in lod.bones], np.int32)
        used = np.unique(lod.bone_indices[lod.bone_weights > 0])
        if (self.mapping[used] < 0).any(): raise ValueError("动作与模型的骨骼不匹配，请选择同一物品的模型与动作")
        self.original_positions = lod.positions.copy()
        self.original_normals = lod.normals.copy()
        self.original_tangents = None if lod.tangents is None else lod.tangents.copy()
        self.inverse_bind = np.linalg.inv(world_matrices(mesh.reference_pose, mesh.bone_parents))
        self.basis = np.array([[0,.01,0,0],[0,0,.01,0],[-.01,0,0,0],[0,0,0,1]],float)
        self.inverse_basis = np.linalg.inv(self.basis)

    def sample(self, seconds):
        clip = self.clip
        pose = sample_pose(clip, seconds)
        world = world_matrices(pose,clip.parents)
        target = world_matrices(self.mesh.reference_pose,self.mesh.bone_parents)
        present = self.mapping >= 0
        target[present] = world[self.mapping[present]]
        matrices = self.basis @ (target @ self.inverse_bind) @ self.inverse_basis
        lod=self.mesh.lods[0]
        positions=np.zeros_like(self.original_positions)
        normals=np.zeros_like(self.original_normals)
        tangents = None if self.original_tangents is None else np.zeros_like(self.original_tangents[:,:3])
        for influence in range(lod.bone_weights.shape[1]):
            weights=lod.bone_weights[:,influence,None]
            m=matrices[lod.bone_indices[:,influence]]
            positions += (np.einsum('nij,nj->ni',m[:,:3,:3],self.original_positions)+m[:,:3,3])*weights
            normals += np.einsum('nij,nj->ni',m[:,:3,:3],self.original_normals)*weights
            if tangents is not None:
                tangents += np.einsum('nij,nj->ni',m[:,:3,:3],self.original_tangents[:,:3])*weights
        lod.positions=positions
        lod.normals=normals/np.maximum(np.linalg.norm(normals,axis=1,keepdims=True),1e-9)
        if tangents is not None:
            tangents/=np.maximum(np.linalg.norm(tangents,axis=1,keepdims=True),1e-9)
            lod.tangents=np.column_stack([tangents,self.original_tangents[:,3]])
