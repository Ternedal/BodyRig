using System;
using System.Collections.Generic;
using System.IO;
using System.Security.Cryptography;
using System.Text;
using UnityEngine;

namespace BodyRig.ReferenceRenderer
{
    public sealed class BodyRigFidelitySnapshotCapture : MonoBehaviour
    {
        private const string Format = "bodyrig-fidelity-render-set";
        private const int Version = 1;
        private const string HandsFeetNailsFormat = "bodyrig-hands-feet-nails-render-set";
        private const string HandsFeetNailsSemantics = "human-review-diagnostic-not-physical-pass";
        private const string WardrobeFormat = "bodyrig-wardrobe-render-set";
        private const string WardrobeSemantics = "human-review-diagnostic-not-physical-pass";
        private const string FaceSecondaryNodeName = "BodyRigFaceSecondaryReview";
        private const string JawNodeName = "smplx_jaw";
        private const float FaceSecondaryJawOpenDegrees = 18f;

        [Serializable]
        private sealed class SnapshotEntry
        {
            public string view;
            public string file;
            public string sha256;
            public int width;
            public int height;
        }

        [Serializable]
        private sealed class SnapshotManifest
        {
            public string format = Format;
            public int version = Version;
            public string body_id;
            public string package_sha256;
            public string semantics = "visual-fidelity-not-identity-verification";
            public SnapshotEntry[] snapshots;
        }

        [Serializable]
        private sealed class HandsFeetNailsManifest
        {
            public string format = HandsFeetNailsFormat;
            public int version = Version;
            public string body_id;
            public string package_sha256;
            public string semantics = HandsFeetNailsSemantics;
            public SnapshotEntry[] snapshots;
        }

        [Serializable]
        private sealed class WardrobeManifest
        {
            public string format = WardrobeFormat;
            public int version = Version;
            public string body_id;
            public string package_sha256;
            public string semantics = WardrobeSemantics;
            public SnapshotEntry[] snapshots;
        }

        private struct CameraPose
        {
            public string Name;
            public Vector3 Position;
            public Vector3 Target;
            public float FieldOfView;

            public CameraPose(string name, Vector3 position, Vector3 target, float fieldOfView)
            {
                Name = name;
                Position = position;
                Target = target;
                FieldOfView = fieldOfView;
            }
        }

        public string Capture(BodyRigAvatarLoader loader, string outputDirectory)
        {
            if (loader == null || loader.Active == null)
                throw new InvalidOperationException("BodyRig fidelity snapshots require a loaded avatar.");
            if (Camera.main == null)
                throw new InvalidOperationException("BodyRig fidelity snapshots require the canonical camera.");
            if (string.IsNullOrWhiteSpace(outputDirectory))
                throw new ArgumentException("Fidelity snapshot output directory is required.", nameof(outputDirectory));

            var root = Path.GetFullPath(outputDirectory);
            if (Directory.Exists(root) || File.Exists(root))
                throw new IOException("Fidelity snapshot output already exists; refusing cross-attempt reuse: " + root);
            Directory.CreateDirectory(root);

            try
            {
                var renderers = loader.Active.GetComponentsInChildren<Renderer>(true);
                if (renderers == null || renderers.Length == 0)
                    throw new InvalidOperationException("Loaded avatar has no renderable bounds.");
                var bounds = renderers[0].bounds;
                for (var index = 1; index < renderers.Length; index++) bounds.Encapsulate(renderers[index].bounds);

                var height = Mathf.Max(bounds.size.y, 1f);
                var center = bounds.center;
                var bodyTarget = center + Vector3.up * height * 0.03f;
                var radius = height * 1.65f;

                var animator = loader.Active.GetComponentInChildren<Animator>(true);
                var head = animator != null ? animator.GetBoneTransform(HumanBodyBones.Head) : null;
                var leftEye = animator != null ? animator.GetBoneTransform(HumanBodyBones.LeftEye) : null;
                var rightEye = animator != null ? animator.GetBoneTransform(HumanBodyBones.RightEye) : null;
                var leftHand = animator != null ? animator.GetBoneTransform(HumanBodyBones.LeftHand) : null;
                var rightHand = animator != null ? animator.GetBoneTransform(HumanBodyBones.RightHand) : null;
                var leftFoot = animator != null ? animator.GetBoneTransform(HumanBodyBones.LeftFoot) : null;
                var rightFoot = animator != null ? animator.GetBoneTransform(HumanBodyBones.RightFoot) : null;
                var leftToes = animator != null ? animator.GetBoneTransform(HumanBodyBones.LeftToes) : null;
                var rightToes = animator != null ? animator.GetBoneTransform(HumanBodyBones.RightToes) : null;
                var faceTarget = head != null ? head.position : center + Vector3.up * height * 0.38f;
                var faceDistance = Mathf.Max(height * 0.24f, 0.30f);
                var faceZoomDistance = Mathf.Max(height * 0.19f, 0.24f);

                // Keep these four manifest-backed views stable. Evaluator version 1
                // binds this exact sequence and older evidence must remain readable.
                var canonicalPoses = new[]
                {
                    new CameraPose("front-full", bodyTarget + new Vector3(0f, 0f, radius), bodyTarget, 35f),
                    new CameraPose("three-quarter-full", bodyTarget + new Vector3(radius * 0.70f, 0f, radius * 0.70f), bodyTarget, 35f),
                    new CameraPose("side-full", bodyTarget + new Vector3(radius, 0f, 0f), bodyTarget, 35f),
                    new CameraPose("face-front", faceTarget + new Vector3(0f, 0f, faceDistance), faceTarget, 24f),
                };

                // Human-review diagnostics are intentionally outside the v1
                // fidelity manifest. They add inspection detail without changing
                // machine-evaluator authority or acceptance semantics.
                var diagnosticPoses = new List<CameraPose>
                {
                    new CameraPose("face-zoom", faceTarget + new Vector3(0f, 0f, faceZoomDistance), faceTarget, 20f),
                    new CameraPose(
                        "face-three-quarter",
                        faceTarget + new Vector3(faceDistance * 0.62f, height * 0.01f, faceDistance * 0.78f),
                        faceTarget,
                        24f),
                };
                if (leftEye != null && rightEye != null)
                {
                    var eyeTarget = (leftEye.position + rightEye.position) * 0.5f;
                    var eyeSpan = Mathf.Max(Vector3.Distance(leftEye.position, rightEye.position), height * 0.025f);
                    var eyeCloseupDistance = Mathf.Max(eyeSpan * 4.6f, height * 0.12f, 0.18f);
                    diagnosticPoses.Add(new CameraPose(
                        "eyes-closeup",
                        eyeTarget + new Vector3(0f, 0f, eyeCloseupDistance),
                        eyeTarget,
                        20f));
                }

                // Full-digital-twin hand/foot diagnostics remain in their own
                // human-review manifest and do not alter machine-evaluator authority.
                var detailPoses = new List<CameraPose>();
                if (leftHand != null && rightHand != null && leftFoot != null && rightFoot != null)
                {
                    var handDistance = Mathf.Max(height * 0.145f, 0.22f);
                    var footDistance = Mathf.Max(height * 0.17f, 0.24f);
                    var leftFootTarget = leftToes != null ? Vector3.Lerp(leftFoot.position, leftToes.position, 0.58f) : leftFoot.position;
                    var rightFootTarget = rightToes != null ? Vector3.Lerp(rightFoot.position, rightToes.position, 0.58f) : rightFoot.position;
                    detailPoses.Add(new CameraPose("left_hand", leftHand.position + new Vector3(0f, height * 0.012f, handDistance), leftHand.position, 18f));
                    detailPoses.Add(new CameraPose("right_hand", rightHand.position + new Vector3(0f, height * 0.012f, handDistance), rightHand.position, 18f));
                    detailPoses.Add(new CameraPose("left_foot", leftFootTarget + new Vector3(0f, height * 0.025f, footDistance), leftFootTarget, 18f));
                    detailPoses.Add(new CameraPose("right_foot", rightFootTarget + new Vector3(0f, height * 0.025f, footDistance), rightFootTarget, 18f));
                }

                // Wardrobe/presentation views expose the complete source outer
                // surface from all four sides. IDs intentionally match the source
                // capture contract so source-vs-render comparison is unambiguous.
                var wardrobePoses = new[]
                {
                    new CameraPose("front", bodyTarget + new Vector3(0f, 0f, radius), bodyTarget, 34f),
                    new CameraPose("left_side", bodyTarget + new Vector3(-radius, 0f, 0f), bodyTarget, 34f),
                    new CameraPose("right_side", bodyTarget + new Vector3(radius, 0f, 0f), bodyTarget, 34f),
                    new CameraPose("back", bodyTarget + new Vector3(0f, 0f, -radius), bodyTarget, 34f),
                };

                var camera = Camera.main;
                var originalPosition = camera.transform.position;
                var originalRotation = camera.transform.rotation;
                var originalFov = camera.fieldOfView;
                var entries = new List<SnapshotEntry>();
                var detailEntries = new List<SnapshotEntry>();
                var wardrobeEntries = new List<SnapshotEntry>();
                try
                {
                    foreach (var pose in canonicalPoses)
                    {
                        var bytes = CapturePose(camera, pose);
                        var filename = WriteSnapshot(root, pose.Name, bytes);
                        entries.Add(new SnapshotEntry { view = pose.Name, file = filename, sha256 = Sha256(bytes), width = 1024, height = 1024 });
                    }

                    foreach (var pose in diagnosticPoses)
                    {
                        var bytes = CapturePose(camera, pose);
                        WriteSnapshot(root, pose.Name, bytes);
                    }

                    foreach (var pose in detailPoses)
                    {
                        var bytes = CapturePose(camera, pose);
                        var filename = WriteSnapshot(root, pose.Name, bytes);
                        detailEntries.Add(new SnapshotEntry { view = pose.Name, file = filename, sha256 = Sha256(bytes), width = 1024, height = 1024 });
                    }

                    foreach (var pose in wardrobePoses)
                    {
                        var bytes = CapturePose(camera, pose);
                        var filename = WriteSnapshot(root, pose.Name, bytes);
                        wardrobeEntries.Add(new SnapshotEntry { view = pose.Name, file = filename, sha256 = Sha256(bytes), width = 1024, height = 1024 });
                    }

                    CaptureFaceSecondaryMouthOpen(loader.Active, camera, root, faceTarget, height);
                }
                finally
                {
                    camera.transform.position = originalPosition;
                    camera.transform.rotation = originalRotation;
                    camera.fieldOfView = originalFov;
                }

                var manifest = new SnapshotManifest
                {
                    body_id = loader.ActiveBodyId,
                    package_sha256 = loader.ActivePackageSha256,
                    snapshots = entries.ToArray(),
                };
                var manifestPath = Path.Combine(root, "fidelity-render-set.json");
                File.WriteAllText(manifestPath, JsonUtility.ToJson(manifest, true) + "\n", new UTF8Encoding(false));

                if (detailEntries.Count == 4)
                {
                    var detailManifest = new HandsFeetNailsManifest
                    {
                        body_id = loader.ActiveBodyId,
                        package_sha256 = loader.ActivePackageSha256,
                        snapshots = detailEntries.ToArray(),
                    };
                    File.WriteAllText(Path.Combine(root, "hands-feet-nails-render-set.json"), JsonUtility.ToJson(detailManifest, true) + "\n", new UTF8Encoding(false));
                }

                if (wardrobeEntries.Count == 4)
                {
                    var wardrobeManifest = new WardrobeManifest
                    {
                        body_id = loader.ActiveBodyId,
                        package_sha256 = loader.ActivePackageSha256,
                        snapshots = wardrobeEntries.ToArray(),
                    };
                    File.WriteAllText(Path.Combine(root, "wardrobe-render-set.json"), JsonUtility.ToJson(wardrobeManifest, true) + "\n", new UTF8Encoding(false));
                }

                return manifestPath;
            }
            catch
            {
                try { Directory.Delete(root, true); } catch { }
                throw;
            }
        }

        private static void CaptureFaceSecondaryMouthOpen(GameObject active, Camera camera, string root, Vector3 fallbackFaceTarget, float height)
        {
            if (FindNamedTransform(active.transform, FaceSecondaryNodeName) == null) return;
            var jaw = FindNamedTransform(active.transform, JawNodeName);
            if (jaw == null) throw new InvalidOperationException("Face-secondary review runtime requires canonical smplx_jaw transform.");
            var originalJawRotation = jaw.localRotation;
            try
            {
                jaw.localRotation = originalJawRotation * Quaternion.Euler(FaceSecondaryJawOpenDegrees, 0f, 0f);
                var target = Vector3.Lerp(fallbackFaceTarget, jaw.position, 0.70f);
                var distance = Mathf.Max(height * 0.145f, 0.20f);
                var pose = new CameraPose("mouth-open", target + new Vector3(0f, -height * 0.005f, distance), target, 16f);
                WriteSnapshot(root, pose.Name, CapturePose(camera, pose));
            }
            finally
            {
                jaw.localRotation = originalJawRotation;
            }
        }

        private static Transform FindNamedTransform(Transform root, string name)
        {
            if (root == null) return null;
            var all = root.GetComponentsInChildren<Transform>(true);
            Transform match = null;
            foreach (var item in all)
            {
                if (!string.Equals(item.name, name, StringComparison.Ordinal)) continue;
                if (match != null) throw new InvalidOperationException("Loaded avatar contains ambiguous transform: " + name);
                match = item;
            }
            return match;
        }

        private static byte[] CapturePose(Camera camera, CameraPose pose)
        {
            camera.transform.position = pose.Position;
            camera.transform.LookAt(pose.Target);
            camera.fieldOfView = pose.FieldOfView;
            return RenderPng(camera, 1024, 1024);
        }

        private static string WriteSnapshot(string root, string name, byte[] bytes)
        {
            var filename = name + ".png";
            var path = Path.Combine(root, filename);
            using (var stream = new FileStream(path, FileMode.CreateNew, FileAccess.Write, FileShare.None))
            {
                stream.Write(bytes, 0, bytes.Length);
                stream.Flush(true);
            }
            return filename;
        }

        private static byte[] RenderPng(Camera camera, int width, int height)
        {
            var target = new RenderTexture(width, height, 24, RenderTextureFormat.ARGB32);
            var previousTarget = camera.targetTexture;
            var previousActive = RenderTexture.active;
            Texture2D texture = null;
            try
            {
                camera.targetTexture = target;
                RenderTexture.active = target;
                camera.Render();
                texture = new Texture2D(width, height, TextureFormat.RGB24, false);
                texture.ReadPixels(new Rect(0, 0, width, height), 0, 0, false);
                texture.Apply(false, false);
                return texture.EncodeToPNG();
            }
            finally
            {
                camera.targetTexture = previousTarget;
                RenderTexture.active = previousActive;
                if (texture != null) Destroy(texture);
                target.Release();
                Destroy(target);
            }
        }

        private static string Sha256(byte[] value)
        {
            using (var sha = SHA256.Create())
            {
                var hash = sha.ComputeHash(value);
                var builder = new StringBuilder(hash.Length * 2);
                foreach (var item in hash) builder.Append(item.ToString("x2"));
                return builder.ToString();
            }
        }
    }
}
