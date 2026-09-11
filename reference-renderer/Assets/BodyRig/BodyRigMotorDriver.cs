using System;
using UniVRM10;
using UnityEngine;

namespace BodyRig.ReferenceRenderer
{
    /// <summary>
    /// Reference renderer for BodyRig Motor State v1, v2 and v3.
    ///
    /// It consumes already-personalized performed values from BodyRig. It does
    /// not reinterpret ModelRig semantics, read BodyPrint itself, or multiply
    /// observed embodiment evidence into performed values a second time.
    /// Motor State v3 locomotion and source-marked natural posture are realized
    /// only when explicit performed objects are present.
    /// </summary>
    public sealed class BodyRigMotorDriver : MonoBehaviour
    {
        private const string ObservedEmbodimentSource = "modelrig-bodyprint-v1";

        [Serializable]
        private sealed class MotionState
        {
            public float energy;
            public float head_motion;
        }

        [Serializable]
        private sealed class ExpressionState
        {
            public string emotion;
            public float intensity;
        }

        [Serializable]
        private sealed class GestureState
        {
            public string id;
            public float amplitude;
        }

        [Serializable]
        private sealed class GazeState
        {
            public string target;
            public float strength;
        }

        [Serializable]
        private sealed class PostureState
        {
            public string id;
            public string source;
            public float intensity;
            public float torso_forward_lean_degrees;
            public float torso_right_lean_degrees;
            public float shoulder_roll_degrees;
            public float hip_roll_degrees;
            public float head_forward_offset_to_height;
            public float head_right_offset_to_height;
        }

        [Serializable]
        private sealed class LocomotionState
        {
            public string action;
            public float effort;
            public float transition_intensity;
            public float cadence_spm;
            public float stride_length_to_height;
            public float stance_width_to_height;
            public float vertical_bounce_to_height;
            public float left_arm_swing_to_height;
            public float right_arm_swing_to_height;
            public float arm_swing_to_height;
            public float turn_speed_degrees_per_second;
        }

        [Serializable]
        private sealed class SpeechState
        {
            public string state;
            public int elapsed_ms;
            public string viseme;
            public float amplitude;
        }

        [Serializable]
        private sealed class ObservedEmbodimentState
        {
            public float energy;
            public float gesture_frequency;
            public float gesture_amplitude;
            public float head_motion;
            public float turn_speed;
            public float walk_cadence_spm;
            public float posture_torso_lean_degrees;
            public float posture_torso_forward_lean_degrees;
            public float posture_torso_right_lean_degrees;
            public float posture_shoulder_tilt_degrees;
            public float posture_shoulder_roll_degrees;
            public float posture_hip_tilt_degrees;
            public float posture_hip_roll_degrees;
            public float posture_head_offset_to_height;
            public float posture_head_forward_offset_to_height;
            public float posture_head_right_offset_to_height;
            public float stride_length_to_height;
            public float stance_width_to_height;
            public float vertical_bounce_to_height;
            public float left_arm_swing_to_height;
            public float right_arm_swing_to_height;
            public float arm_swing_to_height;
            public float arm_swing_asymmetry;
            public float turn_speed_degrees_per_second;
            public float transition_intensity;
            public float idle_sway_to_height;
            public float blink_rate_per_min;
            public float gaze_strength;
            public float head_tilt;
            public float speech_motion;
            public float idle_strength;
            public float gaze_smoothing;
            public float gesture_intensity;
            public float breathing_strength;
        }

        [Serializable]
        private sealed class EmbodimentState
        {
            public string source;
            public ObservedEmbodimentState observed;
        }

        [Serializable]
        private sealed class MotorState
        {
            public string type;
            public int version;
            public string body_id;
            public string utterance_id;
            public MotionState motion;
            public ExpressionState expression;
            public GestureState gesture;
            public GazeState gaze;
            public PostureState posture;
            public LocomotionState locomotion;
            public int duration_ms;
            public SpeechState speech;
            public EmbodimentState embodiment;
        }

        [SerializeField] private BodyRigAvatarLoader avatarLoader;
        [SerializeField] private Transform userGazeTarget;
        [SerializeField, Range(0.01f, 1.0f)] private float smoothingSeconds = 0.12f;

        private Animator _boundAnimator;
        private Transform _head;
        private Transform _spine;
        private Transform _hips;
        private Transform _leftShoulder;
        private Transform _rightShoulder;
        private Transform _leftUpperArm;
        private Transform _rightUpperArm;
        private Transform _rightLowerArm;
        private Transform _leftUpperLeg;
        private Transform _rightUpperLeg;
        private Transform _leftLowerLeg;
        private Transform _rightLowerLeg;
        private Transform _leftFoot;
        private Transform _rightFoot;
        private Quaternion _headBaseRotation;
        private Quaternion _spineBaseRotation;
        private Quaternion _hipsBaseRotation;
        private Quaternion _leftUpperArmBaseRotation;
        private Quaternion _rightUpperArmBaseRotation;
        private Quaternion _rightLowerArmBaseRotation;
        private Quaternion _leftUpperLegBaseRotation;
        private Quaternion _rightUpperLegBaseRotation;
        private Quaternion _leftLowerLegBaseRotation;
        private Quaternion _rightLowerLegBaseRotation;
        private Vector3 _headBasePosition;
        private Vector3 _hipsBasePosition;
        private Vector3 _leftShoulderBasePosition;
        private Vector3 _rightShoulderBasePosition;
        private float _shoulderSpan;
        private float _avatarHeight;
        private MotorState _state;
        private float _gestureAmplitude;
        private float _headMotion;
        private float _gazeStrength;
        private float _speechAmplitude;
        private bool _postureOwnedPoseLastFrame;
        private bool _sourcePostureOffsetsOwnedLastFrame;
        private bool _locomotionPoseOwnedLastFrame;
        private bool _locomotionArmPoseOwnedLastFrame;

        public int LastMotorVersion => _state != null ? _state.version : 0;
        public string LastBodyId => _state != null ? _state.body_id : null;
        public string LastUtteranceId => _state != null ? _state.utterance_id : null;
        public int RealizationFrameCount { get; private set; }
        public bool MotionRealized { get; private set; }
        public bool ExpressionRealized { get; private set; }
        public bool GestureRealized { get; private set; }
        public bool GazeRealized { get; private set; }
        public bool PostureRealized { get; private set; }
        public bool LocomotionRealized { get; private set; }
        public bool SpeechTimingRealized { get; private set; }
        public bool SourceObservedEmbodimentBound =>
            _state != null && _state.version >= 2 && _state.embodiment != null;

        public void Configure(BodyRigAvatarLoader configuredLoader, Transform configuredUserGazeTarget = null)
        {
            avatarLoader = configuredLoader != null ? configuredLoader : throw new ArgumentNullException(nameof(configuredLoader));
            userGazeTarget = configuredUserGazeTarget;
        }

        public void ApplyMotorJson(string json)
        {
            if (string.IsNullOrWhiteSpace(json))
            {
                throw new ArgumentException("BodyRig motor JSON is required", nameof(json));
            }

            var next = JsonUtility.FromJson<MotorState>(json);
            if (next == null || next.type != "bodyrig-motor-state" || (next.version != 1 && next.version != 2 && next.version != 3))
            {
                throw new ArgumentException("Unsupported BodyRig Motor State", nameof(json));
            }
            if (string.IsNullOrWhiteSpace(next.body_id) || string.IsNullOrWhiteSpace(next.utterance_id) || next.motion == null)
            {
                throw new ArgumentException("Incomplete BodyRig Motor State", nameof(json));
            }
            if (next.version == 1 && next.embodiment != null)
            {
                throw new ArgumentException("Motor State v1 may not carry observed embodiment evidence", nameof(json));
            }
            if (next.version < 3 && next.locomotion != null)
            {
                throw new ArgumentException("Motor State v1/v2 may not carry locomotion", nameof(json));
            }
            if (next.version >= 2 && next.embodiment != null)
            {
                if (next.embodiment.source != ObservedEmbodimentSource || next.embodiment.observed == null)
                {
                    throw new ArgumentException("Unsupported BodyRig embodiment evidence", nameof(json));
                }
                ValidateObservedEmbodiment(next.embodiment.observed);
            }

            Validate01(next.motion.energy, "motion.energy");
            Validate01(next.motion.head_motion, "motion.head_motion");
            if (next.expression != null)
            {
                if (string.IsNullOrWhiteSpace(next.expression.emotion)) throw new ArgumentException("Expression emotion is required", nameof(json));
                Validate01(next.expression.intensity, "expression.intensity");
            }
            if (next.gesture != null)
            {
                if (string.IsNullOrWhiteSpace(next.gesture.id)) throw new ArgumentException("Gesture id is required", nameof(json));
                Validate01(next.gesture.amplitude, "gesture.amplitude");
            }
            if (next.gaze != null)
            {
                if (string.IsNullOrWhiteSpace(next.gaze.target)) throw new ArgumentException("Gaze target is required", nameof(json));
                Validate01(next.gaze.strength, "gaze.strength");
            }
            if (next.posture != null)
            {
                ValidatePosture(next.posture, next.version);
            }
            if (next.locomotion != null)
            {
                if (next.version != 3) throw new ArgumentException("Locomotion requires Motor State v3", nameof(json));
                ValidateLocomotion(next.locomotion);
            }
            if (next.speech != null)
            {
                if (next.speech.state != "start" && next.speech.state != "update" && next.speech.state != "stop")
                    throw new ArgumentException("Unsupported speech timing state", nameof(json));
                if (next.speech.elapsed_ms < 0) throw new ArgumentOutOfRangeException("speech.elapsed_ms");
                Validate01(next.speech.amplitude, "speech.amplitude");
            }

            _state = next;
            RealizationFrameCount = 0;
            MotionRealized = false;
            ExpressionRealized = false;
            GestureRealized = false;
            GazeRealized = false;
            PostureRealized = false;
            LocomotionRealized = false;
            SpeechTimingRealized = false;
        }

        private static void ValidatePosture(PostureState posture, int version)
        {
            if (posture == null || string.IsNullOrWhiteSpace(posture.id))
                throw new ArgumentException("Posture id is required");
            Validate01(posture.intensity, "posture.intensity");

            // Frozen legacy/generic posture ids carry no source marker. Even an
            // old id literally named "natural" remains generic and must not be
            // reinterpreted as Movement Identity authority.
            if (string.IsNullOrWhiteSpace(posture.source))
            {
                return;
            }
            if (version != 3 || posture.id != "natural" || posture.source != ObservedEmbodimentSource)
                throw new ArgumentException("Source-derived natural posture requires Motor State v3 and modelrig-bodyprint-v1 authority");

            ValidateRange(posture.torso_forward_lean_degrees, -90.0f, 90.0f, "posture.torso_forward_lean_degrees");
            ValidateRange(posture.torso_right_lean_degrees, -90.0f, 90.0f, "posture.torso_right_lean_degrees");
            ValidateRange(posture.shoulder_roll_degrees, -90.0f, 90.0f, "posture.shoulder_roll_degrees");
            ValidateRange(posture.hip_roll_degrees, -90.0f, 90.0f, "posture.hip_roll_degrees");
            ValidateRange(posture.head_forward_offset_to_height, -1.0f, 1.0f, "posture.head_forward_offset_to_height");
            ValidateRange(posture.head_right_offset_to_height, -1.0f, 1.0f, "posture.head_right_offset_to_height");
        }

        private static void ValidateLocomotion(LocomotionState locomotion)
        {
            if (locomotion == null || string.IsNullOrWhiteSpace(locomotion.action))
                throw new ArgumentException("Locomotion action is required");
            Validate01(locomotion.effort, "locomotion.effort");
            Validate01(locomotion.transition_intensity, "locomotion.transition_intensity");
            switch (locomotion.action)
            {
                case "walk":
                    ValidateRange(locomotion.cadence_spm, 30.0f, 240.0f, "locomotion.cadence_spm");
                    ValidateRange(locomotion.stride_length_to_height, 0.0f, 2.0f, "locomotion.stride_length_to_height");
                    Validate01(locomotion.stance_width_to_height, "locomotion.stance_width_to_height");
                    Validate01(locomotion.vertical_bounce_to_height, "locomotion.vertical_bounce_to_height");
                    ValidateRange(locomotion.left_arm_swing_to_height, 0.0f, 2.0f, "locomotion.left_arm_swing_to_height");
                    ValidateRange(locomotion.right_arm_swing_to_height, 0.0f, 2.0f, "locomotion.right_arm_swing_to_height");
                    ValidateRange(locomotion.arm_swing_to_height, 0.0f, 2.0f, "locomotion.arm_swing_to_height");
                    return;
                case "turn_left":
                case "turn_right":
                    ValidateRange(locomotion.turn_speed_degrees_per_second, 0.0001f, 720.0f, "locomotion.turn_speed_degrees_per_second");
                    return;
                case "stop":
                    return;
                default:
                    throw new ArgumentException("Unsupported locomotion action");
            }
        }

        private static void ValidateObservedEmbodiment(ObservedEmbodimentState observed)
        {
            Validate01(observed.energy, "embodiment.observed.energy");
            Validate01(observed.gesture_frequency, "embodiment.observed.gesture_frequency");
            Validate01(observed.gesture_amplitude, "embodiment.observed.gesture_amplitude");
            Validate01(observed.head_motion, "embodiment.observed.head_motion");
            Validate01(observed.turn_speed, "embodiment.observed.turn_speed");
            ValidateRange(observed.walk_cadence_spm, 0.0f, 300.0f, "embodiment.observed.walk_cadence_spm");
            ValidateRange(observed.posture_torso_lean_degrees, 0.0f, 90.0f, "embodiment.observed.posture_torso_lean_degrees");
            ValidateRange(observed.posture_torso_forward_lean_degrees, -90.0f, 90.0f, "embodiment.observed.posture_torso_forward_lean_degrees");
            ValidateRange(observed.posture_torso_right_lean_degrees, -90.0f, 90.0f, "embodiment.observed.posture_torso_right_lean_degrees");
            ValidateRange(observed.posture_shoulder_tilt_degrees, 0.0f, 90.0f, "embodiment.observed.posture_shoulder_tilt_degrees");
            ValidateRange(observed.posture_shoulder_roll_degrees, -90.0f, 90.0f, "embodiment.observed.posture_shoulder_roll_degrees");
            ValidateRange(observed.posture_hip_tilt_degrees, 0.0f, 90.0f, "embodiment.observed.posture_hip_tilt_degrees");
            ValidateRange(observed.posture_hip_roll_degrees, -90.0f, 90.0f, "embodiment.observed.posture_hip_roll_degrees");
            Validate01(observed.posture_head_offset_to_height, "embodiment.observed.posture_head_offset_to_height");
            ValidateRange(observed.posture_head_forward_offset_to_height, -1.0f, 1.0f, "embodiment.observed.posture_head_forward_offset_to_height");
            ValidateRange(observed.posture_head_right_offset_to_height, -1.0f, 1.0f, "embodiment.observed.posture_head_right_offset_to_height");
            ValidateRange(observed.stride_length_to_height, 0.0f, 2.0f, "embodiment.observed.stride_length_to_height");
            Validate01(observed.stance_width_to_height, "embodiment.observed.stance_width_to_height");
            Validate01(observed.vertical_bounce_to_height, "embodiment.observed.vertical_bounce_to_height");
            ValidateRange(observed.left_arm_swing_to_height, 0.0f, 2.0f, "embodiment.observed.left_arm_swing_to_height");
            ValidateRange(observed.right_arm_swing_to_height, 0.0f, 2.0f, "embodiment.observed.right_arm_swing_to_height");
            ValidateRange(observed.arm_swing_to_height, 0.0f, 2.0f, "embodiment.observed.arm_swing_to_height");
            Validate01(observed.arm_swing_asymmetry, "embodiment.observed.arm_swing_asymmetry");
            ValidateRange(observed.turn_speed_degrees_per_second, 0.0f, 720.0f, "embodiment.observed.turn_speed_degrees_per_second");
            Validate01(observed.transition_intensity, "embodiment.observed.transition_intensity");
            Validate01(observed.idle_sway_to_height, "embodiment.observed.idle_sway_to_height");
            ValidateRange(observed.blink_rate_per_min, 0.0f, 120.0f, "embodiment.observed.blink_rate_per_min");
            Validate01(observed.gaze_strength, "embodiment.observed.gaze_strength");
            Validate01(observed.head_tilt, "embodiment.observed.head_tilt");
            Validate01(observed.speech_motion, "embodiment.observed.speech_motion");
            Validate01(observed.idle_strength, "embodiment.observed.idle_strength");
            Validate01(observed.gaze_smoothing, "embodiment.observed.gaze_smoothing");
            Validate01(observed.gesture_intensity, "embodiment.observed.gesture_intensity");
            Validate01(observed.breathing_strength, "embodiment.observed.breathing_strength");
        }

        private static void Validate01(float value, string field)
        {
            ValidateRange(value, 0.0f, 1.0f, field);
        }

        private static void ValidateRange(float value, float minimum, float maximum, string field)
        {
            if (float.IsNaN(value) || float.IsInfinity(value) || value < minimum || value > maximum)
            {
                throw new ArgumentOutOfRangeException(field, $"BodyRig motor value must be in {minimum}..{maximum}");
            }
        }

        private bool HasSourceDerivedNaturalPosture()
        {
            return _state != null && _state.version == 3 && _state.posture != null &&
                _state.posture.id == "natural" && _state.posture.source == ObservedEmbodimentSource;
        }

        private bool HasSupportedPerformedPosture()
        {
            if (_state == null || _state.posture == null)
            {
                return false;
            }
            if (HasSourceDerivedNaturalPosture())
            {
                return true;
            }
            if (!string.IsNullOrWhiteSpace(_state.posture.source))
            {
                return false;
            }
            return _state.posture.id == "neutral" || _state.posture.id == "upright";
        }

        private void LateUpdate()
        {
            BindAvatarIfNeeded();
            if (_boundAnimator == null || _state == null)
            {
                return;
            }

            var dt = Mathf.Max(Time.unscaledDeltaTime, 0.0001f);
            var blend = 1.0f - Mathf.Exp(-dt / Mathf.Max(smoothingSeconds, 0.01f));
            var sourceNaturalPosture = HasSourceDerivedNaturalPosture();
            var performedPosture = HasSupportedPerformedPosture();

            // Only posture owns these bind-relative offsets. Reset them while a
            // source posture is being recomposed, or once while clearing the
            // previous source posture. With no posture before or now, Animator/
            // VRMA bone transforms are left untouched.
            if (sourceNaturalPosture || _sourcePostureOffsetsOwnedLastFrame)
            {
                RestorePostureOffsetsForFrame();
            }
            if (_postureOwnedPoseLastFrame && !performedPosture && _spine != null)
            {
                _spine.localRotation = _spineBaseRotation;
            }

            // These fields are already performed values resolved by BodyRig.
            // Raw embodiment evidence is never consumed here.
            var targetGesture = _state.gesture != null ? _state.gesture.amplitude : 0.0f;
            var targetHead = _state.motion != null ? _state.motion.head_motion : 0.0f;
            var targetGaze = _state.gaze != null ? _state.gaze.strength : 0.0f;
            var targetSpeech = _state.speech != null ? _state.speech.amplitude : 0.0f;

            _gestureAmplitude = Mathf.Lerp(_gestureAmplitude, targetGesture, blend);
            _headMotion = Mathf.Lerp(_headMotion, targetHead, blend);
            _gazeStrength = Mathf.Lerp(_gazeStrength, targetGaze, blend);
            _speechAmplitude = Mathf.Lerp(_speechAmplitude, targetSpeech, blend);

            LocomotionRealized = ApplyLocomotion(dt);
            MotionRealized = ApplyHeadMotion();
            GestureRealized = ApplyGesture();
            GazeRealized = ApplyGaze();
            PostureRealized = ApplyPosture();
            _postureOwnedPoseLastFrame = PostureRealized;
            _sourcePostureOffsetsOwnedLastFrame = sourceNaturalPosture && PostureRealized;
            ExpressionRealized = ApplyExpression();
            SpeechTimingRealized = ApplySpeech();
            RealizationFrameCount++;
        }

        private void BindAvatarIfNeeded()
        {
            var animator = avatarLoader != null ? avatarLoader.Animator : null;
            if (animator == _boundAnimator)
            {
                return;
            }

            _boundAnimator = animator;
            _head = null;
            _spine = null;
            _hips = null;
            _leftShoulder = null;
            _rightShoulder = null;
            _leftUpperArm = null;
            _rightUpperArm = null;
            _rightLowerArm = null;
            _leftUpperLeg = null;
            _rightUpperLeg = null;
            _leftLowerLeg = null;
            _rightLowerLeg = null;
            _leftFoot = null;
            _rightFoot = null;
            _gestureAmplitude = 0.0f;
            _headMotion = 0.0f;
            _gazeStrength = 0.0f;
            _speechAmplitude = 0.0f;
            _postureOwnedPoseLastFrame = false;
            _sourcePostureOffsetsOwnedLastFrame = false;
            _locomotionPoseOwnedLastFrame = false;
            _locomotionArmPoseOwnedLastFrame = false;
            _shoulderSpan = 0.0f;
            _avatarHeight = 0.0f;
            RealizationFrameCount = 0;

            if (_boundAnimator == null)
            {
                return;
            }

            _head = _boundAnimator.GetBoneTransform(HumanBodyBones.Head);
            _spine = _boundAnimator.GetBoneTransform(HumanBodyBones.Spine);
            _hips = _boundAnimator.GetBoneTransform(HumanBodyBones.Hips);
            _leftShoulder = _boundAnimator.GetBoneTransform(HumanBodyBones.LeftShoulder)
                ?? _boundAnimator.GetBoneTransform(HumanBodyBones.LeftUpperArm);
            _rightShoulder = _boundAnimator.GetBoneTransform(HumanBodyBones.RightShoulder)
                ?? _boundAnimator.GetBoneTransform(HumanBodyBones.RightUpperArm);
            _leftUpperArm = _boundAnimator.GetBoneTransform(HumanBodyBones.LeftUpperArm);
            _rightUpperArm = _boundAnimator.GetBoneTransform(HumanBodyBones.RightUpperArm);
            _rightLowerArm = _boundAnimator.GetBoneTransform(HumanBodyBones.RightLowerArm);
            _leftUpperLeg = _boundAnimator.GetBoneTransform(HumanBodyBones.LeftUpperLeg);
            _rightUpperLeg = _boundAnimator.GetBoneTransform(HumanBodyBones.RightUpperLeg);
            _leftLowerLeg = _boundAnimator.GetBoneTransform(HumanBodyBones.LeftLowerLeg);
            _rightLowerLeg = _boundAnimator.GetBoneTransform(HumanBodyBones.RightLowerLeg);
            _leftFoot = _boundAnimator.GetBoneTransform(HumanBodyBones.LeftFoot);
            _rightFoot = _boundAnimator.GetBoneTransform(HumanBodyBones.RightFoot);

            if (_head != null)
            {
                _headBaseRotation = _head.localRotation;
                _headBasePosition = _head.localPosition;
            }
            if (_spine != null) _spineBaseRotation = _spine.localRotation;
            if (_hips != null)
            {
                _hipsBasePosition = _hips.localPosition;
                _hipsBaseRotation = _hips.localRotation;
            }
            if (_leftShoulder != null) _leftShoulderBasePosition = _leftShoulder.localPosition;
            if (_rightShoulder != null) _rightShoulderBasePosition = _rightShoulder.localPosition;
            if (_leftUpperArm != null) _leftUpperArmBaseRotation = _leftUpperArm.localRotation;
            if (_rightUpperArm != null) _rightUpperArmBaseRotation = _rightUpperArm.localRotation;
            if (_rightLowerArm != null) _rightLowerArmBaseRotation = _rightLowerArm.localRotation;
            if (_leftUpperLeg != null) _leftUpperLegBaseRotation = _leftUpperLeg.localRotation;
            if (_rightUpperLeg != null) _rightUpperLegBaseRotation = _rightUpperLeg.localRotation;
            if (_leftLowerLeg != null) _leftLowerLegBaseRotation = _leftLowerLeg.localRotation;
            if (_rightLowerLeg != null) _rightLowerLegBaseRotation = _rightLowerLeg.localRotation;
            if (_leftShoulder != null && _rightShoulder != null)
            {
                _shoulderSpan = Vector3.Distance(_leftShoulder.position, _rightShoulder.position);
            }
            if (_head != null && _leftFoot != null && _rightFoot != null)
            {
                var feetMid = (_leftFoot.position + _rightFoot.position) * 0.5f;
                _avatarHeight = Vector3.Distance(_head.position, feetMid);
            }
        }

        private float LocomotionBlend(float dt, float transitionIntensity)
        {
            var seconds = Mathf.Lerp(0.30f, 0.06f, Mathf.Clamp01(transitionIntensity));
            return 1.0f - Mathf.Exp(-Mathf.Max(dt, 0.0001f) / seconds);
        }

        private void BlendLocomotionPoseToBase(float blend, bool includeArms)
        {
            if (_hips != null) _hips.localPosition = Vector3.Lerp(_hips.localPosition, _hipsBasePosition, blend);
            if (_leftUpperLeg != null) _leftUpperLeg.localRotation = Quaternion.Slerp(_leftUpperLeg.localRotation, _leftUpperLegBaseRotation, blend);
            if (_rightUpperLeg != null) _rightUpperLeg.localRotation = Quaternion.Slerp(_rightUpperLeg.localRotation, _rightUpperLegBaseRotation, blend);
            if (_leftLowerLeg != null) _leftLowerLeg.localRotation = Quaternion.Slerp(_leftLowerLeg.localRotation, _leftLowerLegBaseRotation, blend);
            if (_rightLowerLeg != null) _rightLowerLeg.localRotation = Quaternion.Slerp(_rightLowerLeg.localRotation, _rightLowerLegBaseRotation, blend);
            if (includeArms)
            {
                if (_leftUpperArm != null) _leftUpperArm.localRotation = Quaternion.Slerp(_leftUpperArm.localRotation, _leftUpperArmBaseRotation, blend);
                if (_rightUpperArm != null) _rightUpperArm.localRotation = Quaternion.Slerp(_rightUpperArm.localRotation, _rightUpperArmBaseRotation, blend);
            }
        }

        private bool ApplyLocomotion(float dt)
        {
            var locomotion = _state != null ? _state.locomotion : null;
            if (locomotion == null)
            {
                // Releasing locomotion ownership means stopping BodyRig writes.
                // Animator/VRMA has already evaluated before LateUpdate, so a
                // bind-pose restore here would overwrite its current frame.
                _locomotionPoseOwnedLastFrame = false;
                _locomotionArmPoseOwnedLastFrame = false;
                return false;
            }

            var locomotionBlend = LocomotionBlend(dt, locomotion.transition_intensity);
            if (locomotion.action == "stop")
            {
                // Stop only settles a pose that BodyRig actually owns. A stop
                // cue arriving over an external Animator pose must not pull it
                // toward BodyRig's captured bind pose. Arms are included only
                // if the preceding gait frame actually owned them.
                if (_locomotionPoseOwnedLastFrame)
                {
                    BlendLocomotionPoseToBase(locomotionBlend, _locomotionArmPoseOwnedLastFrame);
                }
                return true;
            }

            if (locomotion.action == "turn_left" || locomotion.action == "turn_right")
            {
                // Turning owns root heading only. Releasing any preceding gait
                // is a bookkeeping change, not a bind-pose write over Animator.
                _locomotionPoseOwnedLastFrame = false;
                _locomotionArmPoseOwnedLastFrame = false;
                if (_boundAnimator == null) return false;
                var direction = locomotion.action == "turn_left" ? -1.0f : 1.0f;
                _boundAnimator.transform.Rotate(
                    0.0f,
                    direction * locomotion.turn_speed_degrees_per_second * dt,
                    0.0f,
                    Space.Self);
                return true;
            }

            if (locomotion.action != "walk") return false;
            if (_hips == null || _leftUpperLeg == null || _rightUpperLeg == null ||
                _leftLowerLeg == null || _rightLowerLeg == null || _avatarHeight <= 0.0001f)
            {
                return false;
            }

            // cadence_spm is steps/minute. One full left/right cycle contains
            // two steps, hence cadence / 120 cycles per second.
            var phase = Time.unscaledTime * (locomotion.cadence_spm / 120.0f) * Mathf.PI * 2.0f;
            var legWave = Mathf.Sin(phase);
            var strideDegrees = Mathf.Clamp(locomotion.stride_length_to_height * 90.0f, 0.0f, 45.0f);
            var stanceDegrees = Mathf.Clamp(locomotion.stance_width_to_height * 80.0f, 0.0f, 20.0f);
            var kneeDegrees = Mathf.Clamp(locomotion.stride_length_to_height * 70.0f, 0.0f, 35.0f);

            var leftUpperTarget = _leftUpperLegBaseRotation * Quaternion.Euler(
                legWave * strideDegrees, 0.0f, stanceDegrees);
            var rightUpperTarget = _rightUpperLegBaseRotation * Quaternion.Euler(
                -legWave * strideDegrees, 0.0f, -stanceDegrees);
            var leftLowerTarget = _leftLowerLegBaseRotation * Quaternion.Euler(
                Mathf.Max(0.0f, -legWave) * kneeDegrees, 0.0f, 0.0f);
            var rightLowerTarget = _rightLowerLegBaseRotation * Quaternion.Euler(
                Mathf.Max(0.0f, legWave) * kneeDegrees, 0.0f, 0.0f);

            _leftUpperLeg.localRotation = Quaternion.Slerp(_leftUpperLeg.localRotation, leftUpperTarget, locomotionBlend);
            _rightUpperLeg.localRotation = Quaternion.Slerp(_rightUpperLeg.localRotation, rightUpperTarget, locomotionBlend);
            _leftLowerLeg.localRotation = Quaternion.Slerp(_leftLowerLeg.localRotation, leftLowerTarget, locomotionBlend);
            _rightLowerLeg.localRotation = Quaternion.Slerp(_rightLowerLeg.localRotation, rightLowerTarget, locomotionBlend);

            var bounceRange = locomotion.vertical_bounce_to_height * _avatarHeight;
            var bounceOffset = Mathf.Sin(phase * 2.0f) * bounceRange * 0.5f;
            _hips.localPosition = Vector3.Lerp(
                _hips.localPosition,
                _hipsBasePosition + Vector3.up * bounceOffset,
                locomotionBlend);

            // A simultaneous explicit gesture owns the arms. Otherwise each
            // anatomical arm follows its own already-performed v3 amplitude.
            // One shared safety scale bounds the larger arm to 45 degrees while
            // preserving the anatomical left/right ordering and ratio.
            var locomotionOwnsArms = _state.gesture == null && _leftUpperArm != null && _rightUpperArm != null;
            if (locomotionOwnsArms)
            {
                var maxArmSwing = Mathf.Max(
                    locomotion.left_arm_swing_to_height,
                    locomotion.right_arm_swing_to_height);
                var armDegreesPerHeight = maxArmSwing > 0.0001f
                    ? Mathf.Min(90.0f, 45.0f / maxArmSwing)
                    : 90.0f;
                var leftArmDegrees = locomotion.left_arm_swing_to_height * armDegreesPerHeight;
                var rightArmDegrees = locomotion.right_arm_swing_to_height * armDegreesPerHeight;
                var leftArmTarget = _leftUpperArmBaseRotation * Quaternion.Euler(-legWave * leftArmDegrees, 0.0f, 0.0f);
                var rightArmTarget = _rightUpperArmBaseRotation * Quaternion.Euler(legWave * rightArmDegrees, 0.0f, 0.0f);
                _leftUpperArm.localRotation = Quaternion.Slerp(_leftUpperArm.localRotation, leftArmTarget, locomotionBlend);
                _rightUpperArm.localRotation = Quaternion.Slerp(_rightUpperArm.localRotation, rightArmTarget, locomotionBlend);
            }
            _locomotionPoseOwnedLastFrame = true;
            _locomotionArmPoseOwnedLastFrame = locomotionOwnsArms;
            return true;
        }

        private bool ApplyGesture()
        {
            if (_state.gesture == null) return false;
            if (_state.gesture.id == "small_shrug")
            {
                // This gesture owns shoulder translation only. Do not reset an
                // Animator/VRMA arm pose simply because a shrug is active.
                var lift = 0.025f * _gestureAmplitude;
                if (_leftShoulder != null) _leftShoulder.localPosition = _leftShoulderBasePosition + Vector3.up * lift;
                if (_rightShoulder != null) _rightShoulder.localPosition = _rightShoulderBasePosition + Vector3.up * lift;
                return _leftShoulder != null && _rightShoulder != null;
            }
            if (_state.gesture.id == "present")
            {
                // Present owns only the right upper/lower arm. Shoulders remain
                // under Animator/VRMA/posture ownership for this frame.
                if (_rightUpperArm == null || _rightLowerArm == null) return false;
                _rightUpperArm.localRotation = _rightUpperArmBaseRotation * Quaternion.Euler(
                    -18.0f * _gestureAmplitude,
                    4.0f * _gestureAmplitude,
                    -34.0f * _gestureAmplitude);
                _rightLowerArm.localRotation = _rightLowerArmBaseRotation * Quaternion.Euler(
                    0.0f,
                    0.0f,
                    -28.0f * _gestureAmplitude);
                return true;
            }
            if (_state.gesture.id == "neutral")
            {
                // Neutral is an explicit reset request, so it may deliberately
                // restore the gesture-owned bind-relative pose.
                RestoreGesturePose();
                return true;
            }
            return false;
        }

        private bool ApplyHeadMotion()
        {
            if (_head == null || _state.motion == null) return false;
            if (_state.motion.head_motion <= 0.0f)
            {
                // A zero performed head-motion signal releases the head back to
                // Animator/VRMA. Do not restore the captured bind rotation in
                // LateUpdate, because that would overwrite external animation.
                _headMotion = 0.0f;
                return false;
            }
            var t = Time.unscaledTime;
            var speechBoost = 1.0f + 0.35f * _speechAmplitude;
            var microYaw = Mathf.Sin(t * 1.13f) * 2.0f * _headMotion * speechBoost;
            var microPitch = Mathf.Sin(t * 1.71f + 0.7f) * 1.2f * _headMotion * speechBoost;
            _head.localRotation = Quaternion.Slerp(
                _head.localRotation,
                _headBaseRotation * Quaternion.Euler(microPitch, microYaw, 0.0f),
                0.35f);
            return true;
        }

        private bool ApplyGaze()
        {
            if (_state.gaze == null) return false;
            if (_state.gaze.target != "user") return false;
            if (_state.gaze.strength <= 0.0f)
            {
                // Explicit zero gaze releases the head immediately instead of
                // letting a smoothed residual keep steering after BodyRig's
                // performed gaze authority has ended.
                _gazeStrength = 0.0f;
                return false;
            }
            if (_head == null || _head.parent == null || userGazeTarget == null) return false;
            var direction = userGazeTarget.position - _head.position;
            if (direction.sqrMagnitude <= 0.000001f) return false;
            var worldLook = Quaternion.LookRotation(direction.normalized, Vector3.up);
            var localLook = Quaternion.Inverse(_head.parent.rotation) * worldLook;
            _head.localRotation = Quaternion.Slerp(
                _head.localRotation,
                localLook,
                Mathf.Clamp01(_gazeStrength * 0.65f));
            return true;
        }

        private void RestorePostureOffsetsForFrame()
        {
            if (_head != null) _head.localPosition = _headBasePosition;
            if (_hips != null) _hips.localRotation = _hipsBaseRotation;
            if (_leftShoulder != null) _leftShoulder.localPosition = _leftShoulderBasePosition;
            if (_rightShoulder != null) _rightShoulder.localPosition = _rightShoulderBasePosition;
        }

        private Vector3 LocalOffsetForWorldVector(Transform target, Vector3 worldOffset)
        {
            if (target == null || target.parent == null)
            {
                return worldOffset;
            }
            return target.parent.InverseTransformVector(worldOffset);
        }

        private bool ApplyPosture()
        {
            if (_spine == null) return false;
            if (_state.posture == null)
            {
                return false;
            }
            if (_state.posture.id == "neutral")
            {
                _spine.localRotation = Quaternion.Slerp(_spine.localRotation, _spineBaseRotation, 0.35f);
                return true;
            }
            if (_state.posture.id == "upright")
            {
                _spine.localRotation = Quaternion.Slerp(
                    _spine.localRotation,
                    _spineBaseRotation * Quaternion.Euler(-4.0f * _state.posture.intensity, 0.0f, 0.0f),
                    0.35f);
                return true;
            }
            if (_state.posture.source != ObservedEmbodimentSource || _state.posture.id != "natural" ||
                _state.version != 3 || _boundAnimator == null || _avatarHeight <= 0.0001f)
            {
                return false;
            }

            var posture = _state.posture;
            var torsoTarget = _spineBaseRotation * Quaternion.Euler(
                posture.torso_forward_lean_degrees,
                0.0f,
                -posture.torso_right_lean_degrees);
            _spine.localRotation = Quaternion.Slerp(_spine.localRotation, torsoTarget, 0.35f);

            if (_hips != null)
            {
                // Recovery defines hip roll as rightHip.y - leftHip.y. Unity
                // positive local Z raises the avatar's right side, so preserve
                // that recovered sign rather than mirroring it.
                _hips.localRotation = _hipsBaseRotation * Quaternion.Euler(0.0f, 0.0f, posture.hip_roll_degrees);
            }

            if (_leftShoulder != null && _rightShoulder != null && _shoulderSpan > 0.0001f)
            {
                var verticalDifference = Mathf.Tan(posture.shoulder_roll_degrees * Mathf.Deg2Rad) * _shoulderSpan;
                var halfRise = Mathf.Clamp(verticalDifference * 0.5f, -0.25f * _avatarHeight, 0.25f * _avatarHeight);
                var up = _boundAnimator.transform.up;
                _leftShoulder.localPosition += LocalOffsetForWorldVector(_leftShoulder, -up * halfRise);
                _rightShoulder.localPosition += LocalOffsetForWorldVector(_rightShoulder, up * halfRise);
            }

            if (_head != null)
            {
                var worldOffset =
                    _boundAnimator.transform.forward * (posture.head_forward_offset_to_height * _avatarHeight) +
                    _boundAnimator.transform.right * (posture.head_right_offset_to_height * _avatarHeight);
                _head.localPosition = _headBasePosition + LocalOffsetForWorldVector(_head, worldOffset);
            }
            return true;
        }

        private bool ApplyExpression()
        {
            if (_state.expression == null || avatarLoader == null || avatarLoader.Active == null) return false;
            var expression = avatarLoader.Active.Runtime != null ? avatarLoader.Active.Runtime.Expression : null;
            if (expression == null) return false;

            // Affect is one semantic channel. Validate that BodyRig understands
            // the requested emotion before touching any renderer weights.
            switch (_state.expression.emotion)
            {
                case "neutral":
                case "happy":
                case "angry":
                case "sad":
                case "relaxed":
                case "surprised":
                    break;
                default:
                    return false;
            }

            // A previous affect must not leak into the next performed emotion.
            // Only affect keys are cleared here; speech visemes are a separate
            // simultaneously-owned channel and remain untouched.
            expression.SetWeight(ExpressionKey.Neutral, 0.0f);
            expression.SetWeight(ExpressionKey.Happy, 0.0f);
            expression.SetWeight(ExpressionKey.Angry, 0.0f);
            expression.SetWeight(ExpressionKey.Sad, 0.0f);
            expression.SetWeight(ExpressionKey.Relaxed, 0.0f);
            expression.SetWeight(ExpressionKey.Surprised, 0.0f);

            var weight = Mathf.Clamp01(_state.expression.intensity);
            switch (_state.expression.emotion)
            {
                case "neutral": expression.SetWeight(ExpressionKey.Neutral, weight); return true;
                case "happy": expression.SetWeight(ExpressionKey.Happy, weight); return true;
                case "angry": expression.SetWeight(ExpressionKey.Angry, weight); return true;
                case "sad": expression.SetWeight(ExpressionKey.Sad, weight); return true;
                case "relaxed": expression.SetWeight(ExpressionKey.Relaxed, weight); return true;
                case "surprised": expression.SetWeight(ExpressionKey.Surprised, weight); return true;
                default: return false;
            }
        }

        private bool ApplySpeech()
        {
            if (_state.speech == null || avatarLoader == null || avatarLoader.Active == null) return false;
            var expression = avatarLoader.Active.Runtime != null ? avatarLoader.Active.Runtime.Expression : null;
            if (expression == null) return false;

            // Speech stop owns the viseme channel even when no specific viseme
            // is supplied. Clear every mouth-shape weight so the last phoneme
            // cannot remain stuck after the utterance ends.
            if (_state.speech.state == "stop")
            {
                expression.SetWeight(ExpressionKey.Aa, 0.0f);
                expression.SetWeight(ExpressionKey.Ih, 0.0f);
                expression.SetWeight(ExpressionKey.Ou, 0.0f);
                expression.SetWeight(ExpressionKey.Ee, 0.0f);
                expression.SetWeight(ExpressionKey.Oh, 0.0f);
                return true;
            }

            if (string.IsNullOrWhiteSpace(_state.speech.viseme)) return false;
            var viseme = _state.speech.viseme.ToUpperInvariant();

            // Validate before mutating the viseme channel. Unsupported mouth
            // shapes fail closed without erasing the currently valid shape.
            switch (viseme)
            {
                case "AA":
                case "IH":
                case "OU":
                case "EE":
                case "OH":
                    break;
                default:
                    return false;
            }

            // Visemes are one mutually-exclusive speech channel. Affect keys
            // remain untouched so emotion and speech can coexist.
            expression.SetWeight(ExpressionKey.Aa, 0.0f);
            expression.SetWeight(ExpressionKey.Ih, 0.0f);
            expression.SetWeight(ExpressionKey.Ou, 0.0f);
            expression.SetWeight(ExpressionKey.Ee, 0.0f);
            expression.SetWeight(ExpressionKey.Oh, 0.0f);

            var weight = Mathf.Clamp01(_speechAmplitude);
            switch (viseme)
            {
                case "AA": expression.SetWeight(ExpressionKey.Aa, weight); return true;
                case "IH": expression.SetWeight(ExpressionKey.Ih, weight); return true;
                case "OU": expression.SetWeight(ExpressionKey.Ou, weight); return true;
                case "EE": expression.SetWeight(ExpressionKey.Ee, weight); return true;
                case "OH": expression.SetWeight(ExpressionKey.Oh, weight); return true;
                default: return false;
            }
        }

        private void RestoreGesturePose()
        {
            if (_leftShoulder != null) _leftShoulder.localPosition = _leftShoulderBasePosition;
            if (_rightShoulder != null) _rightShoulder.localPosition = _rightShoulderBasePosition;
            if (_rightUpperArm != null) _rightUpperArm.localRotation = _rightUpperArmBaseRotation;
            if (_rightLowerArm != null) _rightLowerArm.localRotation = _rightLowerArmBaseRotation;
        }

        private void RestoreLocomotionPose()
        {
            if (_hips != null) _hips.localPosition = _hipsBasePosition;
            if (_leftUpperLeg != null) _leftUpperLeg.localRotation = _leftUpperLegBaseRotation;
            if (_rightUpperLeg != null) _rightUpperLeg.localRotation = _rightUpperLegBaseRotation;
            if (_leftLowerLeg != null) _leftLowerLeg.localRotation = _leftLowerLegBaseRotation;
            if (_rightLowerLeg != null) _rightLowerLeg.localRotation = _rightLowerLegBaseRotation;
            if (_leftUpperArm != null) _leftUpperArm.localRotation = _leftUpperArmBaseRotation;
            if (_rightUpperArm != null) _rightUpperArm.localRotation = _rightUpperArmBaseRotation;
        }

        public void RestoreNeutralPose()
        {
            RestoreLocomotionPose();
            RestoreGesturePose();
            RestorePostureOffsetsForFrame();
            if (_head != null) _head.localRotation = _headBaseRotation;
            if (_spine != null) _spine.localRotation = _spineBaseRotation;
            if (avatarLoader != null && avatarLoader.Active != null && avatarLoader.Active.Runtime != null)
            {
                var expression = avatarLoader.Active.Runtime.Expression;
                expression.SetWeight(ExpressionKey.Neutral, 0.0f);
                expression.SetWeight(ExpressionKey.Happy, 0.0f);
                expression.SetWeight(ExpressionKey.Angry, 0.0f);
                expression.SetWeight(ExpressionKey.Sad, 0.0f);
                expression.SetWeight(ExpressionKey.Relaxed, 0.0f);
                expression.SetWeight(ExpressionKey.Surprised, 0.0f);
                expression.SetWeight(ExpressionKey.Aa, 0.0f);
                expression.SetWeight(ExpressionKey.Ih, 0.0f);
                expression.SetWeight(ExpressionKey.Ou, 0.0f);
                expression.SetWeight(ExpressionKey.Ee, 0.0f);
                expression.SetWeight(ExpressionKey.Oh, 0.0f);
            }
            _state = null;
            _postureOwnedPoseLastFrame = false;
            _sourcePostureOffsetsOwnedLastFrame = false;
            _locomotionPoseOwnedLastFrame = false;
            _locomotionArmPoseOwnedLastFrame = false;
            RealizationFrameCount = 0;
            MotionRealized = false;
            ExpressionRealized = false;
            GestureRealized = false;
            GazeRealized = false;
            PostureRealized = false;
            LocomotionRealized = false;
            SpeechTimingRealized = false;
        }
    }
}
