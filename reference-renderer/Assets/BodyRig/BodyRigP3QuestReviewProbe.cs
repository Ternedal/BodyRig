using System;
using System.IO;
using System.Text;
using System.Threading.Tasks;
using UnityEngine;

namespace BodyRig.ReferenceRenderer
{
    /// <summary>
    /// Machine probe for the review-only P3 Quest 2 runtime.
    ///
    /// This deliberately proves only: exact bytes, VRM 1.0/Humanoid load,
    /// physical Quest execution and visibility of the modular eye/hair nodes.
    /// The current reference project is not an XR runtime, so this probe must
    /// report XR/stereo/frame-pacing evidence as false.
    /// </summary>
    public sealed class BodyRigP3QuestReviewProbe : MonoBehaviour
    {
        private const string EyeNodeName = "BodyRigP3QuestEyeComponent";
        private const string HairNodeName = "BodyRigP3QuestTeacherHair";

        [Serializable]
        private sealed class ProbeReport
        {
            public string format =
                "bodyrig-photoreal-p3-quest2-review-render-probe";
            public int version = 1;
            public string observed_at;
            public string bodyrig_revision;
            public string unity_platform;
            public string unity_version;
            public string build_guid;
            public string device_model;
            public string graphics_device;
            public string performer_id;
            public string p3_device_runtime_review_plan_sha256;
            public string review_manifest_sha256;
            public string avatar_sha256;
            public string basecolor_sha256;
            public string provenance_sha256;
            public bool vrm10_loaded;
            public bool humanoid_valid;
            public bool required_bones_valid;
            public bool specialized_eye_component_instantiated;
            public bool specialized_eye_component_visible;
            public bool teacher_hair_component_instantiated;
            public bool teacher_hair_component_visible;
            public bool physical_device_observed;
            public bool xr_runtime_present;
            public bool stereo_rendering_observed;
            public bool vr_safe_frame_pacing_observed;
            public double display_refresh_hz;
            public bool physical_review_only;
            public bool comparison_only;
            public bool physical_runtime_review_complete;
            public bool runtime_acceptance_authority;
            public bool photoreal_acceptance_authority;
            public bool production_activation;
            public string semantics =
                "physical-quest-renderability-and-component-visibility-not-xr-or-photoreal-acceptance";
        }

        public string LastProbePath { get; private set; }

        public async Task<string> RunProbeAsync(
            BodyRigP3QuestReviewLoader loader,
            string manifestPath,
            string outputPath)
        {
            if (loader == null)
            {
                throw new ArgumentNullException(nameof(loader));
            }
            if (string.IsNullOrWhiteSpace(manifestPath))
            {
                throw new ArgumentException(
                    "P3 Quest review manifest path is required",
                    nameof(manifestPath));
            }
            if (string.IsNullOrWhiteSpace(outputPath))
            {
                throw new ArgumentException(
                    "P3 Quest review probe output path is required",
                    nameof(outputPath));
            }

            RequirePhysicalQuest();

            await loader.LoadReviewAsync(manifestPath);
            await Task.Yield();

            if (loader.Active == null)
            {
                throw new InvalidDataException(
                    "P3 Quest review probe has no active VRM after load");
            }
            if (loader.Animator == null ||
                loader.Animator.avatar == null ||
                !loader.Animator.avatar.isValid ||
                !loader.Animator.avatar.isHuman)
            {
                throw new InvalidDataException(
                    "P3 Quest review probe does not see a valid Humanoid");
            }

            var revision = BodyRigBuildProvenance.RequireRevision();
            if (!string.Equals(
                    revision,
                    loader.ActiveBodyRigRevision,
                    StringComparison.Ordinal))
            {
                throw new InvalidDataException(
                    "P3 Quest review player revision differs from review manifest");
            }

            var eye = InspectComponent(loader.Active.gameObject, EyeNodeName);
            var hair = InspectComponent(loader.Active.gameObject, HairNodeName);

            var buildGuid = Application.buildGUID;
            if (string.IsNullOrWhiteSpace(buildGuid))
            {
                throw new InvalidDataException(
                    "P3 Quest review probe requires a non-empty build GUID");
            }

            var refresh = Screen.currentResolution.refreshRateRatio.value;
            if (double.IsNaN(refresh) || double.IsInfinity(refresh) || refresh < 0.0)
            {
                refresh = 0.0;
            }

            var report = new ProbeReport
            {
                observed_at = DateTime.UtcNow.ToString("o"),
                bodyrig_revision = revision,
                unity_platform = Application.platform.ToString(),
                unity_version = Application.unityVersion,
                build_guid = buildGuid,
                device_model = SystemInfo.deviceModel.Trim(),
                graphics_device = string.IsNullOrWhiteSpace(
                    SystemInfo.graphicsDeviceName)
                    ? "unknown"
                    : SystemInfo.graphicsDeviceName.Trim(),
                performer_id = loader.ActivePerformerId,
                p3_device_runtime_review_plan_sha256 =
                    loader.ActiveRuntimeReviewPlanSha256,
                review_manifest_sha256 = loader.ActiveManifestSha256,
                avatar_sha256 = loader.ActiveAvatarSha256,
                basecolor_sha256 = loader.ActiveBasecolorSha256,
                provenance_sha256 = loader.ActiveProvenanceSha256,
                vrm10_loaded = true,
                humanoid_valid = true,
                required_bones_valid = true,
                specialized_eye_component_instantiated = eye.instantiated,
                specialized_eye_component_visible = eye.visible,
                teacher_hair_component_instantiated = hair.instantiated,
                teacher_hair_component_visible = hair.visible,
                physical_device_observed = true,

                // Fail closed. The current reference-renderer dependency set has
                // no XR/OpenXR/Oculus package. A flat Android player on Quest is
                // physical renderability evidence, not stereo/XR acceptance.
                xr_runtime_present = false,
                stereo_rendering_observed = false,
                vr_safe_frame_pacing_observed = false,

                display_refresh_hz = refresh,
                physical_review_only = true,
                comparison_only = true,
                physical_runtime_review_complete = false,
                runtime_acceptance_authority = false,
                photoreal_acceptance_authority = false,
                production_activation = false,
            };

            var fullOutput = Path.GetFullPath(outputPath);
            if (File.Exists(fullOutput))
            {
                throw new IOException(
                    $"P3 Quest review probe already exists: {fullOutput}");
            }
            var parent = Path.GetDirectoryName(fullOutput);
            if (string.IsNullOrEmpty(parent))
            {
                throw new InvalidDataException(
                    "P3 Quest review probe output has no parent directory");
            }
            Directory.CreateDirectory(parent);
            WriteCreateOnlyJson(fullOutput, report);
            LastProbePath = fullOutput;

            Debug.Log(
                "BodyRig P3 Quest review probe: RENDERABLE / XR NOT PROVEN | " +
                $"eye={eye.visible} | hair={hair.visible} | {fullOutput}",
                this);
            return fullOutput;
        }

        private readonly struct ComponentState
        {
            public readonly bool instantiated;
            public readonly bool visible;

            public ComponentState(bool instantiatedValue, bool visibleValue)
            {
                instantiated = instantiatedValue;
                visible = visibleValue;
            }
        }

        private static ComponentState InspectComponent(
            GameObject root,
            string expectedName)
        {
            Transform matched = null;
            foreach (var transform in root.GetComponentsInChildren<Transform>(true))
            {
                if (!string.Equals(
                        transform.name,
                        expectedName,
                        StringComparison.Ordinal))
                {
                    continue;
                }
                if (matched != null)
                {
                    throw new InvalidDataException(
                        $"P3 Quest review found repeated component node: {expectedName}");
                }
                matched = transform;
            }
            if (matched == null)
            {
                throw new InvalidDataException(
                    $"P3 Quest review did not instantiate component: {expectedName}");
            }
            if (!matched.gameObject.activeInHierarchy)
            {
                throw new InvalidDataException(
                    $"P3 Quest review component is inactive: {expectedName}");
            }

            var visible = false;
            foreach (var renderer in matched.GetComponentsInChildren<Renderer>(true))
            {
                if (renderer == null ||
                    !renderer.enabled ||
                    !renderer.gameObject.activeInHierarchy)
                {
                    continue;
                }
                if (renderer.bounds.size.sqrMagnitude <= 0.000001f)
                {
                    continue;
                }
                visible = true;
                break;
            }
            if (!visible)
            {
                throw new InvalidDataException(
                    $"P3 Quest review component has no drawable renderer: {expectedName}");
            }
            return new ComponentState(true, true);
        }

        private static void RequirePhysicalQuest()
        {
            if (Application.platform != RuntimePlatform.Android)
            {
                throw new PlatformNotSupportedException(
                    "P3 Quest review probe requires a built Android player");
            }
            var model = SystemInfo.deviceModel;
            if (string.IsNullOrWhiteSpace(model) ||
                (model.IndexOf(
                     "Quest",
                     StringComparison.OrdinalIgnoreCase) < 0 &&
                 model.IndexOf(
                     "Oculus",
                     StringComparison.OrdinalIgnoreCase) < 0))
            {
                throw new PlatformNotSupportedException(
                    $"P3 Quest review probe requires Quest/Oculus hardware, got '{model}'");
            }
        }

        private static void WriteCreateOnlyJson(
            string path,
            object report)
        {
            var json = UnityEngine.JsonUtility.ToJson(report, true) + "\n";
            using (var stream = new FileStream(
                       path,
                       FileMode.CreateNew,
                       FileAccess.Write,
                       FileShare.None))
            using (var writer = new StreamWriter(
                       stream,
                       new UTF8Encoding(false)))
            {
                writer.Write(json);
            }
        }
    }
}
