using System;
using System.IO;
using System.Threading.Tasks;
using UnityEngine;

namespace BodyRig.ReferenceRenderer
{
    /// <summary>
    /// Zero-scene-setup bootstrap for physical renderer acceptance.
    /// A built player can be launched directly against Gate A runtime assets.
    /// Optional comparison probes remain independently non-activating.
    /// </summary>
    [DefaultExecutionOrder(-1000)]
    public sealed class BodyRigPhysicalProbeBootstrap : MonoBehaviour
    {
        private const string RuntimeManifestArg = "--bodyrig-runtime-manifest";
        private const string ProbeOutputArg = "--bodyrig-probe-output";
        private const string DeformationOutputArg = "--bodyrig-deformation-output";
        private const string HairDeformationOutputArg = "--bodyrig-hair-deformation-output";
        private const string RendererNameArg = "--bodyrig-renderer-name";
        private const string RendererVersionArg = "--bodyrig-renderer-version";
        private const string FidelitySnapshotDirArg = "--bodyrig-fidelity-snapshot-dir";
        private const string QuitAfterProbeArg = "--bodyrig-quit-after-probe";

        private string _status = "BodyRig physical probe starting...";
        private bool _failed;

        [RuntimeInitializeOnLoadMethod(RuntimeInitializeLoadType.BeforeSceneLoad)]
        private static void Install()
        {
            if (FindObjectOfType<BodyRigPhysicalProbeBootstrap>() != null) return;
            var host = new GameObject("BodyRig Physical Probe");
            DontDestroyOnLoad(host);
            host.AddComponent<BodyRigPhysicalProbeBootstrap>();
        }

        private async void Start()
        {
            try
            {
                await RunAsync();
            }
            catch (Exception exception)
            {
                _failed = true;
                _status = "BodyRig physical probe: FAIL\n" + exception.Message;
                Debug.LogException(exception, this);
                if (HasFlag("-batchmode") || HasFlag(QuitAfterProbeArg)) Application.Quit(2);
            }
        }

        private async Task RunAsync()
        {
            CreateVisualRig();

            var defaultRoot = Path.Combine(Application.persistentDataPath, "BodyRig");
            var manifestPath = GetArgument(RuntimeManifestArg) ?? Path.Combine(defaultRoot, "runtime", "runtime-manifest.json");
            var probePath = GetArgument(ProbeOutputArg) ?? Path.Combine(defaultRoot, "bodyrig-renderer-probe.json");
            var deformationPath = GetArgument(DeformationOutputArg) ?? Path.Combine(defaultRoot, "bodyrig-deformation-probe.json");
            var hairDeformationPath = GetArgument(HairDeformationOutputArg);
            var fidelitySnapshotDir = GetArgument(FidelitySnapshotDirArg);
            var rendererName = GetArgument(RendererNameArg) ?? "BodyRig Reference Renderer";
            var rendererVersion = GetArgument(RendererVersionArg) ?? "reference-v1/univrm-0.131.2";

            _status = "Loading accepted BodyRig runtime...\n" + manifestPath;
            var loader = gameObject.AddComponent<BodyRigAvatarLoader>();
            var probe = gameObject.AddComponent<BodyRigRendererProbe>();
            probe.Configure(loader, rendererName, rendererVersion);

            await probe.RunProbeAsync(manifestPath, probePath);
            FrameActiveAvatar(loader);

            string fidelityManifest = null;
            if (!string.IsNullOrWhiteSpace(fidelitySnapshotDir))
            {
                _status = "Renderer machine probe: PASS\nCapturing canonical fidelity views...";
                var fidelity = gameObject.AddComponent<BodyRigFidelitySnapshotCapture>();
                fidelityManifest = fidelity.Capture(loader, fidelitySnapshotDir);
            }

            var sweep = gameObject.AddComponent<BodyRigDeformationSweep>();
            sweep.Configure(loader);
            _status = "Renderer machine probe: PASS\nStarting fixed deformation sweep...";
            await sweep.RunSweepAsync(deformationPath, UpdateSweepStatus);

            string hairDeformationReport = null;
            if (!string.IsNullOrWhiteSpace(hairDeformationPath))
            {
                _status = "Body deformation sweep: PASS\nTesting source-hair skinning against the real Head bone...";
                var hairProbe = gameObject.AddComponent<BodyRigHairDeformationProbe>();
                hairProbe.Configure(loader);
                hairDeformationReport = await hairProbe.RunProbeAsync(hairDeformationPath, UpdateHairStatus);
            }

            _status = "BodyRig physical evidence: PASS\n" +
                      probe.LastProbePath + "\n" + sweep.LastReportPath +
                      (string.IsNullOrEmpty(hairDeformationReport) ? "" : "\nHair deformation: " + hairDeformationReport) +
                      (string.IsNullOrEmpty(fidelityManifest) ? "" : "\nFidelity views: " + fidelityManifest) +
                      "\nHuman visual deformation acceptance is still required.";

            if (HasFlag(QuitAfterProbeArg))
            {
                Application.Quit(0);
                return;
            }

            sweep.BeginReviewLoop(UpdateReviewStatus);
        }

        private void UpdateSweepStatus(string message)
        {
            _status = "Renderer machine probe: PASS\n" + message + "\nWatch shoulders, elbows, wrists, hips and knees.";
        }

        private void UpdateHairStatus(string message)
        {
            _status = "Body deformation sweep: PASS\n" + message +
                      "\nMachine evidence only; inspect hair attachment, clipping and silhouette visually.";
        }

        private void UpdateReviewStatus(string message)
        {
            _status = "BodyRig physical evidence: PASS\n" + message +
                      "\nInspect cross-limb leakage, collapse, clipping, hair attachment and unnatural folds.\nClose player when visual review is complete.";
        }

        private static Light CreateDirectionalLight(string name, float intensity, Vector3 rotation)
        {
            var lightObject = new GameObject(name);
            var light = lightObject.AddComponent<Light>();
            light.type = LightType.Directional;
            light.intensity = intensity;
            lightObject.transform.rotation = Quaternion.Euler(rotation);
            return light;
        }

        private static void CreateVisualRig()
        {
            if (Camera.main == null)
            {
                var cameraObject = new GameObject("BodyRig Acceptance Camera");
                cameraObject.tag = "MainCamera";
                var camera = cameraObject.AddComponent<Camera>();
                camera.clearFlags = CameraClearFlags.SolidColor;
                camera.backgroundColor = new Color(0.08f, 0.08f, 0.09f, 1f);
                camera.fieldOfView = 35f;
                camera.nearClipPlane = 0.01f;
                camera.farClipPlane = 100f;
            }

            if (FindObjectOfType<Light>() == null)
            {
                CreateDirectionalLight(
                    "BodyRig Fidelity Key Light",
                    1.15f,
                    new Vector3(36f, -32f, 0f));
                CreateDirectionalLight(
                    "BodyRig Fidelity Fill Light",
                    0.28f,
                    new Vector3(18f, 145f, 0f));
                CreateDirectionalLight(
                    "BodyRig Fidelity Rim Light",
                    0.38f,
                    new Vector3(52f, 205f, 0f));
            }

            RenderSettings.ambientMode = UnityEngine.Rendering.AmbientMode.Flat;
            RenderSettings.ambientLight = new Color(0.16f, 0.16f, 0.16f, 1f);
        }

        private static void FrameActiveAvatar(BodyRigAvatarLoader loader)
        {
            if (loader.Active == null || Camera.main == null) return;
            var renderers = loader.Active.GetComponentsInChildren<Renderer>(true);
            if (renderers == null || renderers.Length == 0) return;

            var bounds = renderers[0].bounds;
            for (var index = 1; index < renderers.Length; index++) bounds.Encapsulate(renderers[index].bounds);

            var height = Mathf.Max(bounds.size.y, 1f);
            var target = bounds.center + Vector3.up * height * 0.03f;
            var camera = Camera.main;
            camera.transform.position = target + new Vector3(0f, 0f, height * 1.65f);
            camera.transform.LookAt(target);
        }

        private void OnGUI()
        {
            var width = Mathf.Min(Screen.width - 24f, 820f);
            var style = new GUIStyle(GUI.skin.box)
            {
                alignment = TextAnchor.UpperLeft,
                fontSize = Mathf.Max(14, Screen.height / 50),
                wordWrap = true,
                normal = { textColor = _failed ? new Color(1f, 0.55f, 0.55f) : Color.white },
            };
            GUI.Box(new Rect(12f, 12f, width, 150f), _status, style);
        }

        private static string GetArgument(string name)
        {
            var args = Environment.GetCommandLineArgs();
            for (var index = 0; index < args.Length - 1; index++)
                if (string.Equals(args[index], name, StringComparison.OrdinalIgnoreCase)) return args[index + 1];
            return null;
        }

        private static bool HasFlag(string name)
        {
            foreach (var arg in Environment.GetCommandLineArgs())
                if (string.Equals(arg, name, StringComparison.OrdinalIgnoreCase)) return true;
            return false;
        }
    }
}
