using System;
using System.Collections.Generic;
using System.IO;
using System.Security.Cryptography;
using System.Text;
using System.Threading.Tasks;
using UnityEngine;

namespace BodyRig.ReferenceRenderer
{
    /// <summary>
    /// Deterministic physical deformation exercise for the exact accepted Humanoid.
    /// It proves that a fixed set of stress poses was actually applied by the built
    /// player. It does not grade visual quality; the operator still has to inspect
    /// the deformation on WindowsPlayer and Quest-class hardware.
    /// </summary>
    public sealed class BodyRigDeformationSweep : MonoBehaviour
    {
        private const string SequenceRevision = "humanoid-muscle-sweep-v1";
        private const float HoldSeconds = 1.5f;

        [Serializable]
        private sealed class PoseEvidence
        {
            public string id;
            public float hold_seconds;
            public bool applied;
        }

        [Serializable]
        private sealed class DeformationReport
        {
            public string format = "bodyrig-deformation-probe";
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
            public int pose_count;
            public PoseEvidence[] poses;
            public bool required_muscles_resolved;
            public bool restored_neutral;
            public bool complete;
            public bool manual_review_required = true;
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

        private static KeyValuePair<string, float> Muscle(string name, float value)
        {
            return new KeyValuePair<string, float>(name, value);
        }

        private static readonly PoseDefinition[] Sequence =
        {
            new PoseDefinition("neutral"),
            new PoseDefinition(
                "arms_abduction",
                Muscle("Left Arm Down-Up", -0.90f),
                Muscle("Right Arm Down-Up", -0.90f),
                Muscle("Left Shoulder Down-Up", -0.35f),
                Muscle("Right Shoulder Down-Up", -0.35f)),
            new PoseDefinition(
                "elbows_flexed",
                Muscle("Left Arm Down-Up", -0.60f),
                Muscle("Right Arm Down-Up", -0.60f),
                Muscle("Left Forearm Stretch", -0.90f),
                Muscle("Right Forearm Stretch", -0.90f)),
            new PoseDefinition(
                "arms_forward",
                Muscle("Left Arm Front-Back", -0.85f),
                Muscle("Right Arm Front-Back", -0.85f),
                Muscle("Left Forearm Stretch", -0.45f),
                Muscle("Right Forearm Stretch", -0.45f)),
            new PoseDefinition(
                "left_leg_lift",
                Muscle("Left Upper Leg Front-Back", -0.80f),
                Muscle("Left Lower Leg Stretch", -0.65f)),
            new PoseDefinition(
                "knee_flexion",
                Muscle("Left Upper Leg Front-Back", -0.45f),
                Muscle("Right Upper Leg Front-Back", -0.45f),
                Muscle("Left Lower Leg Stretch", -0.90f),
                Muscle("Right Lower Leg Stretch", -0.90f)),
        };

        private BodyRigAvatarLoader _loader;
        private Animator _animator;
        private HumanPoseHandler _poseHandler;
        private HumanPose _baseline;
        private Dictionary<string, int> _muscleIndices;
        private bool _reviewLoopActive;

        public string LastReportPath { get; private set; }
        public string CurrentPoseId { get; private set; } = "not-started";
        public string SequenceId => SequenceRevision;

        public void Configure(BodyRigAvatarLoader configuredLoader)
        {
            _loader = configuredLoader != null ? configuredLoader : throw new ArgumentNullException(nameof(configuredLoader));
        }

        public async Task<string> RunSweepAsync(string reportPath, Action<string> status = null)
        {
            if (_loader == null) throw new InvalidOperationException("BodyRig deformation sweep requires a BodyRigAvatarLoader");
            if (string.IsNullOrWhiteSpace(reportPath)) throw new ArgumentException("Deformation probe output path is required", nameof(reportPath));
            BindHumanoid();

            var fullOutputPath = Path.GetFullPath(reportPath);
            if (File.Exists(fullOutputPath)) throw new IOException($"Deformation probe evidence already exists: {fullOutputPath}");
            var outputDirectory = Path.GetDirectoryName(fullOutputPath);
            if (string.IsNullOrEmpty(outputDirectory)) throw new InvalidDataException("Deformation probe output has no parent directory");
            Directory.CreateDirectory(outputDirectory);

            var evidence = new List<PoseEvidence>(Sequence.Length);
            try
            {
                foreach (var definition in Sequence)
                {
                    ApplyPose(definition);
                    CurrentPoseId = definition.Id;
                    status?.Invoke($"Deformation sweep: {definition.Id}");
                    await HoldPoseAsync(HoldSeconds);
                    evidence.Add(new PoseEvidence { id = definition.Id, hold_seconds = HoldSeconds, applied = true });
                }
            }
            finally
            {
                RestoreBaseline();
                CurrentPoseId = "neutral-restored";
            }

            var runtimeManifestPath = Path.GetFullPath(_loader.ActiveRuntimeManifestPath);
            var runtimeDirectory = Path.GetDirectoryName(runtimeManifestPath);
            if (string.IsNullOrEmpty(runtimeDirectory)) throw new InvalidDataException("Active runtime manifest has no parent directory");
            var avatarPath = Path.Combine(runtimeDirectory, "avatar.vrm");
            var bodyprintPath = Path.Combine(runtimeDirectory, "bodyprint.json");
            var bodyRigRevision = BodyRigBuildProvenance.RequireRevision();
            var deviceModel = string.IsNullOrWhiteSpace(SystemInfo.deviceModel) ? "unknown" : SystemInfo.deviceModel.Trim();
            var buildGuid = Application.buildGUID;
            if (string.IsNullOrWhiteSpace(buildGuid)) throw new InvalidDataException("Deformation probe requires a non-empty Unity build GUID");

            var report = new DeformationReport
            {
                observed_at = DateTime.UtcNow.ToString("o"),
                bodyrig_revision = bodyRigRevision,
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
                pose_count = evidence.Count,
                poses = evidence.ToArray(),
                required_muscles_resolved = true,
                restored_neutral = true,
                complete = evidence.Count == Sequence.Length,
            };
            if (!report.complete) throw new InvalidDataException("Deformation sweep did not apply the complete fixed pose sequence");

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
            status?.Invoke("Deformation sweep evidence: PASS");
            Debug.Log($"BodyRig deformation probe: PASS | {report.platform} | revision {report.bodyrig_revision} | {fullOutputPath}", this);
            return fullOutputPath;
        }

        public void BeginReviewLoop(Action<string> status = null)
        {
            if (_poseHandler == null) BindHumanoid();
            if (_reviewLoopActive) return;
            _reviewLoopActive = true;
            ReviewLoopAsync(status);
        }

        public void StopReviewLoop()
        {
            _reviewLoopActive = false;
            if (_poseHandler != null) RestoreBaseline();
        }

        private async void ReviewLoopAsync(Action<string> status)
        {
            try
            {
                while (_reviewLoopActive && this != null && isActiveAndEnabled)
                {
                    foreach (var definition in Sequence)
                    {
                        if (!_reviewLoopActive || this == null || !isActiveAndEnabled) break;
                        ApplyPose(definition);
                        CurrentPoseId = definition.Id;
                        status?.Invoke($"Visual deformation review: {definition.Id}");
                        await HoldPoseAsync(HoldSeconds);
                    }
                }
            }
            catch (Exception exception)
            {
                _reviewLoopActive = false;
                Debug.LogException(exception, this);
                status?.Invoke("Visual deformation review loop failed: " + exception.Message);
            }
            finally
            {
                if (_poseHandler != null)
                {
                    RestoreBaseline();
                    CurrentPoseId = "neutral-restored";
                }
            }
        }

        private void BindHumanoid()
        {
            _animator = _loader.Animator;
            if (_animator == null || _animator.avatar == null || !_animator.avatar.isValid || !_animator.avatar.isHuman)
                throw new InvalidDataException("Deformation sweep requires the loaded valid Unity Humanoid avatar");

            _poseHandler?.Dispose();
            _poseHandler = new HumanPoseHandler(_animator.avatar, _animator.transform);
            _baseline = new HumanPose();
            _poseHandler.GetHumanPose(ref _baseline);
            if (_baseline.muscles == null || _baseline.muscles.Length != HumanTrait.MuscleCount)
                throw new InvalidDataException("Unity Humanoid returned an invalid muscle array");
            _baseline.muscles = (float[])_baseline.muscles.Clone();

            _muscleIndices = new Dictionary<string, int>(StringComparer.Ordinal);
            for (var index = 0; index < HumanTrait.MuscleName.Length; index++)
                _muscleIndices[HumanTrait.MuscleName[index]] = index;

            foreach (var definition in Sequence)
            {
                foreach (var assignment in definition.Muscles)
                {
                    if (!_muscleIndices.ContainsKey(assignment.Key))
                        throw new InvalidDataException($"Unity Humanoid is missing required deformation muscle '{assignment.Key}'");
                }
            }
        }

        private void ApplyPose(PoseDefinition definition)
        {
            var pose = CopyBaseline();
            foreach (var assignment in definition.Muscles)
            {
                var index = _muscleIndices[assignment.Key];
                pose.muscles[index] = Mathf.Clamp(assignment.Value, -1.0f, 1.0f);
            }
            _poseHandler.SetHumanPose(ref pose);
        }

        private HumanPose CopyBaseline()
        {
            return new HumanPose
            {
                bodyPosition = _baseline.bodyPosition,
                bodyRotation = _baseline.bodyRotation,
                muscles = (float[])_baseline.muscles.Clone(),
            };
        }

        private void RestoreBaseline()
        {
            var pose = CopyBaseline();
            _poseHandler.SetHumanPose(ref pose);
        }

        private static async Task HoldPoseAsync(float seconds)
        {
            var until = Time.realtimeSinceStartup + seconds;
            while (Time.realtimeSinceStartup < until) await Task.Yield();
        }

        private static string ResolvePhysicalPlatform(string deviceModel)
        {
            switch (Application.platform)
            {
                case RuntimePlatform.WindowsPlayer:
                    return "windows-unity-univrm";
                case RuntimePlatform.WindowsEditor:
                    throw new PlatformNotSupportedException("BodyRig deformation acceptance requires a built WindowsPlayer, not Unity Editor");
                case RuntimePlatform.Android:
                    if (string.IsNullOrWhiteSpace(deviceModel) ||
                        (deviceModel.IndexOf("Quest", StringComparison.OrdinalIgnoreCase) < 0 &&
                         deviceModel.IndexOf("Oculus", StringComparison.OrdinalIgnoreCase) < 0))
                        throw new PlatformNotSupportedException($"BodyRig deformation acceptance requires a Quest/Oculus device model, got '{deviceModel}'");
                    return "android-quest-class";
                default:
                    throw new PlatformNotSupportedException($"BodyRig deformation acceptance does not support Unity platform {Application.platform}");
            }
        }

        private static string Sha256File(string path)
        {
            if (!File.Exists(path)) throw new FileNotFoundException("Deformation probe input file is missing", path);
            using (var stream = File.OpenRead(path))
            using (var sha = SHA256.Create())
            {
                var digest = sha.ComputeHash(stream);
                var builder = new StringBuilder(digest.Length * 2);
                foreach (var value in digest) builder.Append(value.ToString("x2"));
                return builder.ToString();
            }
        }

        private void OnDisable()
        {
            _reviewLoopActive = false;
            _poseHandler?.Dispose();
            _poseHandler = null;
        }
    }
}