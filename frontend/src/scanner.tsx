import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { useParams } from "react-router-dom";
import { api } from "./api";
import { prepareBarcode } from "./barcode";
import { Page } from "./ui";

const FORMAT_EAN_13 = 7;
const FORMAT_EAN_8 = 6;
const FORMAT_UPC_A = 14;
const FORMAT_UPC_E = 15;
const FORMAT_CODE_128 = 4;
const FORMAT_CODE_39 = 2;
const FORMAT_QR = 11;
const FORMATS = [FORMAT_EAN_13, FORMAT_EAN_8, FORMAT_UPC_A, FORMAT_UPC_E, FORMAT_CODE_128, FORMAT_CODE_39, FORMAT_QR];

type Status = "starting" | "ready" | "detecting" | "detected" | "denied" | "unavailable" | "busy" | "unsupported" | "invalid";

const STATUS_TEXT: Record<Status, string> = {
  starting: "Starting camera",
  ready: "Camera ready",
  detecting: "Detecting...",
  detected: "Barcode detected",
  denied: "Camera permission denied",
  unavailable: "Camera unavailable",
  busy: "Camera already in use",
  unsupported: "This browser cannot scan from a camera",
  invalid: "That barcode could not be used",
};

type TrackWindow = Window & { __aipfCameraTracks?: MediaStreamTrack[] };

function publishTracks(tracks: MediaStreamTrack[]) {
  const view = window as TrackWindow & { __aipfLastTracks?: MediaStreamTrack[] };
  view.__aipfCameraTracks = tracks;
  if (tracks.length) view.__aipfLastTracks = tracks;
}

function cameraError(err: unknown): { status: Status; detail: string } {
  const name = err instanceof DOMException ? err.name : "";
  if (name === "NotAllowedError" || name === "PermissionDeniedError") {
    return { status: "denied", detail: "Allow the camera in the browser prompt, or enter the barcode manually." };
  }
  if (name === "NotFoundError" || name === "DevicesNotFoundError" || name === "OverconstrainedError") {
    return { status: "unavailable", detail: "No camera was found. Enter the barcode manually." };
  }
  if (name === "NotReadableError" || name === "TrackStartError" || name === "AbortError") {
    return { status: "busy", detail: "Close the other app using the camera, then retry." };
  }
  return { status: "unavailable", detail: err instanceof Error ? err.message : "The camera could not start. Enter the barcode manually." };
}

export function BarcodeScanner({ onClose, onUse }: { onClose: () => void; onUse: (code: string) => void }) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const onUseRef = useRef(onUse);
  const session = useRef(0);
  const controlsRef = useRef<{ stop: () => void } | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const locked = useRef(false);
  const used = useRef(false);
  const [status, setStatus] = useState<Status>("starting");
  const [detail, setDetail] = useState("Point the camera at a barcode");
  const [devices, setDevices] = useState<MediaDeviceInfo[]>([]);
  const [deviceId, setDeviceId] = useState("");
  const [code, setCode] = useState("");
  const [still, setStill] = useState("");
  const [manual, setManual] = useState("");
  const [manualError, setManualError] = useState("");
  const closeRef = useRef<HTMLButtonElement>(null);

  useEffect(() => { onUseRef.current = onUse; }, [onUse]);

  function release() {
    try { controlsRef.current?.stop(); } catch { /* already stopped */ }
    controlsRef.current = null;
    const stream = streamRef.current;
    const tracks = stream?.getTracks() || [];
    streamRef.current = null;
    tracks.forEach((track) => track.stop());
    if (videoRef.current) videoRef.current.srcObject = null;
    const view = window as TrackWindow & { __aipfLastTracks?: MediaStreamTrack[] };
    if (tracks.length) view.__aipfLastTracks = tracks;
    publishTracks([]);
  }

  async function start(nextDeviceId = deviceId) {
    const mine = ++session.current;
    locked.current = false;
    setCode("");
    setStill("");
    setManualError("");
    setStatus("starting");
    setDetail("Point the camera at a barcode");
    release();
    if (!navigator.mediaDevices?.getUserMedia) {
      setStatus("unsupported");
      setDetail("Enter the barcode manually.");
      return;
    }
    try {
      const video = nextDeviceId
        ? { deviceId: { exact: nextDeviceId } }
        : { facingMode: { ideal: "environment" } };
      let stream: MediaStream;
      try {
        stream = await navigator.mediaDevices.getUserMedia({ audio: false, video });
      } catch (err) {
        if (nextDeviceId) throw err;
        stream = await navigator.mediaDevices.getUserMedia({ audio: false, video: true });
      }
      if (mine !== session.current) {
        stream.getTracks().forEach((track) => track.stop());
        return;
      }
      streamRef.current = stream;
      publishTracks(stream.getTracks());
      const view = window as TrackWindow & { __aipfCameraStarts?: number };
      view.__aipfCameraStarts = (view.__aipfCameraStarts || 0) + 1;
      setStatus("ready");
      setDetail("Camera ready");
      const listed = (await navigator.mediaDevices.enumerateDevices()).filter((item) => item.kind === "videoinput");
      if (mine !== session.current) return;
      setDevices(listed);
      const active = stream.getVideoTracks()[0]?.getSettings().deviceId || nextDeviceId;
      if (active) setDeviceId(active);
      const lib = await import("@zxing/library");
      const { BrowserMultiFormatReader } = await import("@zxing/browser");
      if (mine !== session.current) return;
      const hints = new Map();
      hints.set(lib.DecodeHintType.POSSIBLE_FORMATS, FORMATS);
      hints.set(lib.DecodeHintType.TRY_HARDER, true);
      const reader = new BrowserMultiFormatReader(hints, { delayBetweenScanAttempts: 180, delayBetweenScanSuccess: 400 });
      const preview = videoRef.current;
      if (!preview) {
        release();
        return;
      }
      setStatus("detecting");
      controlsRef.current = await reader.decodeFromStream(stream, preview, (result) => {
        if (locked.current || mine !== session.current || !result) return;
        const format = result.getBarcodeFormat();
        if (!FORMATS.includes(format)) {
          setStatus("invalid");
          setDetail("Unsupported barcode format. Scan an EAN, UPC, Code 128, or Code 39, or enter it manually.");
          return;
        }
        const prepared = prepareBarcode(result.getText() || "");
        if (prepared.error) {
          setStatus("invalid");
          setDetail(prepared.error);
          return;
        }
        locked.current = true;
        const shot = captureFrame(preview);
        setStill(shot);
        setCode(prepared.code);
        setStatus("detected");
        setDetail("Barcode detected");
        release();
      });
      if (mine !== session.current) {
        release();
        return;
      }
      if (locked.current) return;
    } catch (err) {
      if (mine !== session.current || locked.current) return;
      release();
      const mapped = cameraError(err);
      setStatus(mapped.status);
      setDetail(mapped.detail);
    }
  }

  useEffect(() => {
    start();
    closeRef.current?.focus();
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => {
      session.current += 1;
      window.removeEventListener("keydown", onKey);
      release();
    };
    // The scanner owns its camera for this mount. Restart is explicit.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  function applyCode(value: string) {
    if (used.current) return;
    const prepared = prepareBarcode(value);
    if (prepared.error) {
      setManualError(prepared.error);
      setStatus("invalid");
      setDetail(prepared.error);
      return;
    }
    used.current = true;
    locked.current = true;
    release();
    onUseRef.current(prepared.code);
    onClose();
  }

  function switchCamera() {
    if (devices.length < 2) return;
    const index = devices.findIndex((item) => item.deviceId === deviceId);
    const next = devices[(index + 1) % devices.length];
    setDeviceId(next.deviceId);
    start(next.deviceId);
  }

  const showVideo = status === "starting" || status === "ready" || status === "detecting" || status === "invalid";

  return createPortal(
    <div className="scan-back" role="presentation" onMouseDown={onClose}>
      <section
        className="scan-sheet"
        role="dialog"
        aria-modal="true"
        aria-label="Barcode scanner"
        data-scan-status={status}
        onMouseDown={(event) => event.stopPropagation()}
      >
        <header>
          <strong>Scan barcode</strong>
          <button ref={closeRef} type="button" className="btn small" onClick={onClose}>Close</button>
        </header>
        <div className="scan-stage">
          <video ref={videoRef} className="scan-video" muted playsInline autoPlay hidden={!showVideo} />
          {still && !showVideo && <img src={still} alt="Captured barcode frame" />}
          {showVideo && <div className="scan-frame" aria-hidden="true" />}
          {showVideo && <p className="scan-aim">Point the camera at a barcode</p>}
        </div>
        <div className="scan-body">
          <p className="scan-status" aria-live="polite" data-scan-state={status}>{STATUS_TEXT[status]}</p>
          <p className="muted">{detail}</p>
          {status === "detected" && (
            <div className="scan-found">
              <p className="scan-code" data-detected-code={code}>{code}</p>
              <p className="muted">This is only the barcode number. It is not a medicine name, and nothing has been saved.</p>
              <div className="row-actions">
                <button type="button" className="btn primary" onClick={() => applyCode(code)}>Use Barcode</button>
                <button type="button" className="btn" onClick={() => start(deviceId)}>Scan Again</button>
              </div>
            </div>
          )}
          {status !== "detected" && (
            <div className="row-actions">
              <button type="button" className="btn" onClick={() => start(deviceId)}>Retry camera</button>
              {devices.length > 1 && <button type="button" className="btn" onClick={switchCamera}>Switch camera</button>}
            </div>
          )}
          <form className="scan-manual" onSubmit={(event) => { event.preventDefault(); applyCode(manual); }}>
            <label>
              Enter barcode manually
              <input
                value={manual}
                onChange={(event) => { setManual(event.target.value); setManualError(""); }}
                autoComplete="off"
                inputMode="text"
                aria-label="Enter barcode manually"
              />
            </label>
            {manualError && <p className="warn">{manualError}</p>}
            <button type="submit" className="btn">Continue</button>
          </form>
        </div>
      </section>
    </div>,
    document.body,
  );
}

export function PhonePair({ onUse }: { onUse: (code: string) => void }) {
  const [open, setOpen] = useState(false);
  const [pair, setPair] = useState<any>(null);
  const [error, setError] = useState("");
  const onUseRef = useRef(onUse);
  useEffect(() => {
    onUseRef.current = onUse;
  }, [onUse]);
  useEffect(() => {
    if (!open || !pair?.token) return;
    let stop = false;
    const tick = window.setInterval(async () => {
      if (stop) return;
      try {
        const row = await api<any>(`/api/scan-pairs/${encodeURIComponent(pair.token)}`);
        if (row.status === "ready" && row.code) {
          stop = true;
          window.clearInterval(tick);
          setOpen(false);
          onUseRef.current(row.code);
        }
      } catch (err) {
        stop = true;
        window.clearInterval(tick);
        setError(err instanceof Error ? err.message : "Pairing expired");
      }
    }, 1500);
    return () => {
      stop = true;
      window.clearInterval(tick);
    };
  }, [open, pair?.token]);
  if (!open) {
    return (
      <button className="btn" type="button" onClick={() => {
        setError("");
        api<any>("/api/scan-pairs", { method: "POST", body: JSON.stringify({ origin: window.location.origin }) })
          .then((row) => { setPair(row); setOpen(true); })
          .catch((err) => setError(err instanceof Error ? err.message : "Could not start pairing"));
      }}>Scan using phone</button>
    );
  }
  return (
    <div className="pair-sheet">
      <strong>Scan using phone</strong>
      <p className="muted">The code lasts two minutes and can be used once. It contains no patient information.</p>
      {pair?.svg ? <div className="pair-qr" dangerouslySetInnerHTML={{ __html: pair.svg }} /> : <p className="pid">{pair?.url}</p>}
      {pair?.url && <p className="muted">{pair.url}</p>}
      {error && <p className="warn">{error}</p>}
      <button className="btn" type="button" onClick={() => setOpen(false)}>Cancel</button>
    </div>
  );
}

export function PairPage() {
  const { token } = useParams();
  const [done, setDone] = useState("");
  const [error, setError] = useState("");
  const [manual, setManual] = useState("");
  const [camera, setCamera] = useState(false);
  async function send(code: string) {
    const prepared = prepareBarcode(code);
    if (prepared.error) {
      setError(prepared.error);
      return;
    }
    await api(`/api/scan-pairs/${encodeURIComponent(token || "")}`, { method: "POST", body: JSON.stringify({ code: prepared.code }) });
    setDone(prepared.code);
    setCamera(false);
  }
  return (
    <Page kicker="Barcode" title="Send to the desk" note="This only sends the barcode. It does not open a patient, dispense, or change stock.">
      {done ? <p>Sent {done}. You can close this page.</p> : (
        <div className="panel">
          <div className="body">
            {error && <p className="warn">{error}</p>}
            <button className="btn primary" type="button" onClick={() => setCamera(true)}>Scan barcode</button>
            <form className="scan-manual" onSubmit={(e) => { e.preventDefault(); send(manual).catch((err) => setError(err instanceof Error ? err.message : "Could not send")); }}>
              <input aria-label="Barcode" value={manual} onChange={(e) => setManual(e.target.value)} placeholder="Or type the barcode" />
              <button className="btn" type="submit">Send to desk</button>
            </form>
          </div>
        </div>
      )}
      {camera && <BarcodeScanner onClose={() => setCamera(false)} onUse={(code) => { send(code).catch((err) => setError(err instanceof Error ? err.message : "Could not send")); }} />}
    </Page>
  );
}

function captureFrame(video: HTMLVideoElement) {
  if (!video.videoWidth) return "";
  const canvas = document.createElement("canvas");
  canvas.width = video.videoWidth;
  canvas.height = video.videoHeight;
  canvas.getContext("2d")?.drawImage(video, 0, 0);
  try {
    return canvas.toDataURL("image/jpeg", 0.72);
  } catch {
    return "";
  }
}
