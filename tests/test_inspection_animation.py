"""Round-trip skeletal transforms, hand attachment and safe animation output."""
from copy import deepcopy
from io import BytesIO
import json
from pathlib import Path
import struct
import tempfile
import threading
import unittest
from unittest.mock import patch

import numpy as np

from core.inspection import Clip, SkinPlayer, world_matrices
from core.inspection_scene import InspectionScene, action_key, companion_candidates, load_companion
from core.types import Mesh,MeshLOD,ModelBundle,Section
from exporters.animation_glb import export_animation,gl_pose


def read_glb(path):
    raw=Path(path).read_bytes()
    magic,version,length=struct.unpack_from('<III',raw)
    assert magic==0x46546c67 and version==2 and length==len(raw)
    size,kind=struct.unpack_from('<II',raw,12);assert kind==0x4e4f534a
    doc=json.loads(raw[20:20+size]);binary=raw[28+size:]
    return doc,binary


def accessor(doc,binary,index):
    a=doc['accessors'][index];v=doc['bufferViews'][a['bufferView']]
    width={'SCALAR':1,'VEC2':2,'VEC3':3,'VEC4':4,'MAT4':16}[a['type']]
    return np.frombuffer(binary,{5126:'<f4',5123:'<u2',5125:'<u4'}[a['componentType']],
                         a['count']*width, v.get('byteOffset',0)+a.get('byteOffset',0)).reshape(-1,width)


def imported_vertices(doc,binary,seconds):
    """Evaluate a GLB independently from source rigs, including scene hierarchy."""
    poses=np.tile([0,0,0,1,0,0,0,1,1,1],(len(doc['nodes']),1)).astype(float)
    parents=[-1]*len(poses)
    for i,node in enumerate(doc['nodes']):
        for child in node.get('children',[]):parents[child]=i
        poses[i,:4]=node.get('rotation',[0,0,0,1]);poses[i,4:7]=node.get('translation',[0,0,0]);poses[i,7:]=node.get('scale',[1,1,1])
    for channel in doc['animations'][0]['channels']:
        sampler=doc['animations'][0]['samplers'][channel['sampler']]
        times=accessor(doc,binary,sampler['input']).ravel()
        values=accessor(doc,binary,sampler['output'])
        frame=int(np.argmin(abs(times-seconds)))
        target=channel['target'];sl={'translation':slice(4,7),'rotation':slice(0,4),'scale':slice(7,10)}[target['path']]
        poses[target['node'],sl]=values[frame]
    local=world_matrices(poses,[-1]*len(poses))
    for i,node in enumerate(doc['nodes']):
        if 'matrix' in node:local[i]=np.array(node['matrix']).reshape(4,4).T
    world=np.empty_like(local)
    for i,parent in enumerate(parents):
        world[i]=local[i] if parent<0 else world[parent] @ local[i]
    result=[]
    for node in doc['nodes']:
        if 'mesh' not in node:continue
        primitive=doc['meshes'][node['mesh']]['primitives'][0]
        attrs=primitive['attributes'];skin=doc['skins'][node['skin']]
        positions=accessor(doc,binary,attrs['POSITION'])
        bind=accessor(doc,binary,skin['inverseBindMatrices']).reshape(-1,4,4).transpose(0,2,1)
        transforms=world[skin['joints']] @ bind
        output=np.zeros_like(positions)
        for slot in range(2):
            if 'JOINTS_'+str(slot) not in attrs:continue
            joints=accessor(doc,binary,attrs['JOINTS_'+str(slot)])
            weights=accessor(doc,binary,attrs['WEIGHTS_'+str(slot)])
            for j in range(4):
                matrix=transforms[joints[:,j]]
                output+=(np.einsum('nij,nj->ni',matrix[:,:3,:3],positions)+matrix[:,:3,3])*weights[:,j,None]
        result.append(output)
    return result


def fixture():
    ref=np.tile([0,0,0,1,0,0,0,1,1,1],(2,1)).astype(np.float32)
    ref[1,4]=12
    poses=np.tile(ref,(3,1,1));poses[1,0,6]=20;poses[2,0,6]=40
    poses[1,1,:4]=[0,0,np.sin(.3),np.cos(.3)]
    clip=Clip('Item_1P_Inspect',2,['Root','b_IK_Gun'],[-1,0],ref,poses)
    lod=MeshLOD(positions=np.array([[0,0,0],[.1,0,0],[0,.1,0]],np.float32),
                normals=np.tile([0,0,1],(3,1)).astype(np.float32),uvs=np.zeros((3,2),np.float32),
                indices=np.array([0,1,2],np.uint32),sections=[Section(num_triangles=1)],
                bone_indices=np.tile([0,1,0,1,0,1,0,1],(3,1)).astype(np.uint16),
                bone_weights=np.tile([.25,.25,0,0,.25,.25,0,0],(3,1)).astype(np.float32),bones=clip.bones)
    bundle=ModelBundle(mesh=Mesh(name='test',lods=[lod],reference_pose=ref,bone_parents=clip.parents))
    return bundle,clip


class AnimationTests(unittest.TestCase):
    def test_coordinate_basis_with_nonuniform_scale(self):
        bundle,clip=fixture();p=clip.poses[1].copy();p[:,7:]=[.6,1.7,2.1]
        player=SkinPlayer(bundle.mesh,clip)
        np.testing.assert_allclose(world_matrices(gl_pose(p),clip.parents),
                                   player.basis @ world_matrices(p,clip.parents) @ player.inverse_basis,atol=2e-6)

    def test_paired_animation_roundtrip_eight_weights(self):
        bundle,clip=fixture();hands=deepcopy(bundle);track=dict(clip=clip,socket=1)
        original=bundle.mesh.lods[0].positions.copy()
        scene=InspectionScene(bundle,clip,hands,track)
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'检视.glb'
            stats=export_animation(bundle,clip,path,hands=hands,track=track)
            self.assertEqual(stats['actors'],2)
            doc,binary=read_glb(path)
            self.assertEqual(len(doc['skins']),2)
            for seconds in (0,.5,1):
                scene.sample(seconds);body,item=imported_vertices(doc,binary,seconds)
                np.testing.assert_allclose(item,scene.bundle.mesh.lods[0].positions,atol=2e-6)
                np.testing.assert_allclose(body,scene.hands.mesh.lods[0].positions,atol=2e-6)
        scene.sample(0);first=scene.display.mesh.lods[0].positions.copy()
        scene.sample(.7);scene.sample(0)
        np.testing.assert_array_equal(scene.display.mesh.lods[0].positions,first)
        np.testing.assert_array_equal(bundle.mesh.lods[0].positions,original)

    def test_first_person_camera_uses_authored_joint_and_socket(self):
        from render.viewer import Camera
        bundle,clip=fixture();socket=np.eye(4);socket[:3,3]=[0,3,4]
        track=dict(clip=clip,socket=1,camera=dict(bone=0,local=socket))
        scene=InspectionScene(bundle,clip,bundle,track)
        scene.sample(.5);eye,forward,up=scene.camera_pose()
        np.testing.assert_allclose(eye,[.03,.24,0],atol=1e-6)
        np.testing.assert_allclose(forward,[0,0,-1],atol=1e-6)
        np.testing.assert_allclose(up,[0,1,0],atol=1e-6)
        camera=Camera();camera.set_first_person((eye,forward,up))
        np.testing.assert_allclose(camera.eye(),eye)
        np.testing.assert_allclose(camera.view_matrix() @ np.r_[eye,1],[0,0,0,1],atol=1e-6)
        self.assertAlmostEqual(camera.projection_fov(1),90)
        before=camera.view_matrix().copy();camera.orbit(100,50);camera.pan(10,30,600)
        np.testing.assert_array_equal(before,camera.view_matrix())
        hidden=InspectionScene(bundle,clip,bundle,track,show_hands=False);hidden.sample(.5)
        self.assertIsNone(hidden.body)
        np.testing.assert_allclose(hidden.camera_pose()[0],eye)
        np.testing.assert_allclose(hidden.bundle.mesh.lods[0].positions,scene.bundle.mesh.lods[0].positions)
        camera.frame([0,0,0],1);self.assertIsNone(camera.first_person_pose)
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'camera.glb';export_animation(bundle,clip,path,hands=bundle,track=track)
            doc,_=read_glb(path);self.assertEqual(doc['cameras'][0]['type'],'perspective')
            self.assertTrue(any(n.get('camera')==0 for n in doc['nodes']))

    def test_nonidentity_item_root_is_not_applied_twice_at_hand_socket(self):
        bundle,clip=fixture();hands,body_clip=fixture()
        # Like the chess collectible, the item has an authored -90 Y root.
        # Include translation and scale so only correcting its quaternion fails.
        root=np.array([0,-np.sqrt(.5),0,np.sqrt(.5),3,-7,11,1.2,.8,1.1],np.float32)
        bundle.mesh.reference_pose[0]=root
        clip.reference[0]=root;clip.poses[:,0]=root
        bundle.mesh.lods[0].bone_weights[:]=[1,0,0,0,0,0,0,0]
        track=dict(clip=body_clip,socket=1,camera=dict(bone=0,local=np.eye(4)))
        original=bundle.mesh.lods[0].positions.copy()
        scene=InspectionScene(bundle,clip,hands,track)
        standalone=SkinPlayer(deepcopy(bundle.mesh),clip)
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'root-frame.glb'
            export_animation(bundle,clip,path,hands=hands,track=track)
            doc,binary=read_glb(path)
            for seconds in (0,.5,1):
                scene.sample(seconds)
                socket=world_matrices(body_clip.poses[int(seconds*2)],body_clip.parents)[1]
                # Rest-space vertices contain the authored root. The root's
                # local points must land directly in the body's socket frame.
                B=scene.item.basis
                local=B @ np.linalg.inv(world_matrices(clip.reference,clip.parents)[0]) @ scene.item.inverse_basis
                local_points=original @ local[:3,:3].T+local[:3,3]
                mount=B @ socket @ scene.item.inverse_basis
                expected=local_points @ mount[:3,:3].T+mount[:3,3]
                np.testing.assert_allclose(scene.bundle.mesh.lods[0].positions,expected,atol=2e-6)
                body,item=imported_vertices(doc,binary,seconds)
                np.testing.assert_allclose(item,expected,atol=2e-6)
                np.testing.assert_allclose(body,scene.hands.mesh.lods[0].positions,atol=2e-6)
                np.testing.assert_allclose(scene.camera_pose()[0],B[:3,:3] @ world_matrices(body_clip.poses[int(seconds*2)],body_clip.parents)[0,:3,3],atol=2e-6)
            export_animation(bundle,clip,path)
            doc,binary=read_glb(path)
            standalone.sample(.5)
            np.testing.assert_allclose(imported_vertices(doc,binary,.5)[0],standalone.mesh.lods[0].positions,atol=2e-6)
        np.testing.assert_array_equal(bundle.mesh.lods[0].positions,original)

    def test_gunsmith_preserves_layout_and_moves_magazine_bone(self):
        from core import gunsmith as gs
        from core.gunsmith_animation import assemble_animation
        base,clip=fixture();base.mesh.lods[0].bones=['Root','Mag_point'];clip.bones=['Root','Mag_point']
        part=deepcopy(base);part.mesh.lods[0].bone_weights=None;part.mesh.lods[0].bone_indices=None
        spec=gs.PartSpec(slot='mag',vpath='local-mag',offset=(.1,.2,.3),scale=1.2)
        def plan(*args):return {id(s):np.eye(4) for s,l in args[2]}
        with patch('core.gunsmith.resolve_placements',side_effect=plan),patch('core.gunsmith.part_offset',return_value=np.zeros(3)),patch('core.gunsmith_animation.native_sockets',return_value=[]),patch('core.gunsmith_animation._rig',return_value=(base,'receiver')):
            expected=gs.assemble(base,[(spec,part)],base_vpath='receiver')
            animated=assemble_animation(base,[(spec,part)],'receiver')
        np.testing.assert_allclose(animated.mesh.lods[0].positions,expected.mesh.lods[0].positions)
        self.assertTrue(animated.inspection_assembly)
        self.assertEqual(animated.inspection_parts[0]['bone'],'Mag_point')
        player=SkinPlayer(animated.mesh,clip);player.sample(.5)
        self.assertGreater(np.linalg.norm(animated.mesh.lods[0].positions[-1]-expected.mesh.lods[0].positions[-1]),.01)
        self.assertEqual(spec.socket,'')

    def test_item_only_and_failed_export_preserves_file(self):
        bundle,clip=fixture()
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'item.glb'
            self.assertEqual(export_animation(bundle,clip,path)['actors'],1)
            before=path.read_bytes();bad=deepcopy(clip);bad.additive=True
            with self.assertRaises(ValueError):export_animation(bundle,bad,path)
            self.assertEqual(path.read_bytes(),before)
            self.assertEqual(len(list(Path(folder).iterdir())),1)

    def test_packed_material_textures_are_converted_for_gltf(self):
        from core.types import Material,Texture
        from PIL import Image
        bundle,clip=fixture()
        rgba=np.tile(np.array([20,120,220,255],np.uint8),(2,2,1))
        normal=np.tile(np.array([128,128,0,255],np.uint8),(2,2,1))
        bundle.materials=[Material(name='skin',orm_texture='MRA',normal_texture='NCEmap')]
        bundle.textures=[Texture(pak_path='MRA',rgba=rgba),Texture(pak_path='NCEmap',rgba=normal)]
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'materials.glb';export_animation(bundle,clip,path)
            doc,binary=read_glb(path);material=doc['materials'][0]
            def pixel(info):
                image=doc['images'][doc['textures'][info['index']]['source']]
                view=doc['bufferViews'][image['bufferView']];offset=view['byteOffset']
                return np.asarray(Image.open(BytesIO(binary[offset:offset+view['byteLength']])))[0,0]
            np.testing.assert_array_equal(pixel(material['pbrMetallicRoughness']['metallicRoughnessTexture']),[220,120,20,255])
            self.assertGreater(pixel(material['normalTexture'])[2],250)
        np.testing.assert_array_equal(bundle.textures[0].rgba,rgba)

    def test_pairing_does_not_mix_items_rigs_or_segments(self):
        item='Model/Item/Weapon/Item_1P_Start_003_UI.uasset'
        good='Model/Item/Body/Item_1P_Start.uasset'
        wrong='Model/Other/Body/Other_1P_Start.uasset'
        badrig='Model/Item/Body2/Item_1P_Start.uasset'
        badtime='Model/Item/Body3/Item_1P_Start.uasset'
        class Index:
            catalog={}
            def metadata(self,path):
                return dict(skeleton='item' if path==item else ('other' if path==badrig else 'hands_1p_skeleton'),
                            additive=False,duration=2 if path==badtime else 1)
        with patch('core.inspection_scene.related_animations',return_value=[(p,) for p in (item,good,wrong,badrig,badtime)]),patch('core.loader.index',return_value={}):
            self.assertEqual(companion_candidates('Model/Item',item,Index()),[good])
        self.assertEqual(action_key(item),action_key(good))

    def test_generic_prop_action_does_not_take_another_items_hands(self):
        item='Model/Item/Weapon/Open.uasset'
        unrelated='Models/Other/Body/Open.uasset'
        class Index:
            catalog={}
            def metadata(self,path):return dict(skeleton='item' if path==item else 'hands_1p_skeleton',duration=1,additive=False)
        with patch('core.inspection_scene.related_animations',return_value=[]),patch('core.loader.index',return_value={unrelated:None}):
            self.assertEqual(companion_candidates('Model/Item',item,Index()),[])

    def test_companion_failure_keeps_item_playable_and_cancel_propagates(self):
        bundle,clip=fixture();record=dict(animation='item',clips=[clip],bundle=bundle)
        with patch('core.inspection_scene.companion_candidates',return_value=[]):
            result=load_companion(record,'model',None,threading.Event())
            self.assertIs(result['bundle'],bundle);self.assertIsNone(result['hands'])
        cancel=threading.Event();cancel.set()
        with patch('core.inspection_scene.companion_candidates',return_value=['hands']):
            with self.assertRaises(InterruptedError):load_companion(record,'model',None,cancel)


if __name__=='__main__':unittest.main()
