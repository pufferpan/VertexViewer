# VertexViewer animation bridge

The viewer decodes game animations in a separate read-only process so native
codec failures cannot close the Qt application. The bridge mounts the configured
game through the pinned exporter/CUE4Parse SDK, decodes ACL tracks, and writes local
UE transforms for the Python CPU skinning player. It never changes game files.

The body/item inspection player pairs exact action names and duration, selects
the original first-person hand skeleton and uses its animated `b_IK_Gun` /
weapon hand joint. The pinned SDK resolves additive tracks against their authored
reference animation; the bridge detects that completed conversion and preserves
the inspected asset's original duration instead of the short reference pose's
duration. Unresolved additive tracks remain rejected. The cache includes the
bridge assembly hash so decoder updates cannot reuse incompatible cached clips.

`exporters/animation_glb.py` exports rest geometry, all weight influences,
the two skeletons, the animated attachment hierarchy and original frame samples
into one GLB. Base color, normal, emissive and converted MRA textures are embedded.
It exports the selected segment and uses source frame rate, independent of the
viewer's playback speed. `tools/verify_inspection_hands.py` performs a bounded
real-resource and native FluentPy UI check without loading the full model library.

Build with the .NET 10 SDK, specifying the directory containing the managed SDK
assemblies recorded in `sdk-manifest.json`:

```powershell
dotnet publish tools/animation_bridge -c Release -r win-x64 --self-contained true -p:SdkDirectory=PATH_TO_SDK -o assets/animation
```

`CUE4Parse-Natives.dll` is built from the upstream
[CUE4Parse native sources](https://github.com/FabianFG/CUE4Parse/tree/master/CUE4Parse-Natives)
with the ACL submodule checked out recursively. Build the native CMake project
for x64 Release and copy that DLL, plus the CUE4Parse, ACL and RTM license texts,
to `assets/animation`. The runtime is self-contained; users do not need to
install .NET. The PyInstaller spec includes that entire directory as data.

Run `python tools/verify_inspection_features.py` to check real game deformation,
unchanged bind geometry, GPU vertex updates, precise native FluentPy inputs,
multiple tactical devices, OBJ and textured GLB persistence. The full
`VertexViewer.exe --verify-release OUTPUT` check runs these inside the packaged app.
