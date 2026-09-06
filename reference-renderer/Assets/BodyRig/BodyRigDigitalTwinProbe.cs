using System;
using System.IO;
using System.Security.Cryptography;
using System.Text;
using System.Threading.Tasks;
using UnityEngine;

namespace BodyRig.ReferenceRenderer
{
    /// <summary>
    /// Physical M5 evidence generator for one exact M4 digital-twin composition.
    /// The receipt is machine evidence only and is deliberately non-activating.
    /// Existing canonical Windows/Quest human renderer attestations remain a
    /// separate prerequisite validated by the Python M5 authority layer.
    /// </summary>
    public sealed class BodyRigDigitalTwinProbe : MonoBehaviour
    {
        [Serializable]
        private sealed class PlatformInput
        {
            public string format;
            public int version;
            public string platform;
            public string bodyrig_revision;
            public string body_id;
            public string package_sha256;
            public string runtime_manifest_sha256;
            public string bodyprint_sha256;
            public string composition_authority_id;
            public string composition_authority_sha256;
            public string embodiment_probe_sha256;
            public string motor_state_sha256;
            public string utterance_id;
            public int motor_state_version;
            public string renderer_probe_sha256;
            public string deformation_probe_sha256;
            public string renderer_attestation_sha256;
            public bool source_observed_embodiment_bound;
            public bool production_activation;
        }

        [Serializable]
        private sealed class MotorIdentity
        {
            public string type;
            public int version;
            public string body_id;
            public string utterance_id;
        }

        [Serializable]
        private sealed class RealizationReport
        {
            public string format = "bodyrig-digital-twin-platform-realization";
            public int version = 1;
            public string observed_at;
            public string platform;
            public string bodyrig_revision;
            public string body_id;
            public string package_sha256;
            public string runtime_manifest_sha256;
            public string bodyprint_sha256;
            public string composition_authority_id;
            public string composition_authority_sha256;
            public string embodiment_probe_sha256;
            public string motor_state_sha256;
            public string utterance_id;
            public int motor_state_version;
            public string renderer_probe_sha256;
            public string deformation_probe_sha256;
            public string renderer_attestation_sha256;
            public bool source_observed_embodiment_bound;
            public bool production_activation;
            public string input_manifest_sha256;
            public string unity_platform;
            public string unity_version;
            public string build_guid;
            public string device_model;
            public string graphics_device;
            public string renderer_name;
            public string renderer_version;
            public int realization_frame_count;
            public bool motion_realized;
            public bool expression_realized;
            public bool gesture_realized;
            public bool gaze_realized;
            public bool posture_realized;
            public bool speech_timing_realized;
        }

        private BodyRigAvatarLoader _loader;
        private BodyRigMotorDriver _driver;
        private string _rendererName;
        private string _rendererVersion;

        public string LastReportPath { get; private set; }

        public void Configure(
            BodyRigAvatarLoader configuredLoader,
            BodyRigMotorDriver configuredDriver,
            string configuredRendererName,
            string configuredRendererVersion)
        {
            _loader = configuredLoader != null ? configuredLoader : throw new ArgumentNullException(nameof(configuredLoader));
            _driver = configuredDriver != null ? configuredDriver : throw new ArgumentNullException(nameof(configuredDriver));
            if (string.IsNullOrWhiteSpace(configuredRendererName)) throw new ArgumentException("Renderer name is required", nameof(configuredRendererName));
            if (string.IsNullOrWhiteSpace(configuredRendererVersion)) throw new ArgumentException("Renderer version is required", nameof(configuredRendererVersion));
            _rendererName = configuredRendererName.Trim();
            _rendererVersion = configuredRendererVersion.Trim();
        }

        public async Task<string> RunProbeAsync(
            string inputManifestPath,
            string compositionAuthorityPath,
            string embodimentProbePath,
            string motorStatePath,
            string outputPath)
        {
            if (_loader == null || _driver == null) throw new InvalidOperationException("Digital-twin probe is not configured");
            var inputPath = RequiredFile(inputManifestPath, "M5 platform input");
            var authorityPath = RequiredFile(compositionAuthorityPath, "M4 composition authority");
            var embodimentPath = RequiredFile(embodimentProbePath, "M4 embodiment probe");
            var motorPath = RequiredFile(motorStatePath, "M4 Motor State v2");
            if (string.IsNullOrWhiteSpace(outputPath)) throw new ArgumentException("M5 realization output path is required", nameof(outputPath));

            PlatformInput input;
            MotorIdentity motor;
            var inputJson = File.ReadAllText(inputPath, Encoding.UTF8);
            var motorJson = File.ReadAllText(motorPath, Encoding.UTF8);
            try
            {
                input = JsonUtility.FromJson<PlatformInput>(inputJson);
                motor = JsonUtility.FromJson<MotorIdentity>(motorJson);
            }
            catch (Exception exception)
            {
                throw new InvalidDataException("M5 platform input or Motor State is not valid JSON", exception);
            }
            ValidateInput(input);
            ValidateMotorIdentity(motor, input);

            var revision = BodyRigBuildProvenance.RequireRevision();
            if (!string.Equals(revision, input.bodyrig_revision, StringComparison.Ordinal))
                throw new InvalidDataException("Physical player revision does not match M5 platform input");
            if (_loader.Active == null || _loader.Animator == null)
                throw new InvalidDataException("M5 digital-twin probe requires the exact active VRM runtime");
            if (!string.Equals(_loader.ActiveBodyId, input.body_id, StringComparison.Ordinal) ||
                !string.Equals(_loader.ActivePackageSha256, input.package_sha256, StringComparison.Ordinal) ||
                !string.Equals(_loader.ActiveBodyprintSha256, input.bodyprint_sha256, StringComparison.Ordinal))
                throw new InvalidDataException("Active BodyRig runtime identity does not match M5 platform input");
            if (string.IsNullOrWhiteSpace(_loader.ActiveRuntimeManifestPath) ||
                !string.Equals(Sha256File(_loader.ActiveRuntimeManifestPath), input.runtime_manifest_sha256, StringComparison.Ordinal))
                throw new InvalidDataException("Active runtime-manifest.json does not match M5 platform input");

            RequireHash(authorityPath, input.composition_authority_sha256, "M4 composition authority");
            RequireHash(embodimentPath, input.embodiment_probe_sha256, "M4 embodiment probe");
            RequireHash(motorPath, input.motor_state_sha256, "M4 Motor State v2");

            var platform = ResolvePhysicalPlatform(out var deviceModel);
            if (!string.Equals(platform, input.platform, StringComparison.Ordinal))
                throw new InvalidDataException($"M5 input targets {input.platform} but player is {platform}");

            _driver.ApplyMotorJson(motorJson);
            for (var frame = 0; frame < 120; frame++)
            {
                await Task.Yield();
                if (IsFullyRealized()) break;
            }
            if (!IsFullyRealized())
            {
                throw new InvalidDataException(
                    "M4 Motor State was accepted but the full motion/expression/gesture/gaze/posture/speech surface was not physically realized");
            }
            if (_driver.LastMotorVersion != 2 ||
                !string.Equals(_driver.LastBodyId, input.body_id, StringComparison.Ordinal) ||
                !string.Equals(_driver.LastUtteranceId, input.utterance_id, StringComparison.Ordinal))
                throw new InvalidDataException("Renderer realization identity differs from exact M4 Motor State v2");

            var buildGuid = Application.buildGUID;
            if (string.IsNullOrWhiteSpace(buildGuid)) throw new InvalidDataException("M5 realization requires a non-empty Unity build GUID");
            var report = new RealizationReport
            {
                observed_at = DateTime.UtcNow.ToString("o"),
                platform = input.platform,
                bodyrig_revision = input.bodyrig_revision,
                body_id = input.body_id,
                package_sha256 = input.package_sha256,
                runtime_manifest_sha256 = input.runtime_manifest_sha256,
                bodyprint_sha256 = input.bodyprint_sha256,
                composition_authority_id = input.composition_authority_id,
                composition_authority_sha256 = input.composition_authority_sha256,
                embodiment_probe_sha256 = input.embodiment_probe_sha256,
                motor_state_sha256 = input.motor_state_sha256,
                utterance_id = input.utterance_id,
                motor_state_version = input.motor_state_version,
                renderer_probe_sha256 = input.renderer_probe_sha256,
                deformation_probe_sha256 = input.deformation_probe_sha256,
                renderer_attestation_sha256 = input.renderer_attestation_sha256,
                source_observed_embodiment_bound = _driver.SourceObservedEmbodimentBound,
                production_activation = false,
                input_manifest_sha256 = Sha256File(inputPath),
                unity_platform = Application.platform.ToString(),
                unity_version = Application.unityVersion,
                build_guid = buildGuid,
                device_model = deviceModel,
                graphics_device = string.IsNullOrWhiteSpace(SystemInfo.graphicsDeviceName) ? "unknown" : SystemInfo.graphicsDeviceName.Trim(),
                renderer_name = _rendererName,
                renderer_version = _rendererVersion,
                realization_frame_count = _driver.RealizationFrameCount,
                motion_realized = _driver.MotionRealized,
                expression_realized = _driver.ExpressionRealized,
                gesture_realized = _driver.GestureRealized,
                gaze_realized = _driver.GazeRealized,
                posture_realized = _driver.PostureRealized,
                speech_timing_realized = _driver.SpeechTimingRealized,
            };

            var fullOutputPath = Path.GetFullPath(outputPath);
            if (File.Exists(fullOutputPath)) throw new IOException($"M5 realization evidence already exists: {fullOutputPath}");
            var parent = Path.GetDirectoryName(fullOutputPath);
            if (string.IsNullOrEmpty(parent)) throw new InvalidDataException("M5 realization output has no parent directory");
            Directory.CreateDirectory(parent);
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
            Debug.Log($"BodyRig digital-twin M5 realization: PASS | {platform} | {_driver.LastUtteranceId} | {fullOutputPath}", this);
            return fullOutputPath;
        }

        private bool IsFullyRealized()
        {
            return _driver.RealizationFrameCount >= 2 &&
                   _driver.MotionRealized &&
                   _driver.ExpressionRealized &&
                   _driver.GestureRealized &&
                   _driver.GazeRealized &&
                   _driver.PostureRealized &&
                   _driver.SpeechTimingRealized &&
                   _driver.SourceObservedEmbodimentBound;
        }

        private static void ValidateInput(PlatformInput input)
        {
            if (input == null || input.format != "bodyrig-digital-twin-platform-input" || input.version != 1)
                throw new InvalidDataException("Unsupported M5 platform-input format/version");
            if (input.platform != "windows-unity-univrm" && input.platform != "android-quest-class")
                throw new InvalidDataException("Unsupported M5 physical platform");
            if (input.motor_state_version != 2 || input.source_observed_embodiment_bound != true || input.production_activation != false)
                throw new InvalidDataException("M5 platform input is not canonical non-activating Motor State v2 evidence");
            if (string.IsNullOrWhiteSpace(input.body_id) || string.IsNullOrWhiteSpace(input.composition_authority_id) || string.IsNullOrWhiteSpace(input.utterance_id))
                throw new InvalidDataException("M5 platform input is missing exact identity");
            RequireSha40(input.bodyrig_revision, "input.bodyrig_revision");
            foreach (var pair in new[]
            {
                (input.package_sha256, "input.package_sha256"),
                (input.runtime_manifest_sha256, "input.runtime_manifest_sha256"),
                (input.bodyprint_sha256, "input.bodyprint_sha256"),
                (input.composition_authority_sha256, "input.composition_authority_sha256"),
                (input.embodiment_probe_sha256, "input.embodiment_probe_sha256"),
                (input.motor_state_sha256, "input.motor_state_sha256"),
                (input.renderer_probe_sha256, "input.renderer_probe_sha256"),
                (input.deformation_probe_sha256, "input.deformation_probe_sha256"),
                (input.renderer_attestation_sha256, "input.renderer_attestation_sha256"),
            }) RequireSha256(pair.Item1, pair.Item2);
        }

        private static void ValidateMotorIdentity(MotorIdentity motor, PlatformInput input)
        {
            if (motor == null || motor.type != "bodyrig-motor-state" || motor.version != 2)
                throw new InvalidDataException("M5 motor-state.json is not BodyRig Motor State v2");
            if (!string.Equals(motor.body_id, input.body_id, StringComparison.Ordinal) ||
                !string.Equals(motor.utterance_id, input.utterance_id, StringComparison.Ordinal))
                throw new InvalidDataException("M5 motor-state.json identity differs from platform input");
        }

        private static string RequiredFile(string path, string label)
        {
            if (string.IsNullOrWhiteSpace(path)) throw new ArgumentException(label + " path is required");
            var full = Path.GetFullPath(path);
            if (!File.Exists(full)) throw new FileNotFoundException(label + " not found", full);
            return full;
        }

        private static void RequireHash(string path, string expected, string label)
        {
            if (!string.Equals(Sha256File(path), expected, StringComparison.Ordinal))
                throw new InvalidDataException(label + " bytes no longer match M5 platform input");
        }

        private static string ResolvePhysicalPlatform(out string deviceModel)
        {
            deviceModel = string.IsNullOrWhiteSpace(SystemInfo.deviceModel) ? "unknown" : SystemInfo.deviceModel.Trim();
            switch (Application.platform)
            {
                case RuntimePlatform.WindowsPlayer:
                    return "windows-unity-univrm";
                case RuntimePlatform.WindowsEditor:
                    throw new PlatformNotSupportedException("M5 Windows evidence requires a built WindowsPlayer, not Unity Editor");
                case RuntimePlatform.Android:
                    if (deviceModel.IndexOf("Quest", StringComparison.OrdinalIgnoreCase) < 0 &&
                        deviceModel.IndexOf("Oculus", StringComparison.OrdinalIgnoreCase) < 0)
                        throw new PlatformNotSupportedException($"M5 Quest evidence requires Quest/Oculus hardware, got '{deviceModel}'");
                    return "android-quest-class";
                default:
                    throw new PlatformNotSupportedException($"M5 digital-twin acceptance does not support {Application.platform}");
            }
        }

        private static void RequireSha40(string value, string label)
        {
            if (!IsLowerHex(value, 40)) throw new InvalidDataException(label + " is not a canonical Git SHA");
        }

        private static void RequireSha256(string value, string label)
        {
            if (!IsLowerHex(value, 64)) throw new InvalidDataException(label + " is not a canonical SHA-256");
        }

        private static bool IsLowerHex(string value, int length)
        {
            if (string.IsNullOrEmpty(value) || value.Length != length) return false;
            foreach (var character in value)
                if (!((character >= '0' && character <= '9') || (character >= 'a' && character <= 'f'))) return false;
            return true;
        }

        private static string Sha256File(string path)
        {
            if (!File.Exists(path)) throw new FileNotFoundException("M5 evidence file is missing", path);
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
