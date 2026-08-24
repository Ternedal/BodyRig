using System;
using System.IO;
using System.Text;
using UnityEditor;
using UnityEditor.Build.Reporting;
using UnityEditor.SceneManagement;
using UnityEngine;
using UnityEngine.SceneManagement;

namespace BodyRig.ReferenceRenderer.Editor
{
    public static class BodyRigReferenceBuild
    {
        private const string GeneratedScenePath = "Assets/BodyRigGenerated/PhysicalProbe.unity";
        private const string GeneratedProvenancePath = "Assets/BodyRigGenerated/Resources/bodyrig-build-provenance.json";
        private const string ApplicationId = "dk.ternedal.bodyrig.reference";

        [MenuItem("BodyRig/Build/Windows Physical Probe")]
        public static void BuildWindows() => Build(BuildTarget.StandaloneWindows64, DefaultWindowsOutput());

        [MenuItem("BodyRig/Build/Quest-class Android Physical Probe")]
        public static void BuildQuest() => Build(BuildTarget.Android, DefaultQuestOutput());

        // Stable entry points for Unity -batchmode -executeMethod.
        public static void BuildWindowsBatch() => BuildWindows();
        public static void BuildQuestBatch() => BuildQuest();

        private static void Build(BuildTarget target, string defaultOutput)
        {
            var unityVersion = RequireUnityVersionArgument();
            var revision = RequireRevisionArgument();
            EnsureProbeScene();
            EnsureBuildProvenance(revision);
            ConfigurePlayer(target);

            var output = GetArgument("-bodyrigOutput") ?? defaultOutput;
            output = Path.GetFullPath(output);
            var parent = Path.GetDirectoryName(output);
            if (string.IsNullOrEmpty(parent)) throw new InvalidOperationException("BodyRig build output has no parent directory");
            Directory.CreateDirectory(parent);

            var options = new BuildPlayerOptions
            {
                scenes = new[] { GeneratedScenePath },
                locationPathName = output,
                target = target,
                options = BuildOptions.Development,
            };
            var report = BuildPipeline.BuildPlayer(options);
            if (report.summary.result != BuildResult.Succeeded)
                throw new InvalidOperationException($"BodyRig reference renderer build failed: {report.summary.result} | {report.summary.totalErrors} errors");

            Debug.Log($"BodyRig reference renderer build: PASS | {target} | revision {revision} | Unity {unityVersion} | {output}");
        }

        private static string RequireUnityVersionArgument()
        {
            var expected = (GetArgument("-bodyrigUnityVersion") ?? string.Empty).Trim();
            if (string.IsNullOrEmpty(expected))
                throw new InvalidOperationException("Physical reference build requires -bodyrigUnityVersion from renderer-contract.json");
            if (!string.Equals(Application.unityVersion, expected, StringComparison.Ordinal))
                throw new InvalidOperationException($"Physical reference build requires Unity {expected}; actual editor is {Application.unityVersion}");
            return expected;
        }

        private static string RequireRevisionArgument()
        {
            var revision = (GetArgument("-bodyrigRevision") ?? string.Empty).Trim().ToLowerInvariant();
            if (revision.Length != 40) throw new InvalidOperationException("Physical reference build requires -bodyrigRevision with an exact 40-character Git SHA");
            foreach (var character in revision)
            {
                if (!((character >= '0' && character <= '9') || (character >= 'a' && character <= 'f')))
                    throw new InvalidOperationException("Physical reference build received a non-canonical BodyRig Git SHA");
            }
            return revision;
        }

        private static void EnsureBuildProvenance(string revision)
        {
            var directory = Path.GetDirectoryName(GeneratedProvenancePath);
            if (string.IsNullOrEmpty(directory)) throw new InvalidOperationException("BodyRig generated provenance path has no parent directory");
            Directory.CreateDirectory(directory);
            var json = "{\n" +
                       "  \"format\": \"bodyrig-build-provenance\",\n" +
                       "  \"version\": 1,\n" +
                       $"  \"bodyrig_revision\": \"{revision}\"\n" +
                       "}\n";
            File.WriteAllText(GeneratedProvenancePath, json, new UTF8Encoding(false));
            AssetDatabase.ImportAsset(GeneratedProvenancePath, ImportAssetOptions.ForceSynchronousImport | ImportAssetOptions.ForceUpdate);
        }

        private static void EnsureProbeScene()
        {
            var directory = Path.GetDirectoryName(GeneratedScenePath);
            if (!string.IsNullOrEmpty(directory)) Directory.CreateDirectory(directory);
            var scene = EditorSceneManager.NewScene(NewSceneSetup.EmptyScene, NewSceneMode.Single);
            if (!EditorSceneManager.SaveScene(scene, GeneratedScenePath))
                throw new InvalidOperationException("Could not save generated BodyRig physical-probe scene");
            AssetDatabase.Refresh();
        }

        private static void ConfigurePlayer(BuildTarget target)
        {
            PlayerSettings.companyName = "Ternedal";
            PlayerSettings.productName = "BodyRig Reference Probe";
            PlayerSettings.SetApplicationIdentifier(BuildTargetGroup.Standalone, ApplicationId);
            PlayerSettings.SetApplicationIdentifier(BuildTargetGroup.Android, ApplicationId);
            PlayerSettings.defaultInterfaceOrientation = UIOrientation.LandscapeLeft;

            if (target == BuildTarget.Android)
            {
                PlayerSettings.Android.targetArchitectures = AndroidArchitecture.ARM64;
                PlayerSettings.Android.minSdkVersion = AndroidSdkVersions.AndroidApiLevel29;
                PlayerSettings.Android.targetSdkVersion = AndroidSdkVersions.AndroidApiLevelAuto;
                EditorUserBuildSettings.androidBuildSystem = AndroidBuildSystem.Gradle;
            }
        }

        private static string DefaultWindowsOutput() => Path.Combine("Builds", "Windows", "BodyRigReferenceProbe.exe");
        private static string DefaultQuestOutput() => Path.Combine("Builds", "Quest", "BodyRigReferenceProbe.apk");

        private static string GetArgument(string name)
        {
            var args = Environment.GetCommandLineArgs();
            for (var index = 0; index < args.Length - 1; index++)
                if (string.Equals(args[index], name, StringComparison.OrdinalIgnoreCase)) return args[index + 1];
            return null;
        }
    }
}
