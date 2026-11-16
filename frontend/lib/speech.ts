"use client";

// Voice input and spoken answers for the chat (Ausbau A4).
// Input uses the browser's speech recognition (Chrome, Edge, Safari). Output uses the
// server voice (Piper) when it is set up, otherwise the browser's own speech synthesis.

import { useCallback, useEffect, useRef, useState } from "react";

import { api } from "@/lib/api";

interface RecognitionResult {
  isFinal: boolean;
  0: { transcript: string };
}

interface RecognitionEvent {
  resultIndex: number;
  results: ArrayLike<RecognitionResult>;
}

interface Recognition {
  lang: string;
  continuous: boolean;
  interimResults: boolean;
  onresult: ((e: RecognitionEvent) => void) | null;
  onerror: ((e: { error: string }) => void) | null;
  onend: (() => void) | null;
  start: () => void;
  stop: () => void;
}

type RecognitionCtor = new () => Recognition;

function recognitionCtor(): RecognitionCtor | null {
  if (typeof window === "undefined") return null;
  const w = window as unknown as {
    SpeechRecognition?: RecognitionCtor;
    webkitSpeechRecognition?: RecognitionCtor;
  };
  return w.SpeechRecognition ?? w.webkitSpeechRecognition ?? null;
}

const ERRORS: Record<string, string> = {
  "not-allowed": "Mikrofon ist nicht erlaubt. Bitte im Browser freigeben.",
  "service-not-allowed": "Spracheingabe ist in diesem Browser gesperrt.",
  "no-speech": "Ich habe nichts gehört. Nochmal versuchen?",
  network: "Spracheingabe braucht eine Internetverbindung.",
};

/** Dictation: calls ``onText`` with the final text of each spoken phrase. */
export function useDictation(onText: (text: string) => void) {
  const [supported, setSupported] = useState(false);
  const [listening, setListening] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const rec = useRef<Recognition | null>(null);
  const cb = useRef(onText);
  cb.current = onText;

  useEffect(() => setSupported(recognitionCtor() !== null), []);

  const stop = useCallback(() => {
    rec.current?.stop();
  }, []);

  const start = useCallback(() => {
    const Ctor = recognitionCtor();
    if (!Ctor) return;
    setError(null);
    const r = new Ctor();
    r.lang = "de-DE";
    r.continuous = true;
    r.interimResults = false;
    r.onresult = (e) => {
      for (let i = e.resultIndex; i < e.results.length; i++) {
        const res = e.results[i];
        if (res?.isFinal) cb.current(res[0].transcript.trim());
      }
    };
    r.onerror = (e) => setError(ERRORS[e.error] ?? "Spracheingabe hat nicht geklappt.");
    r.onend = () => {
      setListening(false);
      rec.current = null;
    };
    rec.current = r;
    try {
      r.start();
      setListening(true);
    } catch {
      setError("Spracheingabe hat nicht geklappt.");
    }
  }, []);

  useEffect(() => () => rec.current?.stop(), []);

  return { supported, listening, error, start, stop };
}

function browserVoice(text: string): Promise<void> {
  return new Promise((resolve) => {
    if (typeof window === "undefined" || !("speechSynthesis" in window)) return resolve();
    const u = new SpeechSynthesisUtterance(
      text.replace(/https?:\/\/\S+/g, "Link").replace(/[*_`#>|]/g, ""),
    );
    const english = /\b(the|and|you|is|are|this)\b/i.test(text) && !/[äöüß]/i.test(text);
    u.lang = english ? "en-US" : "de-DE";
    u.rate = 1.05;
    u.onend = () => resolve();
    u.onerror = () => resolve();
    window.speechSynthesis.cancel();
    window.speechSynthesis.speak(u);
  });
}

/** Reads assistant answers aloud; one at a time. */
export function useSpeaker() {
  const [playing, setPlaying] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const audio = useRef<HTMLAudioElement | null>(null);

  const stop = useCallback(() => {
    audio.current?.pause();
    audio.current = null;
    if (typeof window !== "undefined" && "speechSynthesis" in window) {
      window.speechSynthesis.cancel();
    }
    setPlaying(null);
  }, []);

  const speak = useCallback(
    async (id: number, text: string) => {
      stop();
      setError(null);
      setPlaying(id);
      try {
        const blob = await api.chatSpeech(id);
        if (!blob) {
          await browserVoice(text);
          setPlaying((p) => (p === id ? null : p));
          return;
        }
        const url = URL.createObjectURL(blob);
        const a = new Audio(url);
        audio.current = a;
        a.onended = () => {
          URL.revokeObjectURL(url);
          setPlaying((p) => (p === id ? null : p));
        };
        await a.play();
      } catch (err) {
        setError((err as Error).message || "Vorlesen ging nicht.");
        setPlaying(null);
      }
    },
    [stop],
  );

  useEffect(() => stop, [stop]);

  return { playing, error, speak, stop };
}
