using System;
using System.Collections.Generic;
using System.IO;
using System.Text;
using System.Threading.Tasks;
using UnityEngine;

namespace BodyRig.ReferenceRenderer
{
    /// <summary>
    /// Automatic, deterministic deformation quality grader.
    /// It waits for the canonical deformation probe, replays the same fixed Humanoid
    /// stress poses, bakes every SkinnedMeshRenderer and writes a create-only machine
    /// quality receipt. No human attestation is involved.
    /// </summary>
    [DefaultExecutionOrder(2000)]
    public sealed class BodyRigAutomaticDeformationQuality : MonoBehaviour
    {
        private const string SequenceRevision = "humanoid-muscle-sweep-v1";
        private const string MetricRevision = "skinned-mesh-geometry-v1";
        private const string AutoExitEnvironment = "BODYRIG_AUTO_EXIT_AFTER_QUALITY";
        private const float MinChangedVertexFraction = 0.005f;
        private const float MinPoseMaxDisplacementRatio = 0.005f;
        private const float MaxPoseDisplacementRatio = 1.25f;
        private const float MaxPoseRmsRatio = 0.50f;
        private const float NeutralMaxChangedVertexFraction = 0.01f;
        private const float NeutralMaxRmsRatio = 0.001f;
        private const float NeutralMaxDisplacementRatio = 0.005f;
        private const float RestoreMaxRmsRatio = 0.001f;
        private const float RestoreMaxDisplacementRatio = 0.005f;
        private const float MinReferenceHeightM = 0.50f;
        private const float MaxReferenceHeightM = 2.60f;
        private const int MinVertexCount = 1000;
        private const float ChangeEpsilonHeightRatio = 0.0001f;

        [Serializable]
        private sealed class PoseMetric
        {
            public string id;
            public int vertex_count;
            public int nonfinite_vertex_count;
            public float changed_vertex_fraction;
            public float rms_displacement_ratio;
            public float max_displacement_ratio;
            public bool machine_pass;
        }

        [Serializable]
        private sealed class Thresholds
        {
            public float min_changed_vertex_fraction = MinChangedVertexFraction;
            public float min_pose_max_displacement_ratio = MinPoseMaxDisplacementRatio;
            public float max_pose_displacement_ratio = MaxPoseDisplacementRatio;
            public float max_pose_rms_ratio = MaxPoseRmsRatio;
            public float neutral_max_changed_vertex_fraction = NeutralMaxChangedVertexFraction;
            public float neutral_max_rms_ratio = NeutralMaxRmsRatio;
            public float neutral_max_displacement_ratio = NeutralMaxDisplacementRatio;
            public float restore_max_rms_ratio = RestoreMaxRmsRatio;
            public float restore_max_displacement_ratio = RestoreMaxDisplacementRatio;
            public float min_reference_height_m = MinReferenceHeightM;
            public float max_reference_height_m = MaxReferenceHeightM;
            public int min_vertex_count = MinVertexCount;
            public float change_epsilon_height_ratio = ChangeEpsilonHeightRatio;
        }

        [Serializable]
        private sealed class QualityReport
        {
            public string format = "bodyrig-deformation-quality";
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
            public string metric_revision = MetricRevision;
            public int renderer_count;
            public int vertex_count;
            public float reference_height_m;
            public PoseMetric[] poses;
            public float restored_neutral_rms_ratio;
            public float restored_neutral_max_displacement_ratio;
            public Thresholds thresholds = new Thresholds();
            public bool machine_quality_pass;
            public bool production_activation = false;
        }

        private sealed class PoseDefinition
        {
            public readonly string Id;
            public readonly KeyValuePair<string, float>[] Muscles;
            public PoseDefinition(string id, params KeyValuePair<string, float>[] muscles)
            {
                Id = id;
                Muscles = muscles;
            }
        }

        private sealed class MeshSnapshot
        {
            public readonly Vector3[][] Vertices;
            public readonly int VertexCount;
            public MeshSnapshot(Vector3[][] vertices, int vertexCount)
            {
                Vertices = vertices;
                VertexCount = vertexCount;
            }
        }

        private static KeyValuePair<string, float> Muscle(string name, float value) =>
            new KeyValuePair<string, float>(name, value);

        private static readonly PoseDefinition[] Sequence =
        {
            new PoseDefinition("neutral"),
            new PoseDefinition("arms_abduction",
                Muscle("Left Arm Down-Up", -0.90f), Muscle("Right Arm Down-Up", -0.90f),
                Muscle("Left Shoulder Down-Up", -0.35f), Muscle("Right Shoulder Down-Up", -0.35f)),
            new PoseDefinition("elbows_flexed",
                Muscle("Left Arm Down-Up", -0.60f), Muscle("Right Arm Down-Up", -0.60f),
                Muscle("Left Forearm Stretch", -0.90f), Muscle("Right Forearm Stretch", -0.90f)),
            new PoseDefinition("arms_forward",
                Muscle("Left Arm Front-Back", -0.85f), Muscle("Right Arm Front-Back", -0.85f),
                Muscle("Left Forearm Stretch", -0.45f), Muscle("Right Forearm Stretch", -0.45f)),
            new PoseDefinition("left_leg_lift",
                Muscle("Left Upper Leg Front-Back", -0.80f), Muscle("Left Lower Leg Stretch", -0.65f)),
            new PoseDefinition("knee_flexion",
                Muscle("Left Upper Leg Front-Back", -0.45f), Muscle("Right Upper Leg Front-Back", -0.45f),
                Muscle("Left Lower Leg Stretch", -0.90f), Muscle("Right Lower Leg Stretch", -0.90f)),
        };

        [RuntimeInitializeOnLoadMethod(RuntimeInitializeLoadType.AfterSceneLoad)]
        private static void Install()
        {
            if (FindObjectOfType<BodyRigAutomaticDeformationQuality>() != null) return;
            var host = new GameObject("BodyRig Automatic Deformation Quality");
            DontDestroyOnLoad(host);
            host.AddComponent<BodyRigAutomaticDeformationQuality>();
        }

        private async void Start()
        {
            try
            {
                await RunAsync();
            }
            catch (Exception exception)
            {
                Debug.LogException(exception, this);
                if (ShouldAutoExit()) Application.Quit(3);
            }
        }

        private async Task RunAsync()
        {
            var deformationPath = GetArgument("--bodyrig-deformation-output") ??
                                  Path.Combine(Application.persistentDataPath, "BodyRig", "bodyrig-deformation-probe.json");
            deformationPath = Path.GetFullPath(deformationPath);
            var qualityPath = DeriveQualityPath(deformationPath);

            var deadline = Time.realtimeSinceStartup + 240f;
            BodyRigAvatarLoader loader = null;
            BodyRigDeformationSweep sweep = null;
            while (Time.realtimeSinceStartup < deadline)
            {
                loader = FindObjectOfType<BodyRigAvatarLoader>();
                sweep = FindObjectOfType<BodyRigDeformationSweep>();
                if (loader != null && loader.Active != null && loader.Animator != null && sweep != null && File.Exists(deformationPath)) break;
                await Task.Yield();
            }
            if (loader == null || loader.Active == null || loader.Animator == null || sweep == null || !File.Exists(deformationPath))
                throw new TimeoutException("Automatic deformation quality timed out waiting for canonical renderer/deformation evidence.");
            if (File.Exists(qualityPath)) throw new IOException("Automatic deformation quality receipt already exists: " + qualityPath);

            sweep.StopReviewLoop();
            var animator = loader.Animator;
            if (animator.avatar == null || !animator.avatar.isHuman || !animator.avatar.isValid)
                throw new InvalidDataException("Automatic deformation quality requires a valid Unity Humanoid avatar.");

            using (var poseHandler = new HumanPoseHandler(animator.avatar, animator.transform))
            {
                var baselinePose = new HumanPose();
                poseHandler.GetHumanPose(ref baselinePose);
                if (baselinePose.muscles == null || baselinePose.muscles.Length != HumanTrait.MuscleCount)
                    throw new InvalidDataException("Automatic deformation quality received an invalid Humanoid muscle array.");
                baselinePose.muscles = (float[])baselinePose.muscles.Clone();

                var muscleIndices = ResolveMuscles();
                var renderers = loader.Active.GetComponentsInChildren<SkinnedMeshRenderer>(true);
                var usable = new List<SkinnedMeshRenderer>();
                foreach (var renderer in renderers)
                    if (renderer != null && renderer.sharedMesh != null && renderer.sharedMesh.vertexCount > 0) usable.Add(renderer);
                if (usable.Count == 0) throw new InvalidDataException("Automatic deformation quality found no skinned mesh renderers.");

                RestorePose(poseHandler, baselinePose);
                await SettleAsync();
                var baselineMesh = Capture(usable);
                var referenceHeight = ReferenceHeight(baselineMesh);
                if (baselineMesh.VertexCount < MinVertexCount)
                    throw new InvalidDataException($"Automatic deformation quality requires at least {MinVertexCount} skinned vertices, got {baselineMesh.VertexCount}.");
                if (!IsFinite(referenceHeight) || referenceHeight < MinReferenceHeightM || referenceHeight > MaxReferenceHeightM)
                    throw new InvalidDataException($"Automatic deformation quality reference height is outside the production envelope: {referenceHeight:F4} m.");

                var poseMetrics = new List<PoseMetric>(Sequence.Length);
                foreach (var definition in Sequence)
                {
                    ApplyPose(poseHandler, baselinePose, muscleIndices, definition);
                    await SettleAsync();
                    var current = Capture(usable);
                    var metric = Measure(definition.Id, baselineMesh, current, referenceHeight);
                    metric.machine_pass = GradePose(metric, definition.Id == "neutral");
                    poseMetrics.Add(metric);
                }

                RestorePose(poseHandler, baselinePose);
                await SettleAsync();
                var restored = Capture(usable);
                var restoredMetric = Measure("restored-neutral", baselineMesh, restored, referenceHeight);
                var restoredPass = restoredMetric.nonfinite_vertex_count == 0 &&
                                   restoredMetric.rms_displacement_ratio <= RestoreMaxRmsRatio &&
                                   restoredMetric.max_displacement_ratio <= RestoreMaxDisplacementRatio;

                var runtimeManifestPath = Path.GetFullPath(loader.ActiveRuntimeManifestPath);
                var buildGuid = Application.buildGUID;
                if (string.IsNullOrWhiteSpace(buildGuid)) throw new InvalidDataException("Automatic deformation quality requires a non-empty Unity build GUID.");
                var deviceModel = string.IsNullOrWhiteSpace(SystemInfo.deviceModel) ? "unknown" : SystemInfo.deviceModel.Trim();
                var report = new QualityReport
                {
                    observed_at = DateTime.UtcNow.ToString("o"),
                    bodyrig_revision = BodyRigBuildProvenance.RequireRevision(),
                    platform = ResolvePhysicalPlatform(deviceModel),
                    unity_platform = Application.platform.ToString(),
                    unity_version = Application.unityVersion,
                    build_guid = buildGuid,
                    device_model = deviceModel,
                    body_id = loader.ActiveBodyId,
                    package_sha256 = loader.ActivePackageSha256,
                    runtime_manifest_sha256 = Sha256File(runtimeManifestPath),
                    avatar_sha256 = loader.ActiveAvatarSha256,
                    bodyprint_sha256 = loader.ActiveBodyprintSha256,
                    renderer_count = usable.Count,
                    vertex_count = baselineMesh.VertexCount,
                    reference_height_m = referenceHeight,
                    poses = poseMetrics.ToArray(),
                    restored_neutral_rms_ratio = restoredMetric.rms_displacement_ratio,
                    restored_neutral_max_displacement_ratio = restoredMetric.max_displacement_ratio,
                    machine_quality_pass = restoredPass && poseMetrics.TrueForAll(item => item.machine_pass),
                };
                if (!report.machine_quality_pass)
                    throw new InvalidDataException("Automatic deformation quality metrics did not satisfy the production thresholds.");

                WriteCreateOnly(qualityPath, report);
                Debug.Log($"BodyRig automatic deformation quality: PASS | {report.platform} | vertices={report.vertex_count} | {qualityPath}", this);
            }

            if (ShouldAutoExit())
            {
                Application.Quit(0);
            }
            else
            {
                sweep.BeginReviewLoop();
            }
        }

        private static Dictionary<string, int> ResolveMuscles()
        {
            var result = new Dictionary<string, int>(StringComparer.Ordinal);
            for (var index = 0; index < HumanTrait.MuscleName.Length; index++) result[HumanTrait.MuscleName[index]] = index;
            foreach (var definition in Sequence)
                foreach (var assignment in definition.Muscles)
                    if (!result.ContainsKey(assignment.Key)) throw new InvalidDataException("Missing Humanoid muscle: " + assignment.Key);
            return result;
        }

        private static void ApplyPose(HumanPoseHandler handler, HumanPose baseline, Dictionary<string, int> indices, PoseDefinition definition)
        {
            var pose = CopyPose(baseline);
            foreach (var assignment in definition.Muscles) pose.muscles[indices[assignment.Key]] = Mathf.Clamp(assignment.Value, -1f, 1f);
            handler.SetHumanPose(ref pose);
        }

        private static void RestorePose(HumanPoseHandler handler, HumanPose baseline)
        {
            var pose = CopyPose(baseline);
            handler.SetHumanPose(ref pose);
        }

        private static HumanPose CopyPose(HumanPose baseline) => new HumanPose
        {
            bodyPosition = baseline.bodyPosition,
            bodyRotation = baseline.bodyRotation,
            muscles = (float[])baseline.muscles.Clone(),
        };

        private static async Task SettleAsync()
        {
            await Task.Yield();
            await Task.Yield();
        }

        private static MeshSnapshot Capture(IReadOnlyList<SkinnedMeshRenderer> renderers)
        {
            var all = new Vector3[renderers.Count][];
            var total = 0;
            for (var index = 0; index < renderers.Count; index++)
            {
                var baked = new Mesh();
                try
                {
                    renderers[index].BakeMesh(baked);
                    var vertices = baked.vertices;
                    var world = new Vector3[vertices.Length];
                    for (var vertex = 0; vertex < vertices.Length; vertex++) world[vertex] = renderers[index].transform.TransformPoint(vertices[vertex]);
                    all[index] = world;
                    total += world.Length;
                }
                finally
                {
                    Destroy(baked);
                }
            }
            return new MeshSnapshot(all, total);
        }

        private static float ReferenceHeight(MeshSnapshot snapshot)
        {
            var minY = float.PositiveInfinity;
            var maxY = float.NegativeInfinity;
            foreach (var renderer in snapshot.Vertices)
            foreach (var vertex in renderer)
            {
                if (!IsFinite(vertex.x) || !IsFinite(vertex.y) || !IsFinite(vertex.z))
                    throw new InvalidDataException("Baseline mesh contains non-finite vertices.");
                minY = Mathf.Min(minY, vertex.y);
                maxY = Mathf.Max(maxY, vertex.y);
            }
            return maxY - minY;
        }

        private static PoseMetric Measure(string id, MeshSnapshot baseline, MeshSnapshot current, float referenceHeight)
        {
            if (baseline.Vertices.Length != current.Vertices.Length || baseline.VertexCount != current.VertexCount)
                throw new InvalidDataException("Skinned mesh topology changed during the fixed deformation sequence.");
            var changed = 0;
            var nonfinite = 0;
            var max = 0f;
            double squared = 0d;
            var epsilon = referenceHeight * ChangeEpsilonHeightRatio;
            var count = 0;
            for (var renderer = 0; renderer < baseline.Vertices.Length; renderer++)
            {
                if (baseline.Vertices[renderer].Length != current.Vertices[renderer].Length)
                    throw new InvalidDataException("Skinned mesh vertex count changed during the fixed deformation sequence.");
                for (var vertex = 0; vertex < baseline.Vertices[renderer].Length; vertex++)
                {
                    var value = current.Vertices[renderer][vertex];
                    if (!IsFinite(value.x) || !IsFinite(value.y) || !IsFinite(value.z))
                    {
                        nonfinite++;
                        count++;
                        continue;
                    }
                    var displacement = Vector3.Distance(baseline.Vertices[renderer][vertex], value);
                    if (displacement > epsilon) changed++;
                    max = Mathf.Max(max, displacement);
                    squared += displacement * displacement;
                    count++;
                }
            }
            var rms = count > 0 ? Math.Sqrt(squared / count) : double.PositiveInfinity;
            return new PoseMetric
            {
                id = id,
                vertex_count = count,
                nonfinite_vertex_count = nonfinite,
                changed_vertex_fraction = count > 0 ? (float)changed / count : 0f,
                rms_displacement_ratio = (float)(rms / referenceHeight),
                max_displacement_ratio = max / referenceHeight,
            };
        }

        private static bool GradePose(PoseMetric metric, bool neutral)
        {
            if (metric.nonfinite_vertex_count != 0 || metric.vertex_count < MinVertexCount) return false;
            if (neutral)
            {
                return metric.changed_vertex_fraction <= NeutralMaxChangedVertexFraction &&
                       metric.rms_displacement_ratio <= NeutralMaxRmsRatio &&
                       metric.max_displacement_ratio <= NeutralMaxDisplacementRatio;
            }
            return metric.changed_vertex_fraction >= MinChangedVertexFraction &&
                   metric.max_displacement_ratio >= MinPoseMaxDisplacementRatio &&
                   metric.max_displacement_ratio <= MaxPoseDisplacementRatio &&
                   metric.rms_displacement_ratio <= MaxPoseRmsRatio;
        }

        private static string DeriveQualityPath(string deformationPath)
        {
            var directory = Path.GetDirectoryName(deformationPath);
            if (string.IsNullOrEmpty(directory)) throw new InvalidDataException("Deformation output has no parent directory.");
            var name = Path.GetFileName(deformationPath);
            var qualityName = name.EndsWith("-probe.json", StringComparison.OrdinalIgnoreCase)
                ? name.Substring(0, name.Length - "-probe.json".Length) + "-quality.json"
                : Path.GetFileNameWithoutExtension(name) + "-quality.json";
            return Path.Combine(directory, qualityName);
        }

        private static void WriteCreateOnly(string path, QualityReport report)
        {
            var fullPath = Path.GetFullPath(path);
            if (File.Exists(fullPath)) throw new IOException("Automatic quality receipt already exists: " + fullPath);
            var directory = Path.GetDirectoryName(fullPath);
            if (string.IsNullOrEmpty(directory)) throw new InvalidDataException("Automatic quality receipt has no parent directory.");
            Directory.CreateDirectory(directory);
            var temporary = fullPath + "." + Guid.NewGuid().ToString("N") + ".tmp";
            try
            {
                File.WriteAllText(temporary, JsonUtility.ToJson(report, true) + "\n", new UTF8Encoding(false));
                File.Move(temporary, fullPath);
            }
            finally
            {
                if (File.Exists(temporary)) File.Delete(temporary);
            }
        }

        private static bool ShouldAutoExit() => string.Equals(Environment.GetEnvironmentVariable(AutoExitEnvironment), "1", StringComparison.Ordinal);

        private static string GetArgument(string name)
        {
            var args = Environment.GetCommandLineArgs();
            for (var index = 0; index < args.Length - 1; index++)
                if (string.Equals(args[index], name, StringComparison.OrdinalIgnoreCase)) return args[index + 1];
            return null;
        }

        private static string ResolvePhysicalPlatform(string deviceModel)
        {
            if (Application.platform == RuntimePlatform.WindowsPlayer) return "windows-unity-univrm";
            if (Application.platform == RuntimePlatform.Android &&
                !string.IsNullOrWhiteSpace(deviceModel) &&
                (deviceModel.IndexOf("Quest", StringComparison.OrdinalIgnoreCase) >= 0 || deviceModel.IndexOf("Oculus", StringComparison.OrdinalIgnoreCase) >= 0))
                return "android-quest-class";
            throw new PlatformNotSupportedException("Automatic deformation quality requires WindowsPlayer or Quest/Oculus Android hardware.");
        }

        private static string Sha256File(string path)
        {
            if (!File.Exists(path)) throw new FileNotFoundException("Automatic quality input file is missing", path);
            using (var stream = File.OpenRead(path))
            using (var sha = System.Security.Cryptography.SHA256.Create())
            {
                var digest = sha.ComputeHash(stream);
                var builder = new StringBuilder(digest.Length * 2);
                foreach (var value in digest) builder.Append(value.ToString("x2"));
                return builder.ToString();
            }
        }

        private static bool IsFinite(float value) => !float.IsNaN(value) && !float.IsInfinity(value);
    }
}
