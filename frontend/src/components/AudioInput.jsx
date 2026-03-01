/**
 * AudioInput.jsx — Speech-to-text voice input for the LLM Council query box.
 *
 * **Primary engine**: Azure Cognitive Services Speech SDK (S0 Standard tier).
 *   - Routes audio via wss://{region}.stt.speech.microsoft.com
 *   - Works behind corporate proxies (Bayer/Zscaler) that block Google endpoints
 *   - Token fetched from backend /api/speech/token (short-lived, 10-min TTL)
 *   - SDK loaded dynamically on first mic click (~500 KB, cached after first load)
 *
 * **Fallback**: Browser Web Speech API (SpeechRecognition).
 *   - Activates only if Azure Speech token endpoint returns error/unavailable.
 *   - Known limitation: Chrome routes audio to Google servers — fails behind
 *     corporate TLS-intercepting proxies.
 *
 * Design:
 *   - Toggle mic button sits in the input toolbar alongside 📎 🌐 ⚡
 *   - Continuous recognition: finalized phrases are appended to the textarea
 *   - Interim (live) transcript shown below mic for immediate visual feedback
 *   - Auto-stop safety timeout after 3 minutes
 *   - Accessible: role="switch", aria-checked, keyboard-operable
 *   - Graceful degradation: component renders mic button always — engine
 *     selection happens on first click.
 */

import { useState, useRef, useCallback, useEffect } from 'react';
import { api } from '../api';

/* ── Browser feature detection (fallback only) ──────────────── */
const BrowserSpeechRecognition =
  typeof window !== 'undefined'
    ? window.SpeechRecognition || window.webkitSpeechRecognition
    : null;

/** Maximum continuous listening before auto-stop (ms). */
const AUTO_STOP_TIMEOUT = 3 * 60 * 1000; // 3 minutes

/** Azure token refresh — refresh at 9 min (tokens last 10 min). */
const TOKEN_REFRESH_MS = 9 * 60 * 1000;

/**
 * @param {Object}   props
 * @param {function} props.onTranscript  – called with (finalText: string) to append to input
 * @param {boolean}  props.disabled      – mirrors the textarea disabled state
 * @param {string}   [props.lang]        – BCP-47 language tag (default: 'en-US')
 */
export default function AudioInput({ onTranscript, disabled, lang }) {
  const [isListening, setIsListening] = useState(false);
  const [interimText, setInterimText] = useState('');
  const [permError, setPermError] = useState(null);
  const [engineLabel, setEngineLabel] = useState(''); // 'azure' | 'browser' | ''

  const recognizerRef   = useRef(null);  // Azure SpeechRecognizer OR browser SpeechRecognition
  const isListeningRef  = useRef(false);
  const autoStopTimer   = useRef(null);
  const onTranscriptRef = useRef(onTranscript);
  const sdkRef          = useRef(null);  // Cached Speech SDK module
  const tokenRef        = useRef(null);  // { token, region, fetchedAt }
  const engineRef       = useRef('');    // 'azure' | 'browser'
  const interimRef      = useRef('');    // Track interim text for commit-on-stop

  /* Always keep callback ref current — avoids stale closure */
  useEffect(() => { onTranscriptRef.current = onTranscript; }, [onTranscript]);
  useEffect(() => { isListeningRef.current = isListening; }, [isListening]);

  /* Cleanup on unmount */
  useEffect(() => {
    return () => {
      clearTimeout(autoStopTimer.current);
      _cleanupRef.current();
    };
  }, []);

  /** Dispose whatever recognizer is active */
  const _cleanup = useCallback(() => {
    const rec = recognizerRef.current;
    if (!rec) return;
    try {
      if (engineRef.current === 'azure') {
        rec.stopContinuousRecognitionAsync?.(() => {}, () => {});
        setTimeout(() => { try { rec.close(); } catch { /* noop */ } }, 200);
      } else {
        rec.abort?.();
      }
    } catch { /* noop */ }
    recognizerRef.current = null;
  }, []);

  // Stable ref for cleanup (avoids stale closure in unmount effect)
  const _cleanupRef = useRef(_cleanup);
  useEffect(() => { _cleanupRef.current = _cleanup; }, [_cleanup]);

  /* ── Fetch / refresh Azure Speech token ───────────────────── */
  const _getToken = useCallback(async () => {
    if (tokenRef.current && (Date.now() - tokenRef.current.fetchedAt) < TOKEN_REFRESH_MS) {
      return tokenRef.current;
    }
    const data = await api.getSpeechToken();
    if (data?.token && data?.region) {
      tokenRef.current = { ...data, fetchedAt: Date.now() };
      return tokenRef.current;
    }
    tokenRef.current = null;
    return null;
  }, []);

  /* ── Load Azure Speech SDK (dynamic import — code-split) ─── */
  const _loadSDK = useCallback(async () => {
    if (sdkRef.current) return sdkRef.current;
    try {
      const sdk = await import('microsoft-cognitiveservices-speech-sdk');
      sdkRef.current = sdk;
      return sdk;
    } catch (err) {
      console.warn('[AudioInput] Failed to load Azure Speech SDK:', err);
      return null;
    }
  }, []);

  /* ── Stop listening ───────────────────────────────────────── */
  const stopListening = useCallback(() => {
    clearTimeout(autoStopTimer.current);

    // Commit any uncommitted interim text before stopping
    if (interimRef.current.trim()) {
      onTranscriptRef.current(interimRef.current.trim());
      interimRef.current = '';
    }

    _cleanup();
    setIsListening(false);
    setInterimText('');
  }, [_cleanup]);

  /* ── Start with Azure Speech SDK ──────────────────────────── */
  const _startAzure = useCallback(async () => {
    const tokenData = await _getToken();
    if (!tokenData) return false;

    const sdk = await _loadSDK();
    if (!sdk) return false;

    try {
      const speechConfig = sdk.SpeechConfig.fromAuthorizationToken(
        tokenData.token,
        tokenData.region,
      );
      speechConfig.speechRecognitionLanguage = lang || 'en-US';
      speechConfig.setProperty(
        sdk.PropertyId.SpeechServiceResponse_RequestSentenceBoundary,
        'true',
      );

      const audioConfig = sdk.AudioConfig.fromDefaultMicrophoneInput();
      const recognizer = new sdk.SpeechRecognizer(speechConfig, audioConfig);

      /* Interim results */
      recognizer.recognizing = (_sender, event) => {
        if (event.result.text) {
          interimRef.current = event.result.text;
          setInterimText(event.result.text);
        }
      };

      /* Final (committed) result */
      recognizer.recognized = (_sender, event) => {
        if (event.result.reason === sdk.ResultReason.RecognizedSpeech && event.result.text?.trim()) {
          onTranscriptRef.current(event.result.text.trim());
          interimRef.current = '';
          setInterimText('');
        }
      };

      /* Handle cancellation / errors */
      recognizer.canceled = (_sender, event) => {
        if (event.reason === sdk.CancellationReason.Error) {
          console.warn('[AudioInput] Azure Speech error:', event.errorCode, event.errorDetails);
          if (event.errorCode === sdk.CancellationErrorCode.ConnectionFailure) {
            setPermError('Speech service connection failed — check network');
          }
        }
        stopListening();
      };

      recognizer.sessionStopped = () => {
        if (isListeningRef.current) stopListening();
      };

      // Start continuous recognition
      await new Promise((resolve, reject) => {
        recognizer.startContinuousRecognitionAsync(resolve, reject);
      });

      recognizerRef.current = recognizer;
      engineRef.current = 'azure';
      setEngineLabel('azure');
      setIsListening(true);
      return true;
    } catch (err) {
      console.warn('[AudioInput] Azure Speech start failed:', err);
      return false;
    }
  }, [lang, _getToken, _loadSDK, stopListening]);

  /* ── Start with browser Web Speech API (fallback) ─────────── */
  const _startBrowser = useCallback(() => {
    if (!BrowserSpeechRecognition) return false;

    try {
      const recognition = new BrowserSpeechRecognition();
      recognition.continuous      = true;
      recognition.interimResults  = true;
      recognition.lang            = lang || navigator.language || 'en-US';
      recognition.maxAlternatives = 1;

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
        interimRef.current = interim;
        setInterimText(interim);
        if (finalText.trim()) {
          onTranscriptRef.current(finalText.trim());
          interimRef.current = '';
          setInterimText('');
        }
      };

      recognition.onerror = (event) => {
        console.warn('[AudioInput] Browser SpeechRecognition error:', event.error);
        if (event.error === 'not-allowed' || event.error === 'service-not-allowed') {
          setPermError('Microphone access denied — please allow in browser settings');
          stopListening();
        } else if (event.error === 'network') {
          setPermError('Speech service unreachable — corporate proxy may block Google endpoints');
          stopListening();
        } else if (event.error !== 'no-speech' && event.error !== 'aborted') {
          stopListening();
        }
      };

      recognition.onend = () => {
        if (isListeningRef.current && recognizerRef.current === recognition) {
          try { recognition.start(); } catch { stopListening(); }
        }
      };

      recognizerRef.current = recognition;
      engineRef.current = 'browser';
      setEngineLabel('browser');
      recognition.start();
      setIsListening(true);
      return true;
    } catch (err) {
      console.error('[AudioInput] Browser speech start failed:', err);
      return false;
    }
  }, [lang, stopListening]);

  /* ── Start listening (Azure first → browser fallback) ─────── */
  const startListening = useCallback(async () => {
    setPermError(null);
    setInterimText('');
    interimRef.current = '';

    // Abort any lingering session
    _cleanup();

    // Try Azure Speech SDK first (works behind corporate proxy)
    const azureOk = await _startAzure();
    if (azureOk) {
      console.info('[AudioInput] ✅ Using Azure Speech SDK (S0 Standard)');
    } else {
      // Fallback to browser Web Speech API
      const browserOk = _startBrowser();
      if (browserOk) {
        console.info('[AudioInput] ⚠️ Falling back to browser Web Speech API');
      } else {
        setPermError('No speech engine available — microphone may not be supported');
        return;
      }
    }

    // Safety auto-stop
    clearTimeout(autoStopTimer.current);
    autoStopTimer.current = setTimeout(() => {
      if (isListeningRef.current) stopListening();
    }, AUTO_STOP_TIMEOUT);
  }, [_cleanup, _startAzure, _startBrowser, stopListening]);

  /* ── Toggle ───────────────────────────────────────────────── */
  const toggle = useCallback(() => {
    if (isListening) stopListening();
    else startListening();
  }, [isListening, startListening, stopListening]);

  /* Always render mic button — engine selection happens on click */
  return (
    <div className="audio-input-wrapper">
      <button
        type="button"
        className={`audio-input-btn ${isListening ? 'active' : ''}`}
        onClick={toggle}
        disabled={disabled}
        title={
          isListening
            ? `Listening (${engineLabel || 'initializing'})… click to stop`
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
          {interimText || `Listening (${engineLabel})…`}
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
