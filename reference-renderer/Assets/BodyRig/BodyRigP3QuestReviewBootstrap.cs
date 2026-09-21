using System;
using System.IO;
using System.Threading.Tasks;
using UnityEngine;

namespace BodyRig.ReferenceRenderer
{
    /// <summary>
    /// Zero-scene-setup bootstrap for the isolated P3 Quest review application.
    /// The review APK has its own application id and never enters Gate-A
    /// production acceptance.
    /// </summary>
    [DefaultExecutionOrder(-1100)]
    public sealed class BodyRigP3QuestReviewBootstrap : MonoBehaviour
    {
        public const string ReviewApplicationId =
            "dk.ternedal.bodyrig.p3review";

        private string _status = "BodyRig P3 Quest review starting...";
        private bool _failed;

        [RuntimeInitializeOnLoadMethod(RuntimeInitializeLoadType.BeforeSceneLoad)]
        private static void Install()
        {
            if (!string.Equals(
                    Application.identifier,
                    ReviewApplicationId,
                    StringComparison.Ordinal))
            {
                return;
            }
            if (FindObjectOfType<BodyRigP3QuestReviewBootstrap>() != null)
            {
                return;
            }

            var host = new GameObject("BodyRig P3 Quest Review");
            DontDestroyOnLoad(host);
            host.AddComponent<BodyRigP3QuestReviewBootstrap>();
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
                _status = "BodyRig P3 Quest review: FAIL\n" + exception.Message;
                Debug.LogException(exception, this);
            }
        }

        private async Task RunAsync()
        {
            CreateVisualRig();

            var reviewRoot = Path.Combine(
                Application.persistentDataPath,
                "BodyRig",
                "p3-review");
            var manifestPath = Path.Combine(
                reviewRoot,
                "p3-quest2-review-manifest.json");
            var outputPath = Path.Combine(
                reviewRoot,
                "p3-quest2-review-render-probe.json");

            _status =
                "Loading exact P3 Quest student for review...\n" +
                manifestPath;

            var loader = gameObject.AddComponent<BodyRigP3QuestReviewLoader>();
            var probe = gameObject.AddComponent<BodyRigP3QuestReviewProbe>();
            await probe.RunProbeAsync(loader, manifestPath, outputPath);

            FrameActiveAvatar(loader);
            _status =
                "P3 Quest student: RENDERABLE\n" +
                "Eye + hair runtime nodes: VISIBLE\n" +
                "XR/stereo: NOT PROVEN (current review app is flat Android)\n" +
                "Inspect identity, face, eyes, hair, skin, hands/extremities.\n" +
                "Probe: " + probe.LastProbePath;
        }

        private static void CreateVisualRig()
        {
            if (Camera.main == null)
            {
                var cameraObject = new GameObject(
                    "BodyRig P3 Review Camera");
                cameraObject.tag = "MainCamera";
                var camera = cameraObject.AddComponent<Camera>();
                camera.clearFlags = CameraClearFlags.SolidColor;
                camera.backgroundColor = new Color(
                    0.08f,
                    0.08f,
                    0.09f,
                    1f);
                camera.fieldOfView = 35f;
                camera.nearClipPlane = 0.01f;
                camera.farClipPlane = 100f;
            }

            if (FindObjectOfType<Light>() == null)
            {
                CreateDirectionalLight(
                    "BodyRig P3 Review Key",
                    1.15f,
                    new Vector3(36f, -32f, 0f));
                CreateDirectionalLight(
                    "BodyRig P3 Review Fill",
                    0.28f,
                    new Vector3(18f, 145f, 0f));
                CreateDirectionalLight(
                    "BodyRig P3 Review Rim",
                    0.38f,
                    new Vector3(52f, 205f, 0f));
            }

            RenderSettings.ambientMode =
                UnityEngine.Rendering.AmbientMode.Flat;
            RenderSettings.ambientLight = new Color(
                0.16f,
                0.16f,
                0.16f,
                1f);
        }

        private static Light CreateDirectionalLight(
            string name,
            float intensity,
            Vector3 rotation)
        {
            var lightObject = new GameObject(name);
            var light = lightObject.AddComponent<Light>();
            light.type = LightType.Directional;
            light.intensity = intensity;
            lightObject.transform.rotation = Quaternion.Euler(rotation);
            return light;
        }

        private static void FrameActiveAvatar(
            BodyRigP3QuestReviewLoader loader)
        {
            if (loader.Active == null || Camera.main == null)
            {
                return;
            }

            var renderers = loader.Active.GetComponentsInChildren<Renderer>(
                true);
            if (renderers == null || renderers.Length == 0)
            {
                return;
            }

            var bounds = renderers[0].bounds;
            for (var index = 1; index < renderers.Length; index++)
            {
                bounds.Encapsulate(renderers[index].bounds);
            }

            var height = Mathf.Max(bounds.size.y, 1f);
            var target = bounds.center + Vector3.up * height * 0.03f;
            var camera = Camera.main;
            camera.transform.position =
                target + new Vector3(0f, 0f, height * 1.65f);
            camera.transform.LookAt(target);
        }

        private void OnGUI()
        {
            var width = Mathf.Min(Screen.width - 24f, 900f);
            var style = new GUIStyle(GUI.skin.box)
            {
                alignment = TextAnchor.UpperLeft,
                fontSize = Mathf.Max(14, Screen.height / 50),
                wordWrap = true,
                normal =
                {
                    textColor = _failed
                        ? new Color(1f, 0.55f, 0.55f)
                        : Color.white,
                },
            };
            GUI.Box(
                new Rect(12f, 12f, width, 190f),
                _status,
                style);
        }
    }
}
