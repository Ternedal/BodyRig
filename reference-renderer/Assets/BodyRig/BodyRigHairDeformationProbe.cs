using System;
using System.IO;
using System.Security.Cryptography;
using System.Text;
using System.Threading.Tasks;
using UnityEngine;

namespace BodyRig.ReferenceRenderer
{
    /// <summary>
    /// Comparison-only machine evidence that the exact source-hair review mesh is
    /// genuinely skinned into the loaded Humanoid. The probe turns the real Head
    /// bone, bakes the SkinnedMeshRenderer before/after, requires measurable vertex
    /// motion, restores neutral, and binds the report to the exact runtime bytes.
    /// It never grades hairstyle quality and never grants component/production authority.
    /// </summary>
    public sealed class BodyRigHairDeformationProbe : MonoBehaviour
    {
        private const string HairNodeName = "BodyRigSourceHairReview";
        private const string HairMeshName = "BodyRigSourceHairReviewMesh";
        private const string SequenceRevision = "source-hair-head-turn-v1";
        private const float HeadTurnDegrees = 28.0f;
        private const float MinimumMotionRmsMeters = 0.00025f;
        private const float MinimumMotionMaxMeters = 0.001f;
        private const float MaximumRestorationRmsMeters = 0.00025f;
        private const float MaximumRestorationMaxMeters = 0.001f;

        [Serializable]
        private sealed class HairDeformationReport
        {
            public string format = "bodyrig-hair-deformation-probe";
            public int version = 1;
            public string observed_at;
            public string bodyrig_revision;
            public string platform;
            public string unity_platform;
            public string unity_version;
            public string build_guid;
            public string device_model;
            public string body_id;
            public string package_sha256;
            public string runtime_manifest_sha256;
            public string avatar_sha256;
            public string bodyprint_sha256;
            public string sequence_revision = SequenceRevision;
            public string hair_node = HairNodeName;
            public string hair_mesh = HairMeshName;
            public int hair_bone_count;
            public int vertex_count;
            public bool skinned_mesh_renderer_found;
            public bool head_bone_resolved;
            public bool head_bone_bound;
            public float requested_head_turn_degrees = HeadTurnDegrees;
            public float observed_head_turn_degrees;
            public float vertex_motion_rms_m;
            public float vertex_motion_max_m;
            public float restoration_rms_m;
            public float restoration_max_m;
            public bool vertex_motion_observed;
            public bool restored_neutral;
            public bool complete;
            public bool human_review_required = true;
            public bool comparison_only = true;
            public bool hair_component_authority = false;
            public bool production_activation = false;
        }

        private BodyRigAvatarLoader _loader;

        public string LastReportPath { get; private set; }

        public void Configure(BodyRigAvatarLoader configuredLoader)
        {
            _loader = configuredLoader != null ? configuredLoader : throw new ArgumentNullException(nameof(configuredLoader));
        }

        public async Task<string> RunProbeAsync(string reportPath, Action<string> status = null)
        {
            if (_loader == null) throw new InvalidOperationException("BodyRig hair deformation probe requires a BodyRigAvatarLoader");
            if (_loader.Active == null) throw new InvalidDataException("BodyRig hair deformation probe requires a loaded avatar");
            if (string.IsNullOrWhiteSpace(reportPath)) throw new ArgumentException("Hair deformation output path is required", nameof(reportPath));

            var fullOutputPath = Path.GetFullPath(reportPath);
            if (File.Exists(fullOutputPath)) throw new IOException($"Hair deformation evidence already exists: {fullOutputPath}");
            var outputDirectory = Path.GetDirectoryName(fullOutputPath);
            if (string.IsNullOrEmpty(outputDirectory)) throw new InvalidDataException("Hair deformation output has no parent directory");
            Directory.CreateDirectory(outputDirectory);

            var animator = _loader.Animator;
            if (animator == null || animator.avatar == null || !animator.avatar.isValid || !animator.avatar.isHuman)
                throw new InvalidDataException("Hair deformation probe requires the loaded valid Unity Humanoid avatar");
            var head = animator.GetBoneTransform(HumanBodyBones.Head);
            if (head == null) throw new InvalidDataException("Hair deformation probe could not resolve the Humanoid Head bone");

            var hair = FindHairRenderer();
            if (hair.sharedMesh == null || hair.sharedMesh.vertexCount < 3)
                throw new InvalidDataException("Source hair review renderer has no usable mesh");
            var bones = hair.bones;
            if (bones == null || bones.Length < 1)
                throw new InvalidDataException("Source hair review renderer has no skin bones");
            var headBound = false;
            foreach (var bone in bones)
            {
                if (bone == head)
                {
                    headBound = true;
                    break;
                }
            }
            if (!headBound)
                throw new InvalidDataException("Source hair review renderer is not bound to the Humanoid Head bone");

            var baselineRotation = head.localRotation;
            var baselineWorldRotation = head.rotation;
            Vector3[] neutral = null;
            Vector3[] turned = null;
            Vector3[] restored = null;
            float observedHeadTurn = 0f;
            try
            {
                status?.Invoke("Hair deformation: sampling neutral source hair...");
                await WaitFramesAsync(2);
                neutral = BakeVertices(hair);

                status?.Invoke("Hair deformation: applying deterministic Head turn...");
                head.localRotation = baselineRotation * Quaternion.Euler(0f, HeadTurnDegrees, 0f);
                await WaitFramesAsync(3);
                observedHeadTurn = Quaternion.Angle(baselineWorldRotation, head.rotation);
                if (observedHeadTurn < HeadTurnDegrees * 0.65f)
                    throw new InvalidDataException($"Humanoid Head turn was not applied strongly enough ({observedHeadTurn:F4} degrees)");
                turned = BakeVertices(hair);
            }
            finally
            {
                head.localRotation = baselineRotation;
                await WaitFramesAsync(3);
                restored = BakeVertices(hair);
            }

            if (neutral == null || turned == null || restored == null)
                throw new InvalidDataException("Hair deformation probe did not capture all required samples");
            if (neutral.Length != turned.Length || neutral.Length != restored.Length || neutral.Length < 3)
                throw new InvalidDataException("Hair deformation samples changed vertex topology");

            ComputeDelta(neutral, turned, out var motionRms, out var motionMax);
            ComputeDelta(neutral, restored, out var restorationRms, out var restorationMax);
            var motionObserved = motionRms >= MinimumMotionRmsMeters && motionMax >= MinimumMotionMaxMeters;
            var restoredNeutral = restorationRms <= MaximumRestorationRmsMeters && restorationMax <= MaximumRestorationMaxMeters;
            if (!motionObserved)
                throw new InvalidDataException($"Source hair did not deform with Head turn (rms={motionRms:F7}m max={motionMax:F7}m)");
            if (!restoredNeutral)
                throw new InvalidDataException($"Source hair did not restore after Head turn (rms={restorationRms:F7}m max={restorationMax:F7}m)");

            var runtimeManifestPath = Path.GetFullPath(_loader.ActiveRuntimeManifestPath);
            var runtimeDirectory = Path.GetDirectoryName(runtimeManifestPath);
            if (string.IsNullOrEmpty(runtimeDirectory)) throw new InvalidDataException("Active runtime manifest has no parent directory");
            var avatarPath = Path.Combine(runtimeDirectory, "avatar.vrm");
            var bodyprintPath = Path.Combine(runtimeDirectory, "bodyprint.json");
            var buildGuid = Application.buildGUID;
            if (string.IsNullOrWhiteSpace(buildGuid)) throw new InvalidDataException("Hair deformation probe requires a non-empty Unity build GUID");
            var deviceModel = string.IsNullOrWhiteSpace(SystemInfo.deviceModel) ? "unknown" : SystemInfo.deviceModel.Trim();

            var report = new HairDeformationReport
            {
                observed_at = DateTime.UtcNow.ToString("o"),
                bodyrig_revision = BodyRigBuildProvenance.RequireRevision(),
                platform = ResolvePhysicalPlatform(deviceModel),
                unity_platform = Application.platform.ToString(),
                unity_version = Application.unityVersion,
                build_guid = buildGuid,
                device_model = deviceModel,
                body_id = _loader.ActiveBodyId,
                package_sha256 = _loader.ActivePackageSha256,
                runtime_manifest_sha256 = Sha256File(runtimeManifestPath),
                avatar_sha256 = Sha256File(avatarPath),
                bodyprint_sha256 = Sha256File(bodyprintPath),
                hair_bone_count = bones.Length,
                vertex_count = neutral.Length,
                skinned_mesh_renderer_found = true,
                head_bone_resolved = true,
                head_bone_bound = true,
                observed_head_turn_degrees = observedHeadTurn,
                vertex_motion_rms_m = motionRms,
                vertex_motion_max_m = motionMax,
                restoration_rms_m = restorationRms,
                restoration_max_m = restorationMax,
                vertex_motion_observed = true,
                restored_neutral = true,
                complete = true,
            };

            var temporary = fullOutputPath + "." + Guid.NewGuid().ToString("N") + ".tmp";
            try
            {
                File.WriteAllText(temporary, JsonUtility.ToJson(report, true) + "\n", new UTF8Encoding(false));
                File.Move(temporary, fullOutputPath);
            }
            finally
            {
                if (File.Exists(temporary)) File.Delete(temporary);
            }

            LastReportPath = fullOutputPath;
            status?.Invoke($"Hair deformation machine evidence: PASS | rms={motionRms:F5}m max={motionMax:F5}m");
            Debug.Log($"BodyRig hair deformation probe: PASS | {report.platform} | {fullOutputPath}", this);
            return fullOutputPath;
        }

        private SkinnedMeshRenderer FindHairRenderer()
        {
            SkinnedMeshRenderer match = null;
            foreach (var renderer in _loader.Active.GetComponentsInChildren<SkinnedMeshRenderer>(true))
            {
                var nodeMatch = string.Equals(renderer.gameObject.name, HairNodeName, StringComparison.Ordinal);
                var meshMatch = renderer.sharedMesh != null && string.Equals(renderer.sharedMesh.name, HairMeshName, StringComparison.Ordinal);
                if (!nodeMatch && !meshMatch) continue;
                if (match != null) throw new InvalidDataException("Loaded avatar contains multiple source hair review renderers");
                match = renderer;
            }
            if (match == null) throw new InvalidDataException("Loaded avatar does not contain the exact source hair review renderer");
            return match;
        }

        private static Vector3[] BakeVertices(SkinnedMeshRenderer renderer)
        {
            var mesh = new Mesh { name = "BodyRigHairDeformationSample" };
            try
            {
                renderer.BakeMesh(mesh);
                var vertices = mesh.vertices;
                if (vertices == null || vertices.Length < 3)
                    throw new InvalidDataException("Baked source hair mesh has no vertices");
                return vertices;
            }
            finally
            {
                Destroy(mesh);
            }
        }

        private static void ComputeDelta(Vector3[] baseline, Vector3[] observed, out float rms, out float maximum)
        {
            double squared = 0.0;
            var max = 0.0f;
            for (var index = 0; index < baseline.Length; index++)
            {
                var distance = Vector3.Distance(baseline[index], observed[index]);
                squared += (double)distance * distance;
                if (distance > max) max = distance;
            }
            rms = (float)Math.Sqrt(squared / baseline.Length);
            maximum = max;
            if (float.IsNaN(rms) || float.IsInfinity(rms) || float.IsNaN(maximum) || float.IsInfinity(maximum))
                throw new InvalidDataException("Hair deformation metrics are non-finite");
        }

        private static async Task WaitFramesAsync(int count)
        {
            for (var index = 0; index < count; index++) await Task.Yield();
        }

        private static string ResolvePhysicalPlatform(string deviceModel)
        {
            switch (Application.platform)
            {
                case RuntimePlatform.WindowsPlayer:
                    return "windows-unity-univrm";
                case RuntimePlatform.WindowsEditor:
                    throw new PlatformNotSupportedException("Hair deformation evidence requires a built WindowsPlayer, not Unity Editor");
                case RuntimePlatform.Android:
                    if (string.IsNullOrWhiteSpace(deviceModel) ||
                        (deviceModel.IndexOf("Quest", StringComparison.OrdinalIgnoreCase) < 0 &&
                         deviceModel.IndexOf("Oculus", StringComparison.OrdinalIgnoreCase) < 0))
                        throw new PlatformNotSupportedException($"Hair deformation evidence requires a Quest/Oculus device model, got '{deviceModel}'");
                    return "android-quest-class";
                default:
                    throw new PlatformNotSupportedException($"Hair deformation evidence does not support Unity platform {Application.platform}");
            }
        }

        private static string Sha256File(string path)
        {
            if (!File.Exists(path)) throw new FileNotFoundException("Hair deformation probe input file is missing", path);
            using (var stream = File.OpenRead(path))
            using (var sha = SHA256.Create())
            {
                var digest = sha.ComputeHash(stream);
                var builder = new StringBuilder(digest.Length * 2);
                foreach (var value in digest) builder.Append(value.ToString("x2"));
                return builder.ToString();
            }
        }
    }
}
