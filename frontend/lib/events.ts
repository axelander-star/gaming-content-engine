// Tiny in-page event so the shell banner reacts immediately to control changes.
const CONTROLS_EVENT = "gce:controls-changed";

export function emitEmergencyStop(active: boolean): void {
  window.dispatchEvent(new CustomEvent<boolean>(CONTROLS_EVENT, { detail: active }));
}

export function onEmergencyStop(handler: (active: boolean) => void): () => void {
  const listener = (e: Event) => handler((e as CustomEvent<boolean>).detail);
  window.addEventListener(CONTROLS_EVENT, listener);
  return () => window.removeEventListener(CONTROLS_EVENT, listener);
}
