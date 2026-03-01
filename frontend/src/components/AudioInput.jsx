/**
 * AudioInput.jsx — Speech-to-text voice input for the LLM Council query box.
 *
 * Uses the Web Speech API (SpeechRecognition) which is natively supported in
 * Chrome, Edge, and Safari.  Zero external dependencies — no Azure Speech
 * resource or npm package required.
 *
 * Design:
 *   - Toggle mic button sits in the input toolbar alongside 📎 🌐 ⚡
 *   - Continuous recognition: finalized phrases are appended to the textarea
 *   - Interim (live) transcript shown below mic for immediate visual feedback
 *   - Auto-restart on unexpected end (browser caps continuous segments)
 *   - Auto-stop safety timeout after 3 minutes
 *   - Accessible: role="switch", aria-checked, keyboard-operable
 *   - Graceful degradation: component returns null if API unavailable
 *
 * Enhancement path: swap in `microsoft-cognitiveservices-speech-sdk` by
 * replacing the recognition setup in startListening() — the external
 * contract (onTranscript callback) stays identical.
 */

import { useState, useRef, useCallback, useEffect } from 'react';

/* ── Browser feature detection ──────────────────────────────── */
const SpeechRecognition =
  typeof window !== 'undefined'
    ? window.SpeechRecognition || window.webkitSpeechRecognition
    : null;

/** Maximum continuous listening before auto-stop (ms). */
const AUTO_STOP_TIMEOUT = 3 * 60 * 1000; // 3 minutes

/**
 * @param {Object}   props
 * @param {function} props.onTranscript  – called with (finalText: string) to append to input
 * @param {boolean}  props.disabled      – mirrors the textarea disabled state
 * @param {string}   [props.lang]        – BCP-47 language tag (default: browser locale)
 */
export default function AudioInput({ onTranscript, disabled, lang }) {
  const [isListening, setIsListening] = useState(false);
  const [interimText, setInterimText] = useState('');
  const [permError, setPermError] = useState(null);

  const recognitionRef  = useRef(null);
  const isListeningRef  = useRef(false);
  const autoStopTimer   = useRef(null);
  const onTranscriptRef = useRef(onTranscript);

  /* Always keep ref current — avoids stale closure in recognition callbacks */
  useEffect(() => { onTranscriptRef.current = onTranscript; }, [onTranscript]);

  /* Keep ref in sync for use inside recognition callbacks */
  useEffect(() => { isListeningRef.current = isListening; }, [isListening]);

  /* Cleanup on unmount */
  useEffect(() => {
    return () => {
      clearTimeout(autoStopTimer.current);
      if (recognitionRef.current) {
        try { recognitionRef.current.abort(); } catch { /* noop */ }
        recognitionRef.current = null;
      }
    };
  }, []);

  /* ── Stop ─────────────────────────────────────────────────── */
  const stopListening = useCallback(() => {
    clearTimeout(autoStopTimer.current);
    if (recognitionRef.current) {
      try { recognitionRef.current.stop(); } catch { /* noop */ }
      recognitionRef.current = null;
    }
    setIsListening(false);
    setInterimText('');
  }, []);

  /* ── Start ────────────────────────────────────────────────── */
  const startListening = useCallback(() => {
    if (!SpeechRecognition) return;
    setPermError(null);
    setInterimText('');

    // Abort any lingering session
    if (recognitionRef.current) {
      try { recognitionRef.current.abort(); } catch { /* noop */ }
    }

    const recognition = new SpeechRecognition();
    recognition.continuous       = true;
    recognition.interimResults   = true;
    recognition.lang             = lang || navigator.language || 'en-US';
    recognition.maxAlternatives  = 1;

    recognition.onstart = () => setIsListening(true);

    recognition.onresult = (event) => {
      let finalText = '';
      let interim = '';
      for (let i = event.resultIndex; i < event.results.length; i++) {
        const transcript = event.results[i][0].transcript;
        if (event.results[i].isFinal) {
          finalText += transcript;
        } else {
          interim += transcript;
        }
      }
      // Show interim text as live preview
      setInterimText(interim);
      // Commit finalized speech to the textarea
      if (finalText.trim()) {
        onTranscriptRef.current(finalText.trim());
        setInterimText('');
      }
    };

    recognition.onerror = (event) => {
      console.warn('[AudioInput] SpeechRecognition error:', event.error);
      if (event.error === 'not-allowed' || event.error === 'service-not-allowed') {
        setPermError('Microphone access denied — please allow in browser settings');
        stopListening();
      } else if (event.error === 'network') {
        setPermError('Speech service unreachable — check network/proxy settings');
        stopListening();
      } else if (event.error !== 'no-speech' && event.error !== 'aborted') {
        stopListening();
      }
      // 'no-speech' and 'aborted' are non-fatal — auto-restart handles them
    };

    recognition.onend = () => {
      // Continuous mode can end unexpectedly (browser caps ~60 s per segment).
      // Auto-restart if we're still in "listening" mode.
      if (isListeningRef.current && recognitionRef.current === recognition) {
        try {
          recognition.start();
        } catch {
          setIsListening(false);
          setInterimText('');
          recognitionRef.current = null;
        }
      } else {
        setIsListening(false);
        setInterimText('');
        recognitionRef.current = null;
      }
    };

    recognitionRef.current = recognition;

    try {
      recognition.start();
      // Safety auto-stop
      clearTimeout(autoStopTimer.current);
      autoStopTimer.current = setTimeout(() => {
        if (isListeningRef.current) stopListening();
      }, AUTO_STOP_TIMEOUT);
    } catch (err) {
      console.error('[AudioInput] Failed to start recognition:', err);
      setIsListening(false);
    }
  }, [lang, stopListening]);

  /* ── Toggle ───────────────────────────────────────────────── */
  const toggle = useCallback(() => {
    if (isListening) stopListening();
    else startListening();
  }, [isListening, startListening, stopListening]);

  /* ── Render nothing if browser lacks support ──────────────── */
  if (!SpeechRecognition) return null;

  return (
    <div className="audio-input-wrapper">
      <button
        type="button"
        className={`audio-input-btn ${isListening ? 'active' : ''}`}
        onClick={toggle}
        disabled={disabled}
        title={
          isListening
            ? 'Listening… click to stop'
            : 'Voice input — click to speak your query'
        }
        aria-label={isListening ? 'Stop voice input' : 'Start voice input'}
        role="switch"
        aria-checked={isListening}
      >
        🎙️
      </button>
      {isListening && (
        <span className="audio-listening-badge" aria-live="polite">
          {interimText || 'Listening…'}
        </span>
      )}
      {permError && (
        <span className="audio-perm-error" role="alert">
          {permError}
        </span>
      )}
    </div>
  );
}
