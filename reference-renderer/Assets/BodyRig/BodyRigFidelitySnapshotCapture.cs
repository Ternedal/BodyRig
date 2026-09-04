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
                var diagnosticPoses = new[]
                {
                    new CameraPose("face-zoom", faceTarget + new Vector3(0f, 0f, faceZoomDistance), faceTarget, 20f),
                    new CameraPose(
                        "face-three-quarter",
                        faceTarget + new Vector3(faceDistance * 0.62f, height * 0.01f, faceDistance * 0.78f),
                        faceTarget,
                        24f),
                };

                var camera = Camera.main;
                var originalPosition = camera.transform.position;
                var originalRotation = camera.transform.rotation;
                var originalFov = camera.fieldOfView;
                var entries = new List<SnapshotEntry>();
                try
                {
                    foreach (var pose in canonicalPoses)
                    {
                        var bytes = CapturePose(camera, pose);
                        var filename = WriteSnapshot(root, pose.Name, bytes);
                        entries.Add(new SnapshotEntry
                        {
                            view = pose.Name,
                            file = filename,
                            sha256 = Sha256(bytes),
                            width = 1024,
                            height = 1024,
                        });
                    }

                    foreach (var pose in diagnosticPoses)
                    {
                        var bytes = CapturePose(camera, pose);
                        WriteSnapshot(root, pose.Name, bytes);
                    }
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
                var json = JsonUtility.ToJson(manifest, true) + "\n";
                File.WriteAllText(manifestPath, json, new UTF8Encoding(false));
                return manifestPath;
            }
            catch
            {
                try { Directory.Delete(root, true); } catch { }
                throw;
            }
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
