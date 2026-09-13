using System;
using System.IO;
using System.Security.Cryptography;
using System.Text;
using System.Threading.Tasks;
using UnityEngine;

namespace BodyRig.ReferenceRenderer
{
    public sealed class BodyRigRendererProbe : MonoBehaviour
    {
        [Serializable]
        private sealed class RendererIdentity { public string name; public string version; }

        private sealed class ExpectedRenderPayload
        {
            public readonly string Label;
            public readonly string NodeName;

            public ExpectedRenderPayload(string label, string nodeName)
            {
                Label = label;
                NodeName = nodeName;
            }
        }

        [Serializable]
        private sealed class ProbeReport
        {
            public string format = "bodyrig-renderer-probe";
            public int version = 1;
            public string observed_at;
            public string bodyrig_revision;
            public string platform;
            public string unity_platform;
            public string unity_version;
            public string build_guid;
            public string device_model;
            public string graphics_device;
            public string body_id;
            public string package_sha256;
            public string runtime_manifest_sha256;
            public string avatar_sha256;
            public string bodyprint_sha256;
            public bool vrm10_loaded;
            public bool humanoid_valid;
            public bool required_bones_valid;
            public RendererIdentity active_renderer;
        }

        private static readonly HumanBodyBones[] RequiredBones =
        {
            HumanBodyBones.Hips, HumanBodyBones.Spine, HumanBodyBones.Head,
            HumanBodyBones.LeftUpperLeg, HumanBodyBones.LeftLowerLeg, HumanBodyBones.LeftFoot,
            HumanBodyBones.RightUpperLeg, HumanBodyBones.RightLowerLeg, HumanBodyBones.RightFoot,
            HumanBodyBones.LeftUpperArm, HumanBodyBones.LeftLowerArm, HumanBodyBones.LeftHand,
            HumanBodyBones.RightUpperArm, HumanBodyBones.RightLowerArm, HumanBodyBones.RightHand,
        };

        private static readonly ExpectedRenderPayload[] ExpectedRenderPayloads =
        {
            new ExpectedRenderPayload("hair", "BodyRigSourceHairReview"),
            new ExpectedRenderPayload("eyes", "BodyRigSourceEyeReview"),
            new ExpectedRenderPayload("face-secondary", "BodyRigFaceSecondaryReview"),
            new ExpectedRenderPayload("fingernails", "BodyRigFingernailPlates"),
        };

        [SerializeField] private BodyRigAvatarLoader loader;
        [SerializeField] private string runtimeManifestPath;
        [SerializeField] private string outputPath;
        [SerializeField] private string rendererName = "BodyRig Reference Renderer";
        [SerializeField] private string rendererVersion = "reference-v1";
        [SerializeField] private bool runOnStart;

        public string LastProbePath { get; private set; }

        public void Configure(BodyRigAvatarLoader configuredLoader, string configuredRendererName, string configuredRendererVersion)
        {
            loader = configuredLoader != null ? configuredLoader : throw new ArgumentNullException(nameof(configuredLoader));
            if (string.IsNullOrWhiteSpace(configuredRendererName)) throw new ArgumentException("Renderer name is required", nameof(configuredRendererName));
            if (string.IsNullOrWhiteSpace(configuredRendererVersion)) throw new ArgumentException("Renderer version is required", nameof(configuredRendererVersion));
            rendererName = configuredRendererName.Trim();
            rendererVersion = configuredRendererVersion.Trim();
        }

        private async void Start()
        {
            if (!runOnStart) return;
            try { await RunProbeAsync(runtimeManifestPath, outputPath); }
            catch (Exception exception) { Debug.LogException(exception, this); }
        }

        public async Task<string> RunProbeAsync(string manifestPath, string reportPath)
        {
            if (loader == null) throw new InvalidOperationException("BodyRig renderer probe requires a BodyRigAvatarLoader");
            if (string.IsNullOrWhiteSpace(manifestPath)) throw new ArgumentException("Runtime manifest path is required", nameof(manifestPath));
            if (string.IsNullOrWhiteSpace(reportPath)) throw new ArgumentException("Probe output path is required", nameof(reportPath));
            if (string.IsNullOrWhiteSpace(rendererName) || string.IsNullOrWhiteSpace(rendererVersion)) throw new InvalidOperationException("Renderer name/version are required for probe evidence");

            var fullManifestPath = Path.GetFullPath(manifestPath);
            var runtimeDirectory = Path.GetDirectoryName(fullManifestPath);
            if (string.IsNullOrEmpty(runtimeDirectory)) throw new InvalidDataException("Runtime manifest has no parent directory");
            var avatarPath = Path.Combine(runtimeDirectory, "avatar.vrm");
            var bodyprintPath = Path.Combine(runtimeDirectory, "bodyprint.json");

            await loader.LoadRuntimeAsync(fullManifestPath);
            await Task.Yield();

            if (loader.Active == null) throw new InvalidDataException("Renderer probe has no active VRM 1.0 instance after load");
            var animator = loader.Animator;
            if (animator == null || animator.avatar == null || !animator.avatar.isValid || !animator.avatar.isHuman)
                throw new InvalidDataException("Renderer probe does not see a valid Unity Humanoid avatar");
            foreach (var bone in RequiredBones)
                if (animator.GetBoneTransform(bone) == null) throw new InvalidDataException($"Renderer probe is missing required humanoid bone: {bone}");

            var packageHash = loader.ActivePackageSha256;
            if (!IsLowerHexSha256(packageHash)) throw new InvalidDataException("Active BodyRig package SHA-256 is invalid");
            if (string.IsNullOrWhiteSpace(loader.ActiveBodyId)) throw new InvalidDataException("Active BodyRig body id is missing");

            // Re-hash the files after UniVRM has loaded the avatar. The loader
            // already verifies them before/during load; this post-load check makes
            // the evidence fail closed if runtime files are substituted before the
            // physical probe is committed.
            var avatarHash = Sha256File(avatarPath);
            var bodyprintHash = Sha256File(bodyprintPath);
            if (!string.Equals(avatarHash, loader.ActiveAvatarSha256, StringComparison.Ordinal))
                throw new InvalidDataException("Renderer probe avatar.vrm bytes no longer match the Gate A runtime manifest");
            if (!string.Equals(bodyprintHash, loader.ActiveBodyprintSha256, StringComparison.Ordinal))
                throw new InvalidDataException("Renderer probe bodyprint.json bytes no longer match the Gate A runtime manifest");

            // A valid Humanoid is not enough for high-fidelity acceptance. If the
            // exact VRM bytes carry one of BodyRig's promoted component nodes, UniVRM
            // must also have instantiated that node as an active skinned renderer.
            // This closes the gap where metadata/GLB payload could be correct while
            // the physical Unity render still showed the legacy mannequin only.
            RequireExpectedComponentRenderers(avatarPath, loader.Active.gameObject);

            var bodyRigRevision = BodyRigBuildProvenance.RequireRevision();
            var deviceModel = string.IsNullOrWhiteSpace(SystemInfo.deviceModel) ? "unknown" : SystemInfo.deviceModel.Trim();
            var platform = ResolvePhysicalPlatform(deviceModel);
            var buildGuid = Application.buildGUID;
            if (string.IsNullOrWhiteSpace(buildGuid))
                throw new InvalidDataException("Physical renderer probe requires a non-empty Unity build GUID");

            var report = new ProbeReport
            {
                observed_at = DateTime.UtcNow.ToString("o"),
                bodyrig_revision = bodyRigRevision,
                platform = platform,
                unity_platform = Application.platform.ToString(),
                unity_version = Application.unityVersion,
                build_guid = buildGuid,
                device_model = deviceModel,
                graphics_device = string.IsNullOrWhiteSpace(SystemInfo.graphicsDeviceName) ? "unknown" : SystemInfo.graphicsDeviceName,
                body_id = loader.ActiveBodyId,
                package_sha256 = packageHash,
                runtime_manifest_sha256 = Sha256File(fullManifestPath),
                avatar_sha256 = avatarHash,
                bodyprint_sha256 = bodyprintHash,
                vrm10_loaded = true,
                humanoid_valid = true,
                required_bones_valid = true,
                active_renderer = new RendererIdentity { name = rendererName.Trim(), version = rendererVersion.Trim() },
            };

            var fullOutputPath = Path.GetFullPath(reportPath);
            if (File.Exists(fullOutputPath)) throw new IOException($"Renderer probe evidence already exists: {fullOutputPath}");
            var outputDirectory = Path.GetDirectoryName(fullOutputPath);
            if (string.IsNullOrEmpty(outputDirectory)) throw new InvalidDataException("Renderer probe output has no parent directory");
            Directory.CreateDirectory(outputDirectory);
            var temporary = fullOutputPath + "." + Guid.NewGuid().ToString("N") + ".tmp";
            try
            {
                File.WriteAllText(temporary, JsonUtility.ToJson(report, true) + "\n", new UTF8Encoding(false));
                File.Move(temporary, fullOutputPath);
            }
            finally { if (File.Exists(temporary)) File.Delete(temporary); }

            LastProbePath = fullOutputPath;
            Debug.Log($"BodyRig renderer probe: PASS | {report.platform} | revision {report.bodyrig_revision} | {report.device_model} | {fullOutputPath}", this);
            return fullOutputPath;
        }

        private static void RequireExpectedComponentRenderers(string avatarPath, GameObject activeRoot)
        {
            if (activeRoot == null) throw new InvalidDataException("Renderer probe active VRM root is missing");
            if (!File.Exists(avatarPath)) throw new FileNotFoundException("Renderer probe avatar.vrm is missing", avatarPath);
            var bytes = File.ReadAllBytes(avatarPath);
            foreach (var expected in ExpectedRenderPayloads)
            {
                if (!ContainsAscii(bytes, expected.NodeName)) continue;

                Transform matched = null;
                foreach (var transform in activeRoot.GetComponentsInChildren<Transform>(true))
                {
                    if (!string.Equals(transform.name, expected.NodeName, StringComparison.Ordinal)) continue;
                    if (matched != null)
                        throw new InvalidDataException($"Renderer probe found multiple instantiated {expected.Label} nodes named {expected.NodeName}");
                    matched = transform;
                }
                if (matched == null)
                    throw new InvalidDataException($"Renderer probe VRM carries {expected.Label} payload {expected.NodeName}, but UniVRM did not instantiate that node");
                if (!matched.gameObject.activeInHierarchy)
                    throw new InvalidDataException($"Renderer probe instantiated {expected.Label} payload {expected.NodeName}, but its GameObject is inactive");

                var renderers = matched.GetComponentsInChildren<SkinnedMeshRenderer>(true);
                var visible = false;
                foreach (var renderer in renderers)
                {
                    if (renderer == null || !renderer.enabled || renderer.forceRenderingOff || !renderer.gameObject.activeInHierarchy)
                        continue;
                    if (renderer.sharedMesh == null || renderer.sharedMesh.vertexCount <= 0)
                        continue;
                    if (renderer.sharedMaterials == null || renderer.sharedMaterials.Length == 0)
                        continue;
                    visible = true;
                    break;
                }
                if (!visible)
                    throw new InvalidDataException($"Renderer probe instantiated {expected.Label} payload {expected.NodeName}, but no active skinned renderer with mesh/materials is visible");
            }
        }

        private static bool ContainsAscii(byte[] haystack, string value)
        {
            if (haystack == null || string.IsNullOrEmpty(value)) return false;
            var needle = Encoding.UTF8.GetBytes(value);
            if (needle.Length == 0 || needle.Length > haystack.Length) return false;
            for (var start = 0; start <= haystack.Length - needle.Length; start++)
            {
                var matches = true;
                for (var offset = 0; offset < needle.Length; offset++)
                {
                    if (haystack[start + offset] == needle[offset]) continue;
                    matches = false;
                    break;
                }
                if (matches) return true;
            }
            return false;
        }

        private static string ResolvePhysicalPlatform(string deviceModel)
        {
            switch (Application.platform)
            {
                case RuntimePlatform.WindowsPlayer:
                    return "windows-unity-univrm";
                case RuntimePlatform.WindowsEditor:
                    throw new PlatformNotSupportedException("BodyRig Windows physical acceptance requires a built WindowsPlayer, not Unity Editor");
                case RuntimePlatform.Android:
                    if (string.IsNullOrWhiteSpace(deviceModel) ||
                        (deviceModel.IndexOf("Quest", StringComparison.OrdinalIgnoreCase) < 0 &&
                         deviceModel.IndexOf("Oculus", StringComparison.OrdinalIgnoreCase) < 0))
                        throw new PlatformNotSupportedException($"BodyRig Quest physical acceptance requires a Quest/Oculus device model, got '{deviceModel}'");
                    return "android-quest-class";
                default:
                    throw new PlatformNotSupportedException($"BodyRig physical acceptance does not support Unity platform {Application.platform}");
            }
        }

        private static string Sha256File(string path)
        {
            if (!File.Exists(path)) throw new FileNotFoundException("Renderer probe input file is missing", path);
            using (var stream = File.OpenRead(path))
            using (var sha = SHA256.Create())
            {
                var digest = sha.ComputeHash(stream);
                var builder = new StringBuilder(digest.Length * 2);
                foreach (var value in digest) builder.Append(value.ToString("x2"));
                return builder.ToString();
            }
        }

        private static bool IsLowerHexSha256(string value)
        {
            if (string.IsNullOrEmpty(value) || value.Length != 64) return false;
            foreach (var character in value)
                if (!((character >= '0' && character <= '9') || (character >= 'a' && character <= 'f'))) return false;
            return true;
        }
    }
}
