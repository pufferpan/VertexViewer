"""Fast per-install animation eligibility, based on actual skeleton references."""
from bisect import bisect_left
import hashlib
import json
import os
from pathlib import Path
import threading

from core.inspection import related_animations, belongs_to_model, _group_prefix


class InspectionCatalog:
    def __init__(self, catalog, game_dir):
        self.catalog = catalog
        self.game_dir = game_dir
        self._lock = threading.RLock()
        pairs = sorted((p.casefold(),p) for p,c in catalog.items() if c == 'SkeletalMesh')
        self._mesh_keys = [p[0] for p in pairs]
        self._mesh_paths = [p[1] for p in pairs]
        self._metadata = {}
        self._rows = {}
        digest=hashlib.sha256(b'inspection-eligibility-v1')
        digest.update(os.path.normcase(os.path.abspath(game_dir)).encode('utf-8'))
        for path in sorted(Path(game_dir).glob('*.pak')):
            stat=path.stat()
            digest.update(f'{path.name}:{stat.st_size}:{stat.st_mtime_ns}'.encode('utf-8'))
        digest.update(json.dumps(catalog,sort_keys=True).encode('utf-8'))
        root=Path(os.environ.get('LOCALAPPDATA',str(Path.home()))) / 'VertexViewer' / 'inspection-index'
        self.cache_path=root/(digest.hexdigest()+'.json')
        try:
            data=json.loads(self.cache_path.read_text(encoding='utf-8'))
            self._metadata=data.get('assets',{})
        except (OSError,ValueError,TypeError):
            pass

    def metadata(self, path):
        with self._lock:
            if path in self._metadata:
                cached=self._metadata[path]
                if cached.get('skeleton') or self.catalog.get(path) in ('SkeletalMesh','StaticMesh','AnimSequence','AnimMontage','AnimComposite'):
                    return cached
        from core import loader,uasset
        result=None
        try:
            ua=loader.read_entry(path)
            sibling=loader.siblings(path).get('uexp')
            ue=loader.read_entry(sibling) if sibling else None
            package=uasset.Package(ua,ue,None,path)
            # Legacy catalog can name an embedded animation notify class as the
            # package class. Always prefer the actual top-level animation/mesh.
            classes=('SkeletalMesh','StaticMesh','AnimSequence','AnimMontage','AnimComposite')
            exports=[e for e in package.exports if e.outer_index==0 and package.export_class(e) in classes]
            if not exports:exports=package.find_exports(self.catalog.get(path,'AnimSequence'))
            export=next((e for e in exports if e.outer_index==0),exports[0])
            props=package.read_properties(package.export_reader(export))
            additive=props.get('AdditiveAnimType',0)
            if isinstance(additive,dict): additive=additive.get('value',0)
            additive=str(additive).casefold().split('::')[-1] not in ('0','none','aat_none','')
            skeleton=str(props.get('Skeleton') or '').split('.')[0].casefold()
            result=dict(skeleton=skeleton,additive=additive,
                        frames=int(props.get('NumFrames',0)),duration=float(props.get('SequenceLength',0)))
            with self._lock: self._metadata[path]=result
        except Exception:
            # A missing/temporarily unreadable pak is not a durable negative.
            return None
        return result

    def mesh_skeletons(self,path):
        models=[path] if self.catalog.get(path)=='SkeletalMesh' else []
        if models:
            primary=self.metadata(path)
            if primary and primary['skeleton']: return {primary['skeleton']}
        prefix=_group_prefix(path)
        a,b=bisect_left(self._mesh_keys,prefix),bisect_left(self._mesh_keys,prefix+'\uffff')
        models.extend(p for p in self._mesh_paths[a:b] if p!=path and belongs_to_model(path,p))
        out=set()
        for model in models:
            meta=self.metadata(model)
            if meta and meta['skeleton']: out.add(meta['skeleton'])
        return out

    def animations(self,path):
        with self._lock:
            if path in self._rows: return self._rows[path]
        candidates=related_animations(path,self.catalog)
        if not candidates: return []
        skeletons=self.mesh_skeletons(path)
        if not skeletons: return []
        rows=[]
        complete=True
        for row in candidates:
            meta=self.metadata(row[0])
            if meta is None:
                complete=False
                continue
            if not meta['skeleton'] or meta['skeleton'] not in skeletons or meta['additive']:
                continue
            if meta['duration']<=0 or (self.catalog[row[0]]=='AnimSequence' and not 1<meta['frames']<=30000):
                continue
            rows.append(row)
        if complete:
            with self._lock: self._rows[path]=rows
        return rows

    def save(self):
        with self._lock:
            self.cache_path.parent.mkdir(parents=True,exist_ok=True)
            temporary=self.cache_path.with_suffix('.'+str(threading.get_ident())+'.tmp')
            temporary.write_text(json.dumps(dict(assets=self._metadata),ensure_ascii=False),encoding='utf-8')
            os.replace(temporary,self.cache_path)


_INSTANCE=None
_INSTANCE_LOCK=threading.Lock()


def inspection_catalog():
    global _INSTANCE
    from core import loader
    catalog=loader.catalog()
    with _INSTANCE_LOCK:
        if _INSTANCE is None or _INSTANCE.catalog is not catalog or _INSTANCE.game_dir!=loader.PAK_DIR:
            _INSTANCE=InspectionCatalog(catalog,loader.PAK_DIR)
    return _INSTANCE


def playable_animations(path):
    return inspection_catalog().animations(path)


def reset_catalog():
    global _INSTANCE
    with _INSTANCE_LOCK: _INSTANCE=None


def inspectable_paths(paths=None,progress=None,cancel=None):
    index=inspection_catalog()
    candidates=paths if paths is not None else index.catalog
    paths=[p for p in candidates if index.catalog.get(p) in ('StaticMesh','SkeletalMesh')]
    result=set()
    for i,path in enumerate(paths):
        if cancel and cancel(): return result
        if index.animations(path): result.add(path)
        if progress and (i%100==0 or i+1==len(paths)): progress(i+1,len(paths))
    try:
        index.save()
    except OSError:
        # A read-only profile must not hide otherwise valid inspectable models.
        pass
    return result
