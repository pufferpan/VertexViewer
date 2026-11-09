using System.Reflection;
using System.Text.Json;
using CUE4Parse.UE4.Assets.Exports.Animation;
using CUE4Parse.UE4.Objects.Core.Math;
using CUE4Parse_Conversion.Animations;

// Read-only isolated process: a failed game codec must never crash the Qt window.
try
{
    if (args[0] == "reflect")
    {
        foreach (var assemblyName in new[] { "CUE4Parse", "CUE4Parse-Conversion" })
        foreach (var type in Assembly.Load(assemblyName).GetTypes().Where(t =>
                     args.Skip(1).Any(q => t.Name.Contains(q, StringComparison.OrdinalIgnoreCase))))
        {
            Console.WriteLine(type.FullName);
            foreach (var member in type.GetMembers(BindingFlags.Instance | BindingFlags.Public | BindingFlags.DeclaredOnly))
                Console.WriteLine("  " + member);
        }
        return;
    }
    Dfmap.Program.UseConfigFile(args[0], false);
    var provider = Dfmap.Program.SharedProvider();
    var path = args[1].TrimStart('.', '/').Replace(".uasset", "");
    var asset = provider.LoadPackageObject<UAnimationAsset>(path);
    // ConvertAdditive resolves the authored base pose and may replace
    // CAnimSequence.OriginalSequence with that short base-pose asset.
    // Capture timing before conversion, otherwise an inspect becomes 2400 FPS.
    var sourceDuration = asset is UAnimSequence source ? source.SequenceLength : 0f;
    var sourceRate = asset is UAnimSequence source2 ? source2.RateScale : 1f;
    var set = asset.ConvertAnims();
    var skeletonAsset = asset.Skeleton?.Load<USkeleton>() ?? throw new InvalidDataException("动画骨架缺失");
    Directory.CreateDirectory(args[2]);
    var clips = new List<object>();
    var id = 0;
    foreach (var sequence in set.Sequences)
    {
        var skeleton = skeletonAsset.ReferenceSkeleton;
        var count = skeleton.FinalRefBoneInfo.Length;
        var frames = sequence.NumFrames;
        if (frames < 1 || frames > 30000) throw new InvalidDataException("动画帧数超过可播放范围");
        var rate = MathF.Max(MathF.Abs(sourceDuration > 0 ? sourceRate : sequence.OriginalSequence.RateScale), 0.001f);
        var duration = (sourceDuration > 0 ? sourceDuration : sequence.AnimEndTime) / rate;
        var fps = frames > 1 && duration > 0 ? (frames - 1) / duration : 30f;
        var remainingAdditive = sequence.GetType().GetField("_hasAdditiveTracks",
            BindingFlags.Instance | BindingFlags.NonPublic)?.GetValue(sequence) as bool?;
        // The pinned SDK predates the explicit flag. Its converter swaps the
        // original sequence for RefPoseSeq only after accumulating the complete
        // authored base pose. Treat that completed conversion as absolute too.
        var resolvedAdditive = sequence.IsAdditive && (remainingAdditive == false ||
            (asset is UAnimSequence original && original.IsValidAdditive() &&
             !ReferenceEquals(sequence.OriginalSequence, original)));
        var file = $"clip-{id++}.bin";
        using (var writer = new BinaryWriter(File.Create(Path.Combine(args[2], file))))
        for (var frame = 0; frame < frames; frame++)
        for (var bone = 0; bone < count; bone++)
        {
            var pose = skeleton.FinalRefBonePose[bone];
            var q = pose.Rotation; var p = pose.Translation; var s = pose.Scale3D;
            if (bone < sequence.Tracks.Count)
                sequence.Tracks[bone].GetBoneTransform(frame, frames, ref q, ref p, ref s);
            foreach (var v in new[] { q.X, q.Y, q.Z, q.W, p.X, p.Y, p.Z, s.X, s.Y, s.Z }) writer.Write(v);
        }
        clips.Add(new { name = sequence.Name, frames, fps,
            additive = sequence.IsAdditive && !resolvedAdditive, resolvedAdditive, file,
            bones = skeleton.FinalRefBoneInfo.Select(b => b.Name.Text).ToArray(),
            parents = skeleton.FinalRefBoneInfo.Select(b => b.ParentIndex).ToArray(),
            reference = skeleton.FinalRefBonePose.Select(p => new[] { p.Rotation.X, p.Rotation.Y,
                p.Rotation.Z, p.Rotation.W, p.Translation.X, p.Translation.Y, p.Translation.Z,
                p.Scale3D.X, p.Scale3D.Y, p.Scale3D.Z }).ToArray() });
    }
    if (clips.Count == 0) throw new InvalidDataException("动画资源没有可播放的骨骼轨道");
    File.WriteAllText(Path.Combine(args[2], "clips.json"), JsonSerializer.Serialize(new { clips }));
}
catch (Exception ex)
{
    Console.Error.WriteLine(ex.ToString());
    Environment.ExitCode = 1;
}
