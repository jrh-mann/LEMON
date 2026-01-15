import { useState, useRef, useCallback, useEffect } from 'react'

interface UseVoiceInputOptions {
  onTranscript?: (text: string) => void
  onInterimTranscript?: (text: string) => void
}

interface UseVoiceInputReturn {
  isListening: boolean
  isSupported: boolean
  volume: number // 0-1 normalized volume level
  transcript: string
  startListening: () => void
  stopListening: () => void
  toggleListening: () => void
}

// Extend Window interface for webkit prefix
interface WindowWithSpeech extends Window {
  webkitSpeechRecognition?: typeof SpeechRecognition
  SpeechRecognition?: typeof SpeechRecognition
}

export function useVoiceInput(options: UseVoiceInputOptions = {}): UseVoiceInputReturn {
  const { onTranscript, onInterimTranscript } = options

  const [isListening, setIsListening] = useState(false)
  const [volume, setVolume] = useState(0)
  const [transcript, setTranscript] = useState('')

  const recognitionRef = useRef<SpeechRecognition | null>(null)
  const audioContextRef = useRef<AudioContext | null>(null)
  const analyserRef = useRef<AnalyserNode | null>(null)
  const micStreamRef = useRef<MediaStream | null>(null)
  const animationFrameRef = useRef<number | null>(null)

  // Check if speech recognition is supported
  const windowWithSpeech = typeof window !== 'undefined' ? (window as WindowWithSpeech) : null
  const SpeechRecognitionAPI = windowWithSpeech?.SpeechRecognition || windowWithSpeech?.webkitSpeechRecognition
  const isSupported = !!SpeechRecognitionAPI

  // Analyze volume from microphone
  const analyzeVolume = useCallback(() => {
    if (!analyserRef.current) return

    const dataArray = new Uint8Array(analyserRef.current.frequencyBinCount)
    analyserRef.current.getByteFrequencyData(dataArray)

    // Calculate RMS (root mean square) for volume
    let sum = 0
    for (let i = 0; i < dataArray.length; i++) {
      sum += dataArray[i] * dataArray[i]
    }
    const rms = Math.sqrt(sum / dataArray.length)

    // Normalize to 0-1 range (typical RMS values are 0-128)
    const normalizedVolume = Math.min(rms / 100, 1)
    setVolume(normalizedVolume)

    // Continue animation loop
    if (isListening) {
      animationFrameRef.current = requestAnimationFrame(analyzeVolume)
    }
  }, [isListening])

  // Start microphone stream for volume analysis
  const startAudioAnalysis = useCallback(async () => {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true })
      micStreamRef.current = stream

      audioContextRef.current = new AudioContext()
      analyserRef.current = audioContextRef.current.createAnalyser()
      analyserRef.current.fftSize = 256

      const source = audioContextRef.current.createMediaStreamSource(stream)
      source.connect(analyserRef.current)

      // Start volume analysis loop
      animationFrameRef.current = requestAnimationFrame(analyzeVolume)
    } catch (err) {
      console.error('Failed to access microphone:', err)
    }
  }, [analyzeVolume])

  // Stop audio analysis
  const stopAudioAnalysis = useCallback(() => {
    if (animationFrameRef.current) {
      cancelAnimationFrame(animationFrameRef.current)
      animationFrameRef.current = null
    }

    if (micStreamRef.current) {
      micStreamRef.current.getTracks().forEach(track => track.stop())
      micStreamRef.current = null
    }

    if (audioContextRef.current) {
      audioContextRef.current.close()
      audioContextRef.current = null
    }

    analyserRef.current = null
    setVolume(0)
  }, [])

  // Start listening
  const startListening = useCallback(() => {
    if (!SpeechRecognitionAPI || isListening) return

    const recognition = new SpeechRecognitionAPI()
    recognition.continuous = true
    recognition.interimResults = true
    recognition.lang = 'en-US'

    recognition.onstart = () => {
      setIsListening(true)
      startAudioAnalysis()
    }

    recognition.onresult = (event: SpeechRecognitionEvent) => {
      let interimTranscript = ''
      let finalTranscript = ''

      for (let i = event.resultIndex; i < event.results.length; i++) {
        const result = event.results[i]
        if (result.isFinal) {
          finalTranscript += result[0].transcript
        } else {
          interimTranscript += result[0].transcript
        }
      }

      if (finalTranscript) {
        setTranscript(finalTranscript)
        onTranscript?.(finalTranscript)
      }

      if (interimTranscript) {
        onInterimTranscript?.(interimTranscript)
      }
    }

    recognition.onerror = (event: SpeechRecognitionErrorEvent) => {
      console.error('Speech recognition error:', event.error)
      setIsListening(false)
      stopAudioAnalysis()
    }

    recognition.onend = () => {
      setIsListening(false)
      stopAudioAnalysis()
    }

    recognitionRef.current = recognition
    recognition.start()
  }, [SpeechRecognitionAPI, isListening, startAudioAnalysis, stopAudioAnalysis, onTranscript, onInterimTranscript])

  // Stop listening
  const stopListening = useCallback(() => {
    if (recognitionRef.current) {
      recognitionRef.current.stop()
      recognitionRef.current = null
    }
    setIsListening(false)
    stopAudioAnalysis()
  }, [stopAudioAnalysis])

  // Toggle listening
  const toggleListening = useCallback(() => {
    if (isListening) {
      stopListening()
    } else {
      startListening()
    }
  }, [isListening, startListening, stopListening])

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      stopListening()
    }
  }, [stopListening])

  return {
    isListening,
    isSupported,
    volume,
    transcript,
    startListening,
    stopListening,
    toggleListening,
  }
}
