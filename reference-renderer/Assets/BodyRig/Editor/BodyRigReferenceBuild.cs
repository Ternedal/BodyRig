using System;
using System.IO;
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
            EnsureProbeScene();
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

            Debug.Log($"BodyRig reference renderer build: PASS | {target} | {output}");
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
