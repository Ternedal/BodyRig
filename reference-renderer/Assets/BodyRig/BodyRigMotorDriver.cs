using System;
using UnityEngine;

namespace BodyRig.ReferenceRenderer
{
    /// <summary>
    /// Reference-only renderer for BodyRig Motor State v1 and v2.
    ///
    /// It consumes already-personalized performed amplitudes from BodyRig. It
    /// does not reinterpret ModelRig BodyCue semantics, read BodyPrint itself,
    /// or multiply v2 observed embodiment evidence into performed values a
    /// second time.
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
            public GestureState gesture;
            public GazeState gaze;
            public SpeechState speech;
            public EmbodimentState embodiment;
        }

        [SerializeField] private BodyRigAvatarLoader avatarLoader;
        [SerializeField] private Transform userGazeTarget;
        [SerializeField, Range(0.01f, 1.0f)] private float smoothingSeconds = 0.12f;

        private Animator _boundAnimator;
        private Transform _head;
        private Transform _leftShoulder;
        private Transform _rightShoulder;
        private Quaternion _headBaseRotation;
        private Vector3 _leftShoulderBasePosition;
        private Vector3 _rightShoulderBasePosition;
        private MotorState _state;
        private float _gestureAmplitude;
        private float _headMotion;
        private float _gazeStrength;
        private float _speechAmplitude;

        public void ApplyMotorJson(string json)
        {
            if (string.IsNullOrWhiteSpace(json))
            {
                throw new ArgumentException("BodyRig motor JSON is required", nameof(json));
            }

            var next = JsonUtility.FromJson<MotorState>(json);
            if (next == null || next.type != "bodyrig-motor-state" || (next.version != 1 && next.version != 2))
            {
                throw new ArgumentException("Unsupported BodyRig Motor State", nameof(json));
            }
            if (string.IsNullOrWhiteSpace(next.body_id) || string.IsNullOrWhiteSpace(next.utterance_id) || next.motion == null)
            {
                throw new ArgumentException("Incomplete BodyRig Motor State", nameof(json));
            }
            if (next.version == 1 && next.embodiment != null)
            {
                throw new ArgumentException("Motor State v1 may not carry v2 embodiment evidence", nameof(json));
            }
            if (next.version == 2 && next.embodiment != null)
            {
                if (next.embodiment.source != ObservedEmbodimentSource || next.embodiment.observed == null)
                {
                    throw new ArgumentException("Unsupported BodyRig embodiment evidence", nameof(json));
                }
                ValidateObservedEmbodiment(next.embodiment.observed);
            }

            Validate01(next.motion.energy, "motion.energy");
            Validate01(next.motion.head_motion, "motion.head_motion");
            if (next.gesture != null)
            {
                Validate01(next.gesture.amplitude, "gesture.amplitude");
            }
            if (next.gaze != null)
            {
                Validate01(next.gaze.strength, "gaze.strength");
            }
            if (next.speech != null)
            {
                Validate01(next.speech.amplitude, "speech.amplitude");
            }

            _state = next;
        }

        private static void ValidateObservedEmbodiment(ObservedEmbodimentState observed)
        {
            Validate01(observed.energy, "embodiment.observed.energy");
            Validate01(observed.gesture_frequency, "embodiment.observed.gesture_frequency");
            Validate01(observed.gesture_amplitude, "embodiment.observed.gesture_amplitude");
            Validate01(observed.head_motion, "embodiment.observed.head_motion");
            Validate01(observed.turn_speed, "embodiment.observed.turn_speed");
            ValidateRange(observed.walk_cadence_spm, 0.0f, 300.0f, "embodiment.observed.walk_cadence_spm");
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

        private void LateUpdate()
        {
            BindAvatarIfNeeded();
            if (_boundAnimator == null || _state == null)
            {
                return;
            }

            var dt = Mathf.Max(Time.unscaledDeltaTime, 0.0001f);
            var blend = 1.0f - Mathf.Exp(-dt / Mathf.Max(smoothingSeconds, 0.01f));

            // The performed fields below are already resolved against BodyPrint
            // by BodyRig. v2 embodiment is evidence/provenance for consumers; it
            // is deliberately not multiplied into these values again here.
            var targetGesture = _state.gesture != null && _state.gesture.id == "small_shrug"
                ? _state.gesture.amplitude
                : 0.0f;
            var targetHead = _state.motion != null ? _state.motion.head_motion : 0.0f;
            var targetGaze = _state.gaze != null ? _state.gaze.strength : 0.0f;
            var targetSpeech = _state.speech != null ? _state.speech.amplitude : 0.0f;

            _gestureAmplitude = Mathf.Lerp(_gestureAmplitude, targetGesture, blend);
            _headMotion = Mathf.Lerp(_headMotion, targetHead, blend);
            _gazeStrength = Mathf.Lerp(_gazeStrength, targetGaze, blend);
            _speechAmplitude = Mathf.Lerp(_speechAmplitude, targetSpeech, blend);

            ApplyShrug();
            ApplyHeadMotionAndGaze();
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
            _leftShoulder = null;
            _rightShoulder = null;
            _gestureAmplitude = 0.0f;
            _headMotion = 0.0f;
            _gazeStrength = 0.0f;
            _speechAmplitude = 0.0f;

            if (_boundAnimator == null)
            {
                return;
            }

            _head = _boundAnimator.GetBoneTransform(HumanBodyBones.Head);
            _leftShoulder = _boundAnimator.GetBoneTransform(HumanBodyBones.LeftShoulder)
                ?? _boundAnimator.GetBoneTransform(HumanBodyBones.LeftUpperArm);
            _rightShoulder = _boundAnimator.GetBoneTransform(HumanBodyBones.RightShoulder)
                ?? _boundAnimator.GetBoneTransform(HumanBodyBones.RightUpperArm);

            if (_head != null)
            {
                _headBaseRotation = _head.localRotation;
            }
            if (_leftShoulder != null)
            {
                _leftShoulderBasePosition = _leftShoulder.localPosition;
            }
            if (_rightShoulder != null)
            {
                _rightShoulderBasePosition = _rightShoulder.localPosition;
            }
        }

        private void ApplyShrug()
        {
            // Reference implementation only: a semantic small_shrug is rendered
            // as a bounded local shoulder lift. The personal amplitude has
            // already been resolved by BodyRig.
            var lift = 0.025f * _gestureAmplitude;
            if (_leftShoulder != null)
            {
                _leftShoulder.localPosition = _leftShoulderBasePosition + Vector3.up * lift;
            }
            if (_rightShoulder != null)
            {
                _rightShoulder.localPosition = _rightShoulderBasePosition + Vector3.up * lift;
            }
        }

        private void ApplyHeadMotionAndGaze()
        {
            if (_head == null)
            {
                return;
            }

            var t = Time.unscaledTime;
            var speechBoost = 1.0f + 0.35f * _speechAmplitude;
            var microYaw = Mathf.Sin(t * 1.13f) * 2.0f * _headMotion * speechBoost;
            var microPitch = Mathf.Sin(t * 1.71f + 0.7f) * 1.2f * _headMotion * speechBoost;
            var targetRotation = _headBaseRotation * Quaternion.Euler(microPitch, microYaw, 0.0f);

            if (_state.gaze != null && _state.gaze.target == "user" && userGazeTarget != null && _head.parent != null)
            {
                var direction = userGazeTarget.position - _head.position;
                if (direction.sqrMagnitude > 0.000001f)
                {
                    var worldLook = Quaternion.LookRotation(direction.normalized, Vector3.up);
                    var localLook = Quaternion.Inverse(_head.parent.rotation) * worldLook;
                    targetRotation = Quaternion.Slerp(targetRotation, localLook, Mathf.Clamp01(_gazeStrength * 0.65f));
                }
            }

            _head.localRotation = Quaternion.Slerp(_head.localRotation, targetRotation, 0.35f);
        }
    }
}
