using System;
using System.Collections.Generic;
using System.IO;
using System.Security.Cryptography;
using System.Text;
using System.Threading.Tasks;
using UniGLTF;
using UniVRM10;
using UnityEngine;

namespace BodyRig.ReferenceRenderer
{
    /// <summary>
    /// Machine-only Quest 2 probe for the Photoreal V2 P3 student.
    /// It proves exact artifact bytes, real UniVRM loading and measured frame timing.
    /// It deliberately does not claim stereo/VR-safe pacing until the canonical
    /// reference project has a pinned XR runtime.
    /// </summary>
    public sealed class BodyRigP3Quest2Probe : MonoBehaviour
    {
        [Serializable]
        private sealed class Artifact
        {
            public string kind;
            public string relative_path;
            public long size_bytes;
            public string sha256;
        }

        [Serializable]
        private sealed class RuntimeManifest
        {
            public string format;
            public int version;
            public string bodyrig_revision;
            public string p3_device_runtime_review_plan_sha256;
            public string performer_id;
            public string target_device_family;
            public string target_device_model;
            public string avatar_relative_path;
            public Artifact[] student_artifacts;
        }

        [Serializable]
        private sealed class InstalledArtifact
        {
            public string relative_path;
            public string sha256;
        }

        [Serializable]
        private sealed class ProbeReport
        {
            public string format = "bodyrig-photoreal-p3-quest2-machine-probe";
            public int version = 1;
            public string observed_at;
            public string bodyrig_revision;
            public string p3_device_runtime_review_plan_sha256;
            public string performer_id;
            public string target_device_family;
            public string target_device_model;
            public string observed_device_model;
            public string unity_version;
            public string build_guid;
            public string graphics_device;
            public int student_artifact_count;
            public InstalledArtifact[] installed_student_artifacts;
            public bool installed_student_hashes_verified_on_device;
            public bool vrm10_loaded;
            public bool humanoid_valid;
            public bool required_bones_valid;
            public float observed_refresh_hz;
            public float p95_frame_time_ms;
            public int frame_time_sample_count;
            public bool runtime_loaded;
            public bool stereo_rendering_observed;
            public bool vr_safe_frame_pacing_observed;
            public string stereo_authority;
            public bool human_runtime_visual_acceptance_required;
            public bool runtime_acceptance_authority;
            public bool photoreal_acceptance_authority;
            public bool production_activation;
        }

        private static readonly HumanBodyBones[] RequiredBones =
        {
            HumanBodyBones.Hips,
            HumanBodyBones.Spine,
            HumanBodyBones.Head,
            HumanBodyBones.LeftUpperLeg,
            HumanBodyBones.LeftLowerLeg,
            HumanBodyBones.LeftFoot,
            HumanBodyBones.RightUpperLeg,
            HumanBodyBones.RightLowerLeg,
            HumanBodyBones.RightFoot,
            HumanBodyBones.LeftUpperArm,
            HumanBodyBones.LeftLowerArm,
            HumanBodyBones.LeftHand,
            HumanBodyBones.RightUpperArm,
            HumanBodyBones.RightLowerArm,
            HumanBodyBones.RightHand,
        };

        private Vrm10Instance _active;

        public Vrm10Instance Active => _active;

        public async Task<string> RunProbeAsync(string manifestPath, string outputPath)
        {
            var manifestFile = RequireFile(manifestPath, "P3 runtime manifest");
            var outputFile = Path.GetFullPath(outputPath);
            if (File.Exists(outputFile))
                throw new IOException("P3 Quest2 machine probe already exists: " + outputFile);

            RuntimeManifest manifest;
            try
            {
                manifest = JsonUtility.FromJson<RuntimeManifest>(File.ReadAllText(manifestFile));
            }
            catch (Exception exception)
            {
                throw new InvalidDataException("P3 runtime manifest is not valid JSON", exception);
            }

            ValidateManifest(manifest);
            var buildRevision = BodyRigBuildProvenance.RequireRevision();
            if (!string.Equals(manifest.bodyrig_revision, buildRevision, StringComparison.Ordinal))
                throw new InvalidDataException("P3 runtime manifest revision differs from exact renderer build revision");

            var deviceModel = string.IsNullOrWhiteSpace(SystemInfo.deviceModel)
                ? "unknown"
                : SystemInfo.deviceModel.Trim();
            if (Application.platform != RuntimePlatform.Android)
                throw new PlatformNotSupportedException("P3 Quest2 machine probe requires an Android player");
            if (deviceModel.IndexOf("Quest 2", StringComparison.OrdinalIgnoreCase) < 0 &&
                deviceModel.IndexOf("Oculus Quest 2", StringComparison.OrdinalIgnoreCase) < 0)
                throw new PlatformNotSupportedException("P3 machine probe requires an exact Quest 2 device, got '" + deviceModel + "'");

            var manifestDirectory = Path.GetDirectoryName(manifestFile);
            if (string.IsNullOrEmpty(manifestDirectory))
                throw new InvalidDataException("P3 runtime manifest has no parent directory");
            var studentRoot = Path.GetFullPath(Path.Combine(manifestDirectory, "student"));
            if (!Directory.Exists(studentRoot))
                throw new DirectoryNotFoundException("P3 student root is missing: " + studentRoot);

            var seen = new HashSet<string>(StringComparer.Ordinal);
            var installed = new List<InstalledArtifact>();
            string avatarPath = null;
            string avatarSha = null;
            foreach (var artifact in manifest.student_artifacts)
            {
                var relative = RequireRelativePath(artifact.relative_path);
                if (!seen.Add(relative))
                    throw new InvalidDataException("P3 runtime manifest repeats student artifact: " + relative);
                if (!IsLowerHexSha256(artifact.sha256) || artifact.size_bytes < 1)
                    throw new InvalidDataException("P3 runtime manifest artifact metadata is invalid: " + relative);

                var fullPath = Path.GetFullPath(Path.Combine(studentRoot, relative.Replace('/', Path.DirectorySeparatorChar)));
                RequireChild(studentRoot, fullPath, relative);
                if (!File.Exists(fullPath))
                    throw new FileNotFoundException("P3 student artifact is missing", fullPath);
                var info = new FileInfo(fullPath);
                if (info.Length != artifact.size_bytes)
                    throw new InvalidDataException("P3 student artifact size drifted on device: " + relative);
                var observedSha = Sha256File(fullPath);
                if (!string.Equals(observedSha, artifact.sha256, StringComparison.Ordinal))
                    throw new InvalidDataException("P3 student artifact bytes drifted on device: " + relative);

                installed.Add(new InstalledArtifact
                {
                    relative_path = relative,
                    sha256 = observedSha,
                });

                if (string.Equals(relative, manifest.avatar_relative_path, StringComparison.Ordinal))
                {
                    if (avatarPath != null)
                        throw new InvalidDataException("P3 runtime manifest resolves multiple avatar artifacts");
                    avatarPath = fullPath;
                    avatarSha = observedSha;
                }
            }

            if (avatarPath == null || avatarSha == null)
                throw new InvalidDataException("P3 runtime manifest does not resolve its avatar artifact");

            var actual = new HashSet<string>(StringComparer.Ordinal);
            foreach (var path in Directory.GetFiles(studentRoot, "*", SearchOption.AllDirectories))
            {
                var relative = path.Substring(studentRoot.Length)
                    .TrimStart(Path.DirectorySeparatorChar, Path.AltDirectorySeparatorChar)
                    .Replace(Path.DirectorySeparatorChar, '/');
                actual.Add(relative);
            }
            if (!actual.SetEquals(seen))
                throw new InvalidDataException("P3 student artifact universe drifted on device");

            Vrm10Instance candidate = null;
            try
            {
                candidate = await Vrm10.LoadPathAsync(
                    avatarPath,
                    canLoadVrm0X: false,
                    showMeshes: false);

                if (candidate == null)
                    throw new InvalidDataException("UniVRM returned no P3 VRM 1.0 instance");

                var animator = candidate.GetComponent<Animator>();
                ValidateHumanoid(animator);

                var runtime = candidate.GetComponent<RuntimeGltfInstance>();
                if (runtime == null)
                    throw new InvalidDataException("P3 UniVRM instance has no RuntimeGltfInstance");

                if (!string.Equals(Sha256File(avatarPath), avatarSha, StringComparison.Ordinal))
                    throw new InvalidDataException("P3 avatar bytes changed during UniVRM load");

                runtime.ShowMeshes();
                var previous = _active;
                _active = candidate;
                candidate = null;
                if (previous != null)
                    Destroy(previous.gameObject);
            }
            finally
            {
                if (candidate != null)
                    Destroy(candidate.gameObject);
            }

            FrameAvatar(_active);

            for (var index = 0; index < 30; index++)
                await Task.Yield();

            var samples = new List<float>();
            for (var index = 0; index < 240; index++)
            {
                await Task.Yield();
                var delta = Time.unscaledDeltaTime * 1000f;
                if (delta > 0f && !float.IsNaN(delta) && !float.IsInfinity(delta))
                    samples.Add(delta);
            }
            if (samples.Count < 120)
                throw new InvalidDataException("P3 Quest2 machine probe did not collect enough frame-time samples");
            samples.Sort();
            var p95Index = Mathf.Clamp(Mathf.CeilToInt(samples.Count * 0.95f) - 1, 0, samples.Count - 1);
            var p95 = samples[p95Index];

            var refresh = (float)Screen.currentResolution.refreshRateRatio.value;
            if (!(refresh > 0f) || float.IsNaN(refresh) || float.IsInfinity(refresh))
                throw new InvalidDataException("P3 Quest2 machine probe could not resolve physical refresh rate");

            var buildGuid = Application.buildGUID;
            if (string.IsNullOrWhiteSpace(buildGuid))
                throw new InvalidDataException("P3 Quest2 machine probe requires a non-empty Unity build GUID");

            var report = new ProbeReport
            {
                observed_at = DateTime.UtcNow.ToString("o"),
                bodyrig_revision = buildRevision,
                p3_device_runtime_review_plan_sha256 = manifest.p3_device_runtime_review_plan_sha256,
                performer_id = manifest.performer_id,
                target_device_family = manifest.target_device_family,
                target_device_model = manifest.target_device_model,
                observed_device_model = deviceModel,
                unity_version = Application.unityVersion,
                build_guid = buildGuid,
                graphics_device = string.IsNullOrWhiteSpace(SystemInfo.graphicsDeviceName) ? "unknown" : SystemInfo.graphicsDeviceName,
                student_artifact_count = installed.Count,
                installed_student_artifacts = installed.ToArray(),
                installed_student_hashes_verified_on_device = true,
                vrm10_loaded = true,
                humanoid_valid = true,
                required_bones_valid = true,
                observed_refresh_hz = refresh,
                p95_frame_time_ms = p95,
                frame_time_sample_count = samples.Count,
                runtime_loaded = true,

                // The current canonical reference project is Android/UniVRM-only.
                // Do not infer VR stereo authority from "running on Quest hardware".
                stereo_rendering_observed = false,
                vr_safe_frame_pacing_observed = false,
                stereo_authority = "blocked-until-canonical-xr-runtime-is-pinned",
                human_runtime_visual_acceptance_required = true,
                runtime_acceptance_authority = false,
                photoreal_acceptance_authority = false,
                production_activation = false,
            };

            var outputDirectory = Path.GetDirectoryName(outputFile);
            if (string.IsNullOrEmpty(outputDirectory))
                throw new InvalidDataException("P3 Quest2 machine probe output has no parent directory");
            Directory.CreateDirectory(outputDirectory);
            WriteCreateOnlyJson(outputFile, report);
            return outputFile;
        }

        private static void ValidateManifest(RuntimeManifest manifest)
        {
            if (manifest == null ||
                manifest.format != "bodyrig-photoreal-p3-quest2-reference-runtime" ||
                manifest.version != 1)
                throw new InvalidDataException("Unsupported P3 reference runtime manifest format/version");
            if (!IsLowerHexGitSha(manifest.bodyrig_revision))
                throw new InvalidDataException("P3 runtime manifest BodyRig revision is invalid");
            if (!IsLowerHexSha256(manifest.p3_device_runtime_review_plan_sha256))
                throw new InvalidDataException("P3 runtime review plan SHA-256 is invalid");
            if (string.IsNullOrWhiteSpace(manifest.performer_id))
                throw new InvalidDataException("P3 runtime manifest performer id is missing");
            if (manifest.target_device_family != "meta-quest" || manifest.target_device_model != "quest-2")
                throw new InvalidDataException("P3 reference runtime manifest does not target Quest 2");
            manifest.avatar_relative_path = RequireRelativePath(manifest.avatar_relative_path);
            if (manifest.student_artifacts == null || manifest.student_artifacts.Length < 1)
                throw new InvalidDataException("P3 runtime manifest contains no student artifacts");
        }

        private static string RequireRelativePath(string value)
        {
            if (string.IsNullOrWhiteSpace(value))
                throw new InvalidDataException("P3 artifact path is empty");
            var clean = value.Trim().Replace('\\', '/');
            var first = clean.Split('/')[0];
            if (clean.StartsWith("/", StringComparison.Ordinal) ||
                clean.StartsWith("../", StringComparison.Ordinal) ||
                ("/" + clean + "/").Contains("/../") ||
                first.Contains(":"))
                throw new InvalidDataException("P3 artifact path escapes its root: " + clean);
            return clean;
        }

        private static void RequireChild(string root, string path, string label)
        {
            var normalizedRoot = Path.GetFullPath(root).TrimEnd(Path.DirectorySeparatorChar) + Path.DirectorySeparatorChar;
            var normalizedPath = Path.GetFullPath(path);
            if (!normalizedPath.StartsWith(normalizedRoot, StringComparison.Ordinal))
                throw new InvalidDataException("P3 artifact path escapes student root: " + label);
        }

        private static string RequireFile(string path, string label)
        {
            if (string.IsNullOrWhiteSpace(path))
                throw new ArgumentException(label + " path is required");
            var full = Path.GetFullPath(path);
            if (!File.Exists(full))
                throw new FileNotFoundException(label + " not found", full);
            return full;
        }

        private static void ValidateHumanoid(Animator animator)
        {
            if (animator == null || animator.avatar == null || !animator.avatar.isValid || !animator.avatar.isHuman)
                throw new InvalidDataException("P3 VRM does not expose a valid Unity Humanoid avatar");
            foreach (var bone in RequiredBones)
                if (animator.GetBoneTransform(bone) == null)
                    throw new InvalidDataException("P3 VRM is missing required humanoid bone: " + bone);
        }

        private static void FrameAvatar(Vrm10Instance avatar)
        {
            if (avatar == null || Camera.main == null)
                return;
            var renderers = avatar.GetComponentsInChildren<Renderer>(true);
            if (renderers == null || renderers.Length == 0)
                return;
            var bounds = renderers[0].bounds;
            for (var index = 1; index < renderers.Length; index++)
                bounds.Encapsulate(renderers[index].bounds);
            var height = Mathf.Max(bounds.size.y, 1f);
            var target = bounds.center + Vector3.up * height * 0.03f;
            Camera.main.transform.position = target + new Vector3(0f, 0f, height * 1.65f);
            Camera.main.transform.LookAt(target);
        }

        private static void WriteCreateOnlyJson(string path, object value)
        {
            if (File.Exists(path))
                throw new IOException("P3 Quest2 probe evidence already exists: " + path);
            var temporary = path + "." + Guid.NewGuid().ToString("N") + ".tmp";
            try
            {
                File.WriteAllText(temporary, JsonUtility.ToJson(value, true) + "\n", new UTF8Encoding(false));
                File.Move(temporary, path);
            }
            finally
            {
                if (File.Exists(temporary))
                    File.Delete(temporary);
            }
        }

        private static string Sha256File(string path)
        {
            using (var stream = File.OpenRead(path))
            using (var sha = SHA256.Create())
            {
                var digest = sha.ComputeHash(stream);
                var builder = new StringBuilder(digest.Length * 2);
                foreach (var value in digest)
                    builder.Append(value.ToString("x2"));
                return builder.ToString();
            }
        }

        private static bool IsLowerHexSha256(string value)
        {
            if (string.IsNullOrEmpty(value) || value.Length != 64)
                return false;
            foreach (var ch in value)
                if (!((ch >= '0' && ch <= '9') || (ch >= 'a' && ch <= 'f')))
                    return false;
            return true;
        }

        private static bool IsLowerHexGitSha(string value)
        {
            if (string.IsNullOrEmpty(value) || value.Length != 40)
                return false;
            foreach (var ch in value)
                if (!((ch >= '0' && ch <= '9') || (ch >= 'a' && ch <= 'f')))
                    return false;
            return true;
        }
    }
}
