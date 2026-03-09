export const renderSessionStatusClass = (level?: string | null) => {
  switch (String(level ?? '').toLowerCase()) {
    case 'healthy':
    case 'completed':
    case 'running':
    case 'recording':
    case 'connected':
    case 'active':
      return 'border-emerald-200 bg-emerald-50 text-emerald-700';
    case 'degraded':
    case 'warming':
    case 'paused':
    case 'resetting':
    case 'connecting':
    case 'starting':
    case 'deploying':
      return 'border-amber-200 bg-amber-50 text-amber-700';
    case 'error':
    case 'failed':
    case 'disconnected':
    case 'inactive':
    case 'stopped':
      return 'border-rose-200 bg-rose-50 text-rose-700';
    default:
      return 'border-slate-200 bg-slate-100 text-slate-600';
  }
};

export const renderSessionPanelClass = (level?: string | null) => {
  switch (String(level ?? '').toLowerCase()) {
    case 'healthy':
    case 'completed':
    case 'running':
    case 'recording':
    case 'connected':
    case 'active':
      return 'border-emerald-200/80 bg-emerald-50/40';
    case 'degraded':
    case 'warming':
    case 'paused':
    case 'resetting':
    case 'connecting':
    case 'starting':
    case 'deploying':
      return 'border-amber-200/80 bg-amber-50/40';
    case 'error':
    case 'failed':
    case 'disconnected':
    case 'inactive':
    case 'stopped':
      return 'border-rose-200/80 bg-rose-50/40';
    default:
      return 'border-slate-200/80 bg-slate-50/70';
  }
};

export const speakSessionMessage = (message: string) => {
  if (typeof window === 'undefined' || !('speechSynthesis' in window)) return;
  const normalized = String(message || '').trim();
  if (!normalized) return;

  try {
    const utterance = new SpeechSynthesisUtterance(normalized);
    utterance.lang = 'ja-JP';
    utterance.rate = 1;
    utterance.pitch = 0.85;
    utterance.volume = 0.9;
    const voices = window.speechSynthesis.getVoices();
    const preferredVoice =
      voices.find((voice) => voice.lang === 'ja-JP') ??
      voices.find((voice) => voice.lang.toLowerCase().startsWith('ja')) ??
      null;
    if (preferredVoice) utterance.voice = preferredVoice;
    window.speechSynthesis.cancel();
    window.speechSynthesis.speak(utterance);
  } catch {
    // Ignore browsers that reject background/autoplay speech.
  }
};

export const computeScrollTargetTop = (options: {
  currentScrollY: number;
  elementBottom: number;
  viewportHeight: number;
  marginPx?: number;
}) => {
  const { currentScrollY, elementBottom, viewportHeight, marginPx = 24 } = options;
  const overflow = elementBottom - viewportHeight + marginPx;
  if (overflow <= 0) return currentScrollY;
  return Math.max(0, Math.ceil(currentScrollY + overflow));
};

export const scrollIntoViewSoon = (element: HTMLElement | null, delayMs = 120) => {
  if (typeof window === 'undefined' || !element) return () => {};

  let timeoutId: number | null = null;
  let observer: ResizeObserver | null = null;

  const syncScroll = () => {
    if (!element.isConnected) {
      cleanup();
      return;
    }
    const targetTop = computeScrollTargetTop({
      currentScrollY: window.scrollY,
      elementBottom: element.getBoundingClientRect().bottom,
      viewportHeight: window.innerHeight
    });
    if (Math.abs(targetTop - window.scrollY) > 1) {
      window.scrollTo({ top: targetTop, behavior: 'auto' });
    }
  };

  const cleanup = () => {
    if (timeoutId !== null) {
      window.clearTimeout(timeoutId);
      timeoutId = null;
    }
    observer?.disconnect();
    observer = null;
  };

  timeoutId = window.setTimeout(() => {
    syncScroll();
  }, delayMs);

  if (typeof ResizeObserver !== 'undefined') {
    observer = new ResizeObserver(() => {
      syncScroll();
    });
    observer.observe(element);
  }

  return cleanup;
};
