using System;
using System.IO;
using System.Security.Cryptography;
using System.Text;
using System.Threading;
using System.Threading.Tasks;
using UniGLTF;
using UniVRM10;
using UnityEngine;

namespace BodyRig.ReferenceRenderer
{
    /// <summary>
    /// Thin physical-acceptance loader for a BodyRig materialized runtime.
    /// It intentionally contains no cloning/recovery logic and exposes no
    /// public loose-VRM loading path: acceptance starts from runtime-manifest.json.
    /// </summary>
    public sealed class BodyRigAvatarLoader : MonoBehaviour
    {
        [Serializable]
        private sealed class RuntimeManifest
        {
            public string format;
            public int version;
            public string body_id;
            public string body_name;
            public string package_sha256;
            public string avatar;
            public string avatar_sha256;
            public string bodyprint;
            public string bodyprint_sha256;
            public string[] payloads;
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
        private Animator _animator;

        public Vrm10Instance Active => _active;
        public Animator Animator => _animator;
        public string ActiveBodyId { get; private set; }
        public string ActivePackageSha256 { get; private set; }
        public string ActiveAvatarSha256 { get; private set; }
        public string ActiveBodyprintSha256 { get; private set; }
        public string ActiveRuntimeManifestPath { get; private set; }

        public async Task LoadRuntimeAsync(string runtimeManifestPath, CancellationToken cancellationToken = default)
        {
            if (string.IsNullOrWhiteSpace(runtimeManifestPath))
            {
                throw new ArgumentException("BodyRig runtime manifest path is required", nameof(runtimeManifestPath));
            }

            var fullManifestPath = Path.GetFullPath(runtimeManifestPath);
            if (!File.Exists(fullManifestPath))
            {
                throw new FileNotFoundException("BodyRig runtime-manifest.json was not found", fullManifestPath);
            }
            if (!string.Equals(Path.GetFileName(fullManifestPath), "runtime-manifest.json", StringComparison.Ordinal))
            {
                throw new InvalidDataException("BodyRig acceptance loader requires runtime-manifest.json");
            }

            RuntimeManifest manifest;
            try
            {
                manifest = JsonUtility.FromJson<RuntimeManifest>(File.ReadAllText(fullManifestPath));
            }
            catch (Exception exception)
            {
                throw new InvalidDataException("BodyRig runtime manifest is not valid JSON", exception);
            }
            ValidateRuntimeManifest(manifest);

            var runtimeDirectory = Path.GetDirectoryName(fullManifestPath);
            if (string.IsNullOrEmpty(runtimeDirectory))
            {
                throw new InvalidDataException("BodyRig runtime manifest has no parent directory");
            }
            var avatarPath = Path.GetFullPath(Path.Combine(runtimeDirectory, manifest.avatar));
            var bodyprintPath = Path.GetFullPath(Path.Combine(runtimeDirectory, manifest.bodyprint));
            var normalizedRuntimeDirectory = Path.GetFullPath(runtimeDirectory);
            if (!string.Equals(Path.GetDirectoryName(avatarPath), normalizedRuntimeDirectory, StringComparison.OrdinalIgnoreCase) ||
                !string.Equals(Path.GetDirectoryName(bodyprintPath), normalizedRuntimeDirectory, StringComparison.OrdinalIgnoreCase))
            {
                throw new InvalidDataException("BodyRig runtime payload escaped the materialized runtime directory");
            }
            if (!File.Exists(avatarPath))
            {
                throw new FileNotFoundException("BodyRig materialized avatar.vrm was not found", avatarPath);
            }
            if (!File.Exists(bodyprintPath))
            {
                throw new FileNotFoundException("BodyRig materialized bodyprint.json was not found", bodyprintPath);
            }
            RequireSha256(avatarPath, manifest.avatar_sha256, "avatar.vrm");
            RequireSha256(bodyprintPath, manifest.bodyprint_sha256, "bodyprint.json");

            // Keep the previous runtime identity until the replacement avatar has
            // imported, remained byte-stable and passed all Unity/UniVRM Humanoid validation.
            await LoadAvatarPathAsync(avatarPath, manifest.avatar_sha256, cancellationToken);
            RequireSha256(bodyprintPath, manifest.bodyprint_sha256, "bodyprint.json");
            ActiveBodyId = manifest.body_id;
            ActivePackageSha256 = manifest.package_sha256.ToLowerInvariant();
            ActiveAvatarSha256 = manifest.avatar_sha256.ToLowerInvariant();
            ActiveBodyprintSha256 = manifest.bodyprint_sha256.ToLowerInvariant();
            ActiveRuntimeManifestPath = fullManifestPath;
        }

        private async Task LoadAvatarPathAsync(string path, string expectedSha256, CancellationToken cancellationToken)
        {
            var fullPath = Path.GetFullPath(path);
            if (!File.Exists(fullPath))
            {
                throw new FileNotFoundException("BodyRig materialized avatar.vrm was not found", fullPath);
            }

            Vrm10Instance candidate = null;
            try
            {
                candidate = await Vrm10.LoadPathAsync(
                    fullPath,
                    canLoadVrm0X: false,
                    showMeshes: false,
                    ct: cancellationToken);

                if (candidate == null)
                {
                    throw new InvalidDataException("UniVRM returned no VRM 1.0 instance");
                }

                var candidateAnimator = candidate.GetComponent<Animator>();
                ValidateHumanoid(candidateAnimator);

                var runtime = candidate.GetComponent<RuntimeGltfInstance>();
                if (runtime == null)
                {
                    throw new InvalidDataException("UniVRM instance has no RuntimeGltfInstance");
                }

                // Close the pre-check -> UniVRM path-load race before committing
                // the candidate as the active physical-acceptance avatar.
                RequireSha256(fullPath, expectedSha256, "avatar.vrm");
                runtime.ShowMeshes();

                var previous = _active;
                _active = candidate;
                _animator = candidateAnimator;
                candidate = null;

                if (previous != null)
                {
                    Destroy(previous.gameObject);
                }
            }
            finally
            {
                if (candidate != null)
                {
                    Destroy(candidate.gameObject);
                }
            }
        }

        public Transform GetBone(HumanBodyBones bone)
        {
            if (_animator == null)
            {
                throw new InvalidOperationException("No BodyRig avatar is active");
            }

            return _animator.GetBoneTransform(bone);
        }

        private static void ValidateRuntimeManifest(RuntimeManifest manifest)
        {
            if (manifest == null || manifest.format != "bodyrig-runtime-assets" || manifest.version != 1)
            {
                throw new InvalidDataException("Unsupported BodyRig runtime manifest format/version");
            }
            if (string.IsNullOrWhiteSpace(manifest.body_id) || string.IsNullOrWhiteSpace(manifest.body_name))
            {
                throw new InvalidDataException("BodyRig runtime manifest has no body identity");
            }
            if (!IsLowerHexSha256(manifest.package_sha256))
            {
                throw new InvalidDataException("BodyRig runtime manifest package SHA-256 is invalid");
            }
            if (!IsLowerHexSha256(manifest.avatar_sha256) || !IsLowerHexSha256(manifest.bodyprint_sha256))
            {
                throw new InvalidDataException("BodyRig runtime manifest payload SHA-256 is invalid");
            }
            if (manifest.avatar != "avatar.vrm" || manifest.bodyprint != "bodyprint.json")
            {
                throw new InvalidDataException("BodyRig runtime manifest contains unexpected payload paths");
            }
            if (manifest.payloads == null ||
                Array.IndexOf(manifest.payloads, "avatar.vrm") < 0 ||
                Array.IndexOf(manifest.payloads, "bodyprint.json") < 0)
            {
                throw new InvalidDataException("BodyRig runtime manifest is missing required payloads");
            }
        }

        private static void RequireSha256(string path, string expectedSha256, string label)
        {
            var actual = Sha256File(path);
            if (!string.Equals(actual, expectedSha256, StringComparison.Ordinal))
            {
                throw new InvalidDataException($"BodyRig materialized {label} SHA-256 does not match runtime manifest");
            }
        }

        private static string Sha256File(string path)
        {
            if (!File.Exists(path)) throw new FileNotFoundException("BodyRig runtime payload is missing", path);
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
            if (string.IsNullOrEmpty(value) || value.Length != 64)
            {
                return false;
            }
            foreach (var character in value)
            {
                if (!((character >= '0' && character <= '9') || (character >= 'a' && character <= 'f'))
                {
                    return false;
                }
            }
            return true;
        }

        private static void ValidateHumanoid(Animator animator)
        {
            if (animator == null || animator.avatar == null || !animator.avatar.isValid || !animator.avatar.isHuman)
            {
                throw new InvalidDataException("Imported VRM does not expose a valid Unity Humanoid avatar");
            }

            foreach (var bone in RequiredBones)
            {
                if (animator.GetBoneTransform(bone) == null)
                {
                    throw new InvalidDataException($"Imported VRM is missing required humanoid bone: {bone}");
                }
            }
        }

        private void OnDestroy()
        {
            if (_active != null)
            {
                Destroy(_active.gameObject);
                _active = null;
                _animator = null;
            }
            ActiveBodyId = null;
            ActivePackageSha256 = null;
            ActiveAvatarSha256 = null;
            ActiveBodyprintSha256 = null;
            ActiveRuntimeManifestPath = null;
        }
    }
}
