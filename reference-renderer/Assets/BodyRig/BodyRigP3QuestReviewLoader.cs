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
    /// Review-only loader for the exact modular P3 Quest 2 student.
    ///
    /// This class deliberately does not accept BodyRig Gate-A runtime manifests,
    /// .mrbody packages or BodyPrint. Conversely, the production acceptance
    /// loader does not call this class. The two authority surfaces remain
    /// separate.
    /// </summary>
    public sealed class BodyRigP3QuestReviewLoader : MonoBehaviour
    {
        [Serializable]
        private sealed class ReviewManifest
        {
            public string format;
            public int version;
            public string bodyrig_revision;
            public string performer_id;
            public string selected_epoch_id;
            public string teacher_input_sha256;
            public string p3_device_distillation_plan_sha256;
            public string p3_device_distillation_execution_receipt_sha256;
            public string p3_device_runtime_review_plan_sha256;
            public string target_device_family;
            public string target_device_model;
            public string student_representation;
            public string[] student_components;
            public string avatar;
            public string avatar_sha256;
            public string basecolor;
            public string basecolor_sha256;
            public string provenance;
            public string provenance_sha256;
            public bool physical_review_only;
            public bool comparison_only;
            public bool physical_device_evidence_present;
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
        private Animator _animator;

        public Vrm10Instance Active => _active;
        public Animator Animator => _animator;
        public string ActiveManifestPath { get; private set; }
        public string ActiveManifestSha256 { get; private set; }
        public string ActiveBodyRigRevision { get; private set; }
        public string ActivePerformerId { get; private set; }
        public string ActiveRuntimeReviewPlanSha256 { get; private set; }
        public string ActiveAvatarSha256 { get; private set; }
        public string ActiveBasecolorSha256 { get; private set; }
        public string ActiveProvenanceSha256 { get; private set; }

        public async Task LoadReviewAsync(
            string reviewManifestPath,
            CancellationToken cancellationToken = default)
        {
            if (string.IsNullOrWhiteSpace(reviewManifestPath))
            {
                throw new ArgumentException(
                    "P3 Quest review manifest path is required",
                    nameof(reviewManifestPath));
            }

            var fullManifestPath = Path.GetFullPath(reviewManifestPath);
            if (!File.Exists(fullManifestPath))
            {
                throw new FileNotFoundException(
                    "P3 Quest review manifest was not found",
                    fullManifestPath);
            }
            if (!string.Equals(
                    Path.GetFileName(fullManifestPath),
                    "p3-quest2-review-manifest.json",
                    StringComparison.Ordinal))
            {
                throw new InvalidDataException(
                    "P3 Quest review loader requires p3-quest2-review-manifest.json");
            }

            ReviewManifest manifest;
            try
            {
                var raw = File.ReadAllText(fullManifestPath);
                JsonUtility.ValidateP3QuestReviewManifestJson(raw);
                manifest = JsonUtility.FromJson<ReviewManifest>(raw);
            }
            catch (Exception exception)
            {
                throw new InvalidDataException(
                    "P3 Quest review manifest is not valid",
                    exception);
            }
            ValidateManifest(manifest);

            var root = Path.GetDirectoryName(fullManifestPath);
            if (string.IsNullOrEmpty(root))
            {
                throw new InvalidDataException(
                    "P3 Quest review manifest has no parent directory");
            }
            root = Path.GetFullPath(root);

            var avatarPath = ResolveDirectChild(root, manifest.avatar);
            var basecolorPath = ResolveDirectChild(root, manifest.basecolor);
            var provenancePath = ResolveDirectChild(root, manifest.provenance);

            RequireSha256(avatarPath, manifest.avatar_sha256, "avatar.vrm");
            RequireSha256(basecolorPath, manifest.basecolor_sha256, "basecolor.png");
            RequireSha256(
                provenancePath,
                manifest.provenance_sha256,
                "quest2-modular-provenance.json");

            var candidate = await LoadAvatarAsync(
                avatarPath,
                manifest.avatar_sha256,
                cancellationToken);

            // Close the manifest/payload race after UniVRM has parsed the avatar
            // but before review identity becomes active.
            RequireSha256(fullManifestPath, Sha256File(fullManifestPath), "review manifest");
            RequireSha256(avatarPath, manifest.avatar_sha256, "avatar.vrm");
            RequireSha256(basecolorPath, manifest.basecolor_sha256, "basecolor.png");
            RequireSha256(
                provenancePath,
                manifest.provenance_sha256,
                "quest2-modular-provenance.json");

            var previous = _active;
            _active = candidate;
            _animator = candidate.GetComponent<Animator>();
            if (previous != null)
            {
                Destroy(previous.gameObject);
            }

            ActiveManifestPath = fullManifestPath;
            ActiveManifestSha256 = Sha256File(fullManifestPath);
            ActiveBodyRigRevision = manifest.bodyrig_revision;
            ActivePerformerId = manifest.performer_id;
            ActiveRuntimeReviewPlanSha256 =
                manifest.p3_device_runtime_review_plan_sha256;
            ActiveAvatarSha256 = manifest.avatar_sha256;
            ActiveBasecolorSha256 = manifest.basecolor_sha256;
            ActiveProvenanceSha256 = manifest.provenance_sha256;
        }

        public Transform GetBone(HumanBodyBones bone)
        {
            if (_animator == null)
            {
                throw new InvalidOperationException(
                    "No P3 Quest review avatar is active");
            }
            return _animator.GetBoneTransform(bone);
        }

        private static async Task<Vrm10Instance> LoadAvatarAsync(
            string path,
            string expectedSha256,
            CancellationToken cancellationToken)
        {
            Vrm10Instance candidate = null;
            try
            {
                candidate = await Vrm10.LoadPathAsync(
                    path,
                    canLoadVrm0X: false,
                    showMeshes: false,
                    ct: cancellationToken);
                if (candidate == null)
                {
                    throw new InvalidDataException(
                        "UniVRM returned no P3 Quest VRM 1.0 instance");
                }

                var animator = candidate.GetComponent<Animator>();
                ValidateHumanoid(animator);

                var runtime = candidate.GetComponent<RuntimeGltfInstance>();
                if (runtime == null)
                {
                    throw new InvalidDataException(
                        "P3 Quest review avatar has no RuntimeGltfInstance");
                }

                RequireSha256(path, expectedSha256, "avatar.vrm");
                runtime.ShowMeshes();

                var result = candidate;
                candidate = null;
                return result;
            }
            finally
            {
                if (candidate != null)
                {
                    Destroy(candidate.gameObject);
                }
            }
        }

        private static void ValidateManifest(ReviewManifest manifest)
        {
            if (manifest == null ||
                manifest.format !=
                    "bodyrig-photoreal-p3-quest2-review-runtime-manifest" ||
                manifest.version != 1)
            {
                throw new InvalidDataException(
                    "Unsupported P3 Quest review manifest format/version");
            }
            if (manifest.target_device_family != "meta-quest" ||
                manifest.target_device_model != "quest-2" ||
                manifest.student_representation != "skinned-mesh-pbr")
            {
                throw new InvalidDataException(
                    "P3 Quest review manifest target/student contract mismatch");
            }
            if (manifest.student_components == null ||
                manifest.student_components.Length != 2 ||
                manifest.student_components[0] != "specialized-eye-component" ||
                manifest.student_components[1] != "teacher-derived-hair-component")
            {
                throw new InvalidDataException(
                    "P3 Quest review manifest component universe mismatch");
            }
            if (!manifest.physical_review_only ||
                !manifest.comparison_only ||
                manifest.physical_device_evidence_present ||
                manifest.runtime_acceptance_authority ||
                manifest.photoreal_acceptance_authority ||
                manifest.production_activation)
            {
                throw new InvalidDataException(
                    "P3 Quest review manifest crossed review-only authority");
            }
        }

        private static string ResolveDirectChild(string root, string name)
        {
            var path = Path.GetFullPath(Path.Combine(root, name));
            if (!string.Equals(
                    Path.GetDirectoryName(path),
                    root,
                    StringComparison.OrdinalIgnoreCase))
            {
                throw new InvalidDataException(
                    "P3 Quest review payload escaped review workspace");
            }
            if (!File.Exists(path))
            {
                throw new FileNotFoundException(
                    "P3 Quest review payload is missing",
                    path);
            }
            return path;
        }

        private static void ValidateHumanoid(Animator animator)
        {
            if (animator == null ||
                animator.avatar == null ||
                !animator.avatar.isValid ||
                !animator.avatar.isHuman)
            {
                throw new InvalidDataException(
                    "P3 Quest review VRM does not expose a valid Unity Humanoid");
            }
            foreach (var bone in RequiredBones)
            {
                if (animator.GetBoneTransform(bone) == null)
                {
                    throw new InvalidDataException(
                        $"P3 Quest review VRM is missing required Humanoid bone: {bone}");
                }
            }
        }

        private static void RequireSha256(
            string path,
            string expectedSha256,
            string label)
        {
            var actual = Sha256File(path);
            if (!string.Equals(
                    actual,
                    expectedSha256,
                    StringComparison.Ordinal))
            {
                throw new InvalidDataException(
                    $"P3 Quest review {label} SHA-256 mismatch");
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
                {
                    builder.Append(value.ToString("x2"));
                }
                return builder.ToString();
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

            ActiveManifestPath = null;
            ActiveManifestSha256 = null;
            ActiveBodyRigRevision = null;
            ActivePerformerId = null;
            ActiveRuntimeReviewPlanSha256 = null;
            ActiveAvatarSha256 = null;
            ActiveBasecolorSha256 = null;
            ActiveProvenanceSha256 = null;
        }
    }
}
