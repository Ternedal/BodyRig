using System;
using System.IO;
using System.Threading;
using System.Threading.Tasks;
using UniGLTF;
using UniVRM10;
using UnityEngine;

namespace BodyRig.ReferenceRenderer
{
    /// <summary>
    /// Thin physical-acceptance loader for BodyRig avatar.vrm files.
    /// It intentionally contains no cloning/recovery logic.
    /// </summary>
    public sealed class BodyRigAvatarLoader : MonoBehaviour
    {
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

        public async Task LoadAsync(string path, CancellationToken cancellationToken = default)
        {
            if (string.IsNullOrWhiteSpace(path))
            {
                throw new ArgumentException("VRM path is required", nameof(path));
            }

            var fullPath = Path.GetFullPath(path);
            if (!File.Exists(fullPath))
            {
                throw new FileNotFoundException("BodyRig avatar.vrm was not found", fullPath);
            }

            // Keep the old known-good avatar until the replacement has imported
            // and passed Unity's own Humanoid mapping checks.
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
        }
    }
}
