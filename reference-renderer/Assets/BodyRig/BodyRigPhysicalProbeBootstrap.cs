using System;
using System.IO;
using System.Threading.Tasks;
using UnityEngine;

namespace BodyRig.ReferenceRenderer
{
    /// <summary>
    /// Zero-scene-setup bootstrap for physical renderer acceptance.
    /// A built player can be launched directly against Gate A runtime assets.
    /// </summary>
    [DefaultExecutionOrder(-1000)]
    public sealed class BodyRigPhysicalProbeBootstrap : MonoBehaviour
    {
        private const string RuntimeManifestArg = "--bodyrig-runtime-manifest";
        private const string ProbeOutputArg = "--bodyrig-probe-output";
        private const string RendererNameArg = "--bodyrig-renderer-name";
        private const string RendererVersionArg = "--bodyrig-renderer-version";
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
            var rendererName = GetArgument(RendererNameArg) ?? "BodyRig Reference Renderer";
            var rendererVersion = GetArgument(RendererVersionArg) ?? "reference-v1/univrm-0.131.2";

            _status = "Loading accepted BodyRig runtime...\n" + manifestPath;
            var loader = gameObject.AddComponent<BodyRigAvatarLoader>();
            var probe = gameObject.AddComponent<BodyRigRendererProbe>();
            probe.Configure(loader, rendererName, rendererVersion);

            await probe.RunProbeAsync(manifestPath, probePath);
            FrameActiveAvatar(loader);
            _status = "BodyRig physical probe: PASS\n" + probe.LastProbePath + "\nVisual quality still requires human acceptance.";

            if (HasFlag(QuitAfterProbeArg)) Application.Quit(0);
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
                var lightObject = new GameObject("BodyRig Acceptance Light");
                var light = lightObject.AddComponent<Light>();
                light.type = LightType.Directional;
                light.intensity = 1.25f;
                lightObject.transform.rotation = Quaternion.Euler(45f, -25f, 0f);
            }

            RenderSettings.ambientLight = new Color(0.45f, 0.45f, 0.45f, 1f);
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
            var width = Mathf.Min(Screen.width - 24f, 760f);
            var style = new GUIStyle(GUI.skin.box)
            {
                alignment = TextAnchor.UpperLeft,
                fontSize = Mathf.Max(14, Screen.height / 50),
                wordWrap = true,
                normal = { textColor = _failed ? new Color(1f, 0.55f, 0.55f) : Color.white },
            };
            GUI.Box(new Rect(12f, 12f, width, 110f), _status, style);
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
