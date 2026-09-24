import { useState, useRef, useCallback } from 'react';
import { ASR_PROVIDERS } from '@/lib/audio/constants';
import type { ASRProviderId } from '@/lib/audio/types';
import { normalizeASRUploadAudio } from '@/lib/audio/wav-utils';
import { createLogger } from '@/lib/logger';

const log = createLogger('AudioRecorder');

// Window.SpeechRecognition / webkitSpeechRecognition are declared globally by
// @assistant-ui/core's speech adapter; re-augmenting them here as `any` conflicts
// with that typing, so we rely on the global declaration and cast the instance.

export interface UseAudioRecorderOptions {
  onTranscription?: (text: string) => void;
  /** Receives the latest full transcript while recording is still active. */
  onInterimTranscription?: (text: string) => void;
  onError?: (error: string) => void;
  /** When true and using browser-native ASR, recognition stays active until explicitly stopped. */
  continuous?: boolean;
}

export function useAudioRecorder(options: UseAudioRecorderOptions = {}) {
  const { onTranscription, onInterimTranscription, onError, continuous = false } = options;

  const [isRecording, setIsRecording] = useState(false);
  const [isProcessing, setIsProcessing] = useState(false);
  const [recordingTime, setRecordingTime] = useState(0);

  const mediaRecorderRef = useRef<MediaRecorder | null>(null);
  const audioChunksRef = useRef<Blob[]>([]);
  const timerRef = useRef<NodeJS.Timeout | null>(null);
  // eslint-disable-next-line @typescript-eslint/no-explicit-any -- Web Speech API not typed
  const speechRecognitionRef = useRef<any>(null);
  // Synchronous lock to prevent rapid re-entry (React state updates are async)
  const busyRef = useRef(false);
  const liveProcessingRef = useRef(false);
  const transcriptionSequenceRef = useRef(0);

  // Send audio to server for transcription
  const transcribeAudio = useCallback(
    async (audioBlob: Blob, interim = false) => {
      const sequence = ++transcriptionSequenceRef.current;
      if (!interim) setIsProcessing(true);

      try {
        const formData = new FormData();

        // Get current ASR configuration from settings store
        // Note: This requires importing useSettingsStore in browser context
        if (typeof window !== 'undefined') {
          const { useSettingsStore } = await import('@/lib/store/settings');
          const { asrProviderId, asrLanguage, asrProvidersConfig } = useSettingsStore.getState();
          const uploadAudio = await normalizeASRUploadAudio(asrProviderId, audioBlob);
          formData.append('audio', uploadAudio.blob, uploadAudio.fileName);

          formData.append('providerId', asrProviderId);
          formData.append(
            'modelId',
            asrProvidersConfig?.[asrProviderId]?.modelId ||
              ASR_PROVIDERS[asrProviderId as keyof typeof ASR_PROVIDERS]?.defaultModelId ||
              '',
          );
          formData.append('language', asrLanguage);

          // Append API key and base URL if configured
          const providerConfig = asrProvidersConfig?.[asrProviderId];
          if (providerConfig?.apiKey?.trim()) {
            formData.append('apiKey', providerConfig.apiKey);
          }
          const effectiveBaseUrl =
            providerConfig?.baseUrl?.trim() || providerConfig?.customDefaultBaseUrl || '';
          if (effectiveBaseUrl) {
            formData.append('baseUrl', effectiveBaseUrl);
          }
        } else {
          formData.append('audio', audioBlob, 'recording.webm');
        }

        const response = await fetch('/api/transcription', {
          method: 'POST',
          body: formData,
        });

        if (!response.ok) {
          const error = await response.json();
          throw new Error(error.error || 'Transcription failed');
        }

        const result = await response.json();
        if (result.text) {
          if (interim) {
            if (sequence === transcriptionSequenceRef.current) {
              onInterimTranscription?.(result.text);
            }
          } else {
            onTranscription?.(result.text);
          }
        }
      } catch (error) {
        log.error('Transcription error:', error);
        onError?.(error instanceof Error ? error.message : '语音识别失败，请重试');
      } finally {
        if (!interim) {
          setIsProcessing(false);
          setRecordingTime(0);
        }
      }
    },
    [onTranscription, onInterimTranscription, onError],
  );

  // Start recording
  const startRecording = useCallback(async () => {
    // Synchronous lock — React state is async so isRecording may be stale
    if (busyRef.current) return;
    busyRef.current = true;
    try {
      // Get current ASR configuration
      if (typeof window !== 'undefined') {
        const { useSettingsStore } = await import('@/lib/store/settings');
        const settings = useSettingsStore.getState();
        let { asrProviderId } = settings;
        const { asrLanguage } = settings;

        // Prefer a managed server ASR when available. Browser-native recognition
        // depends on a vendor network service and frequently reports `network`
        // on restricted/campus networks even though microphone access works.
        if (asrProviderId === 'browser-native') {
          try {
            const response = await fetch('/api/server-providers');
            if (response.ok) {
              const payload = (await response.json()) as { asr?: Record<string, unknown> };
              const managedProviderId = Object.keys(payload.asr || {})[0] as
                | ASRProviderId
                | undefined;
              if (managedProviderId) {
                settings.setASRProvider(managedProviderId);
                settings.setASREnabled(true);
                asrProviderId = managedProviderId;
              }
            }
          } catch (providerError) {
            log.warn('Unable to resolve managed ASR provider:', providerError);
          }
        }

        // Use browser native ASR if configured
        if (asrProviderId === 'browser-native') {
          // Check if Speech Recognition is supported
          if (!window.SpeechRecognition && !window.webkitSpeechRecognition) {
            onError?.('您的浏览器不支持语音识别功能');
            return;
          }

          const SpeechRecognitionCtor = (window.SpeechRecognition ||
            window.webkitSpeechRecognition)!;
          // eslint-disable-next-line @typescript-eslint/no-explicit-any -- Web Speech API instance shape isn't in lib.dom
          const recognition: any = new SpeechRecognitionCtor();

          recognition.lang = asrLanguage === 'zh' ? 'zh-CN' : asrLanguage || 'zh-CN';
          recognition.continuous = continuous;
          recognition.interimResults = continuous;

          recognition.onstart = () => {
            setIsRecording(true);
            setRecordingTime(0);

            // Start timer
            timerRef.current = setInterval(() => {
              setRecordingTime((prev) => prev + 1);
            }, 1000);
          };

          recognition.onresult = (event: {
            resultIndex: number;
            results: {
              [index: number]: {
                isFinal: boolean;
                [index: number]: { transcript: string };
              };
              length: number;
            };
          }) => {
            let finalTranscript = '';
            let interimTranscript = '';
            for (let i = event.resultIndex; i < event.results.length; i++) {
              const result = event.results[i];
              if (result[0]?.transcript) {
                if (result.isFinal) finalTranscript += result[0].transcript;
                else interimTranscript += result[0].transcript;
              }
            }
            if (interimTranscript) onInterimTranscription?.(interimTranscript);
            if (finalTranscript) onTranscription?.(finalTranscript);
          };

          recognition.onerror = (event: { error: string }) => {
            if (event.error === 'network' || event.error === 'no-speech') {
              log.warn('Speech recognition unavailable:', event.error);
            } else {
              log.error('Speech recognition error:', event.error);
            }
            let errorMessage = '语音识别失败';

            switch (event.error) {
              case 'aborted':
                // Non-fatal: caused by our own cancel/stop logic or rapid toggle
                busyRef.current = false;
                setIsRecording(false);
                setRecordingTime(0);
                if (timerRef.current) {
                  clearInterval(timerRef.current);
                  timerRef.current = null;
                }
                return;
              case 'no-speech':
                errorMessage = '未检测到语音输入';
                break;
              case 'audio-capture':
                errorMessage = '无法访问麦克风';
                break;
              case 'not-allowed':
                errorMessage = '麦克风权限被拒绝';
                break;
              case 'network':
                errorMessage = '浏览器语音服务网络不可用，请检查网络或在设置中配置服务器 ASR';
                void (async () => {
                  try {
                    const response = await fetch('/api/server-providers');
                    if (!response.ok) return;
                    const payload = (await response.json()) as {
                      asr?: Record<string, unknown>;
                    };
                    const fallbackProviderId = Object.keys(payload.asr || {})[0];
                    if (!fallbackProviderId) return;

                    const { useSettingsStore } = await import('@/lib/store/settings');
                    const settings = useSettingsStore.getState();
                    settings.setASRProvider(fallbackProviderId as ASRProviderId);
                    settings.setASREnabled(true);
                    onError?.('浏览器语音服务不可用，已切换到服务器语音识别，请再次点击麦克风');
                  } catch (fallbackError) {
                    log.warn('Unable to activate server ASR fallback:', fallbackError);
                  }
                })();
                break;
              default:
                errorMessage = `语音识别错误: ${event.error}`;
            }

            onError?.(errorMessage);
            busyRef.current = false;
            setIsRecording(false);
            setRecordingTime(0);
            if (timerRef.current) {
              clearInterval(timerRef.current);
              timerRef.current = null;
            }
          };

          recognition.onend = () => {
            busyRef.current = false;
            setIsRecording(false);
            setRecordingTime(0);
            if (timerRef.current) {
              clearInterval(timerRef.current);
              timerRef.current = null;
            }
          };

          recognition.start();
          speechRecognitionRef.current = recognition;
          return;
        }
      }

      // Use MediaRecorder for server-side ASR
      // Request microphone permission
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });

      // Create MediaRecorder
      const mediaRecorder = new MediaRecorder(stream, {
        mimeType: 'audio/webm',
      });

      mediaRecorderRef.current = mediaRecorder;
      audioChunksRef.current = [];

      mediaRecorder.ondataavailable = (event) => {
        if (event.data.size > 0) {
          audioChunksRef.current.push(event.data);
          if (continuous && mediaRecorder.state === 'recording' && !liveProcessingRef.current) {
            liveProcessingRef.current = true;
            const currentAudio = new Blob([...audioChunksRef.current], { type: 'audio/webm' });
            void transcribeAudio(currentAudio, true).finally(() => {
              liveProcessingRef.current = false;
            });
          }
        }
      };

      mediaRecorder.onstop = async () => {
        // Stop all audio tracks
        stream.getTracks().forEach((track) => track.stop());

        // Merge audio chunks
        const audioBlob = new Blob(audioChunksRef.current, {
          type: 'audio/webm',
        });

        // Send to server for transcription
        await transcribeAudio(audioBlob);
        busyRef.current = false;
      };

      // Start recording
      if (continuous) mediaRecorder.start(3000);
      else mediaRecorder.start();
      setIsRecording(true);
      setRecordingTime(0);

      // Start timer
      timerRef.current = setInterval(() => {
        setRecordingTime((prev) => prev + 1);
      }, 1000);
    } catch (error) {
      busyRef.current = false;
      log.error('Failed to start recording:', error);
      onError?.('无法访问麦克风，请检查权限设置');
    }
  }, [onTranscription, onInterimTranscription, onError, transcribeAudio, continuous]);

  // Stop recording
  const stopRecording = useCallback(() => {
    // Stop Speech Recognition if active
    if (speechRecognitionRef.current) {
      speechRecognitionRef.current.stop();
      speechRecognitionRef.current = null;
      busyRef.current = false;
      setIsRecording(false);
      if (timerRef.current) {
        clearInterval(timerRef.current);
        timerRef.current = null;
      }
      return;
    }

    // Stop MediaRecorder if active
    if (mediaRecorderRef.current && isRecording) {
      mediaRecorderRef.current.stop();
      busyRef.current = false;
      setIsRecording(false);

      if (timerRef.current) {
        clearInterval(timerRef.current);
        timerRef.current = null;
      }
    }
  }, [isRecording]);

  // Cancel recording
  const cancelRecording = useCallback(() => {
    // Cancel Speech Recognition if active
    if (speechRecognitionRef.current) {
      speechRecognitionRef.current.onresult = null; // Prevent transcription callback
      speechRecognitionRef.current.onerror = null; // Suppress browser abort error events
      speechRecognitionRef.current.stop();
      speechRecognitionRef.current = null;
      busyRef.current = false;
      setIsRecording(false);
      setRecordingTime(0);
      if (timerRef.current) {
        clearInterval(timerRef.current);
        timerRef.current = null;
      }
      return;
    }

    // Cancel MediaRecorder if active
    if (mediaRecorderRef.current && isRecording) {
      // Stop recording without transcription
      mediaRecorderRef.current.ondataavailable = null;
      mediaRecorderRef.current.onstop = null;
      mediaRecorderRef.current.stop();

      // Stop all audio tracks
      if (mediaRecorderRef.current.stream) {
        mediaRecorderRef.current.stream.getTracks().forEach((track) => track.stop());
      }

      busyRef.current = false;
      setIsRecording(false);
      setRecordingTime(0);

      if (timerRef.current) {
        clearInterval(timerRef.current);
        timerRef.current = null;
      }

      audioChunksRef.current = [];
    }
  }, [isRecording]);

  return {
    isRecording,
    isProcessing,
    recordingTime,
    startRecording,
    stopRecording,
    cancelRecording,
  };
}
