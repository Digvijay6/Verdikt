/**
 * Browser-side proctoring client.
 *
 * Runs entirely in-page (no extension, no install). Detects what it can from
 * the browser sandbox and sends events to /interview/events. All events are
 * evidence for a human reviewer, never a hard gate.
 *
 * See docs/compliance.md for the posture: browser-only, every available
 * signal applied to every interview.
 */

export interface ProctorEvent {
  org_id: string;
  interview_id: string;
  type: ProctorEventType;
  severity: number;
  at_ms: number;
  detail: Record<string, unknown>;
}

type ProctorEventType =
  | "tab_blur"
  | "fullscreen_exit"
  | "paste_burst"
  | "virtual_camera"
  | "multiple_displays"
  | "vm_detected"
  | "raf_jitter"
  | "device_change";

const VIRTUAL_CAMERA_REGEX = /obs|virtual|snap|many|cam|droidcam|ecam|vcam|nvidia/i;
const VM_RENDERER_REGEX = /swiftshader|llvmpipe|virtualbox|vmware|microsoft basic render/i;

export class ProctorClient {
  private orgId: string;
  private interviewId: string;
  private apiUrl: string;
  private eventQueue: ProctorEvent[] = [];
  private flushInterval: ReturnType<typeof setInterval> | null = null;
  private rafId: number | null = null;
  private lastRafTime = 0;
  private cameraLabels: string[] = [];
  private monitors = 1;
  private destroyed = false;

  constructor(orgId: string, interviewId: string, apiUrl: string) {
    this.orgId = orgId;
    this.interviewId = interviewId;
    this.apiUrl = apiUrl;
  }

  async start(): Promise<void> {
    // Fullscreen enforcement + exit detection
    this.setupFullscreen();

    // Visibility / blur detection
    this.setupVisibility();

    // Clipboard / paste detection
    this.setupClipboard();

    // Device enumeration (virtual cameras)
    await this.enumerateDevices();

    // Display enumeration (multiple monitors)
    await this.checkDisplays();

    // WebGL fingerprint (VM detection)
    this.checkWebGL();

    // requestAnimationFrame jitter (GPU contention)
    this.startRafJitter();

    // Batch-send events every 5 seconds
    this.flushInterval = setInterval(() => this.flush(), 5000);
  }

  destroy(): void {
    this.destroyed = true;
    if (this.flushInterval) clearInterval(this.flushInterval);
    if (this.rafId) cancelAnimationFrame(this.rafId);
    this.flush();
  }

  private emit(type: ProctorEventType, severity: number, detail: Record<string, unknown>): void {
    this.eventQueue.push({
      org_id: this.orgId,
      interview_id: this.interviewId,
      type,
      severity,
      at_ms: Date.now(),
      detail,
    });
  }

  // --- Fullscreen ---------------------------------------------------------

  private setupFullscreen(): void {
    document.documentElement.requestFullscreen?.().catch(() => {});

    document.addEventListener("fullscreenchange", () => {
      if (!document.fullscreenElement) {
        this.emit("fullscreen_exit", 0.5, {});
      }
    });
  }

  // --- Visibility / blur -------------------------------------------------

  private setupVisibility(): void {
    document.addEventListener("visibilitychange", () => {
      if (document.visibilityState === "hidden") {
        this.emit("tab_blur", 0.4, {});
      }
    });

    window.addEventListener("blur", () => {
      this.emit("tab_blur", 0.3, {});
    });
  }

  // --- Clipboard / paste -------------------------------------------------

  private setupClipboard(): void {
    let lastInputTime = 0;
    let lastInputLength = 0;

    document.addEventListener("paste", (e) => {
      const pasted = e.clipboardData?.getData("text") ?? "";
      if (pasted.length > 20) {
        this.emit("paste_burst", 0.8, {
          pasted_length: pasted.length,
          snippet: pasted.slice(0, 100),
        });
      }
    });

    // Paste burst detection on text inputs
    document.addEventListener("input", (e) => {
      const target = e.target as HTMLInputElement | HTMLTextAreaElement;
      if (!target || !("value" in target)) return;
      const now = performance.now();
      const inserted = target.value.length - lastInputLength;
      if (inserted > 20 && now - lastInputTime < 120) {
        this.emit("paste_burst", 0.7, {
          inserted_chars: inserted,
          dt_ms: now - lastInputTime,
        });
      }
      lastInputLength = target.value.length;
      lastInputTime = now;
    });
  }

  // --- Device enumeration (virtual cameras) ------------------------------

  private async enumerateDevices(): Promise<void> {
    try {
      // Need to request a stream to get device labels
      const stream = await navigator.mediaDevices.getUserMedia({ video: true, audio: false });
      stream.getTracks().forEach((t) => t.stop());

      const devices = await navigator.mediaDevices.enumerateDevices();
      const cameras = devices.filter((d) => d.kind === "videoinput");
      this.cameraLabels = cameras.map((c) => c.label || "");

      for (const label of this.cameraLabels) {
        if (VIRTUAL_CAMERA_REGEX.test(label)) {
          this.emit("virtual_camera", 0.9, { label });
        }
      }

      // Re-enumerate on device change
      navigator.mediaDevices.addEventListener("devicechange", async () => {
        const newDevices = await navigator.mediaDevices.enumerateDevices();
        const newCameras = newDevices.filter((d) => d.kind === "videoinput");
        for (const cam of newCameras) {
          const label = cam.label || "";
          if (label && !this.cameraLabels.includes(label)) {
            if (VIRTUAL_CAMERA_REGEX.test(label)) {
              this.emit("virtual_camera", 0.9, { label });
            } else {
              this.emit("device_change", 0.3, { label });
            }
          }
        }
        this.cameraLabels = newCameras.map((c) => c.label || "");
      });
    } catch {
      // Permission denied — not fatal
    }
  }

  // --- Display enumeration (multiple monitors) ----------------------------

  private async checkDisplays(): Promise<void> {
    try {
      const stream = await navigator.mediaDevices.getDisplayMedia({ video: true });
      const track = stream.getVideoTracks()[0];
      const settings = track.getSettings();

      if (settings.displaySurface === "monitor") {
        this.monitors = 1;
      }

      // Check for virtual display
      if ((settings as MediaTrackSettings & { logicalSurface?: boolean }).logicalSurface) {
        this.emit("multiple_displays", 0.7, {
          logicalSurface: true,
          displaySurface: settings.displaySurface,
        });
      }

      stream.getTracks().forEach((t) => t.stop());
    } catch {
      // User declined screen share — fine, just skip
    }
  }

  // --- WebGL fingerprint (VM detection) -----------------------------------

  private checkWebGL(): void {
    try {
      const canvas = document.createElement("canvas");
      const gl = canvas.getContext("webgl");
      if (!gl) return;
      const renderer = (gl.getParameter(gl.RENDERER) as string) || "";
      const vendor = (gl.getParameter(gl.VENDOR) as string) || "";
      if (VM_RENDERER_REGEX.test(renderer) || VM_RENDERER_REGEX.test(vendor)) {
        this.emit("vm_detected", 0.8, { renderer, vendor });
      }
    } catch {
      // No WebGL — not relevant
    }
  }

  // --- rAF jitter (GPU contention from overlays) -------------------------

  private startRafJitter(): void {
    this.lastRafTime = performance.now();

    const loop = (t: number) => {
      if (this.destroyed) return;
      const delta = t - this.lastRafTime;
      this.lastRafTime = t;

      // Sustained >50ms frames while visible = GPU contention
      if (delta > 50 && document.visibilityState === "visible") {
        this.emit("raf_jitter", 0.3, { delta_ms: delta });
      }

      this.rafId = requestAnimationFrame(loop);
    };

    this.rafId = requestAnimationFrame(loop);
  }

  // --- Flush to backend ---------------------------------------------------

  private async flush(): Promise<void> {
    if (this.eventQueue.length === 0) return;
    const batch = this.eventQueue.splice(0);
    try {
      await fetch(`${this.apiUrl}/interview/events`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(batch),
      });
    } catch {
      // Re-queue on failure (cap to avoid infinite growth)
      if (this.eventQueue.length < 100) {
        this.eventQueue.unshift(...batch);
      }
    }
  }
}