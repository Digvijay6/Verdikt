/**
 * LANE 2 — candidate interview room.
 *
 * Public route: /interview/:token
 */

import { useState, useEffect, useRef, useCallback } from "react";
import type { Dispatch, SetStateAction } from "react";
import { useParams } from "react-router-dom";
import {
  DisconnectButton,
  LiveKitRoom,
  RoomAudioRenderer,
  TrackToggle,
  VideoTrack,
  useDataChannel,
  useLocalParticipant,
} from "@livekit/components-react";
import { Track } from "livekit-client";

import { api } from "../../lib/api";
import { ProctorClient } from "../../lib/proctor";

import { ConsentGate } from "../../components/interview/ConsentGate";
import { LiveTranscript } from "../../components/interview/LiveTranscript";
import { InterviewComplete } from "../../components/interview/InterviewComplete";

interface RedeemResponse {
  interview_id: string;
  org_id?: string;
  room_name: string;
  livekit_url: string;
  access_token: string;
  resuming: boolean;
}

interface TranscriptEntry {
  speaker: "agent" | "candidate";
  text: string;
  questionId?: string;
}

export default function InterviewRoom() {
  const { token } = useParams();
  const [phase, setPhase] = useState<"consent" | "connecting" | "live" | "done">("consent");
  const [error, setError] = useState<string | null>(null);
  const [connection, setConnection] = useState<RedeemResponse | null>(null);
  const [transcript, setTranscript] = useState<TranscriptEntry[]>([]);
  const proctorRef = useRef<ProctorClient | null>(null);

  const handleConsent = async () => {
    if (!token) return;
    setPhase("connecting");
    try {
      const res = await api.redeemInvite<RedeemResponse>(token);
      setConnection(res);
      setPhase("live");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to join interview");
      setPhase("consent");
    }
  };

  useEffect(() => {
    if (!connection || phase !== "live") return;
    const apiUrl = import.meta.env.VITE_API_URL ?? "http://localhost:8000";
    const proctor = new ProctorClient(
      connection.org_id ?? "",
      connection.interview_id,
      apiUrl,
    );
    proctor.start();
    proctorRef.current = proctor;
    return () => {
      proctor.destroy();
      proctorRef.current = null;
    };
  }, [connection, phase]);

  const handleInterviewEnd = useCallback(() => {
    setPhase("done");
  }, []);

  if (phase === "consent") {
    return <ConsentGate onAccept={handleConsent} error={error} />;
  }

  if (phase === "connecting") {
    return (
      <main className="wrap narrow">
        <div className="nb-card" style={{ textAlign: "center" }}>
          <p className="hint">Connecting...</p>
        </div>
      </main>
    );
  }

  if (phase === "done" || !connection) {
    return <InterviewComplete />;
  }

  return (
    <LiveKitRoom
      token={connection.access_token}
      serverUrl={connection.livekit_url}
      audio={true}
      video={true}
      connect={true}
      onDisconnected={() => {
        proctorRef.current?.destroy();
        setPhase("done");
      }}
      onError={(e) => {
        console.error("LiveKit error:", e);
        setError(e.message);
      }}
    >
      <InterviewSession
        transcript={transcript}
        onTranscript={setTranscript}
        onInterviewEnd={handleInterviewEnd}
      />
    </LiveKitRoom>
  );
}

function InterviewSession({
  transcript,
  onTranscript,
  onInterviewEnd,
}: {
  transcript: TranscriptEntry[];
  onTranscript: Dispatch<SetStateAction<TranscriptEntry[]>>;
  onInterviewEnd: () => void;
}) {
  const {
    cameraTrack,
    isCameraEnabled,
    isMicrophoneEnabled,
    lastCameraError,
    localParticipant,
  } = useLocalParticipant();

  const handleData = useCallback(
    (message: { payload: Uint8Array }) => {
      try {
        const payload = JSON.parse(new TextDecoder().decode(message.payload));
        if (payload.type === "transcript") {
          onTranscript((previous) => [
            ...previous,
            {
              speaker: payload.speaker,
              text: payload.text,
              questionId: payload.question_id,
            },
          ]);
        } else if (payload.type === "interview_end") {
          onInterviewEnd();
        }
      } catch {
        // Ignore malformed data-channel messages.
      }
    },
    [onInterviewEnd, onTranscript],
  );

  useDataChannel(handleData);

  return (
    <>
      <RoomAudioRenderer />
      <main className="wrap" style={{ maxWidth: "44rem" }}>
        <div
          style={{
            display: "flex",
            alignItems: "center",
            gap: "0.6rem",
            marginBottom: "1.5rem",
          }}
        >
          <div
            style={{
              width: "0.5rem",
              height: "0.5rem",
              borderRadius: "9999px",
              background: "var(--color-danger)",
              animation: "pulse 2s infinite",
            }}
          />
          <span style={{ fontSize: "0.85rem", color: "var(--color-muted)" }}>
            Interview in progress
          </span>
        </div>

        <div style={{ display: "flex", flexWrap: "wrap", gap: "1rem", alignItems: "stretch" }}>
          <section
            className="nb-card"
            aria-label="Your camera preview"
            style={{ flex: "1 1 14rem", minWidth: 0, padding: "0.75rem" }}
          >
            <div
              style={{
                aspectRatio: "4 / 3",
                overflow: "hidden",
                borderRadius: "var(--radius-tile)",
                background: "var(--color-ink)",
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
              }}
            >
              {isCameraEnabled && cameraTrack ? (
                <VideoTrack
                  trackRef={{
                    participant: localParticipant,
                    publication: cameraTrack,
                    source: Track.Source.Camera,
                  }}
                  style={{ width: "100%", height: "100%", objectFit: "cover" }}
                />
              ) : (
                <p style={{ color: "var(--color-panel)", fontSize: "0.85rem", margin: 0 }}>
                  {lastCameraError ? "Camera unavailable" : "Camera is off"}
                </p>
              )}
            </div>
            <p className="hint" style={{ margin: "0.75rem 0 0" }}>
              Your camera preview
            </p>
          </section>

          <div
            className="nb-card"
            style={{
              flex: "2 1 24rem",
              minWidth: 0,
              minHeight: "50vh",
              maxHeight: "70vh",
              overflowY: "auto",
            }}
          >
            <LiveTranscript transcript={transcript} />
          </div>
        </div>

        <div
          aria-label="Call controls"
          style={{
            display: "flex",
            flexWrap: "wrap",
            justifyContent: "center",
            gap: "0.75rem",
            marginTop: "1.25rem",
          }}
        >
          <TrackToggle
            className="nb-btn"
            source={Track.Source.Microphone}
            showIcon={false}
          >
            {isMicrophoneEnabled ? "Mute microphone" : "Unmute microphone"}
          </TrackToggle>
          <TrackToggle className="nb-btn" source={Track.Source.Camera} showIcon={false}>
            {isCameraEnabled ? "Turn camera off" : "Turn camera on"}
          </TrackToggle>
          <DisconnectButton className="nb-btn nb-btn-danger">
            End call
          </DisconnectButton>
        </div>

        <p
          style={{
            marginTop: "1rem",
            fontSize: "0.8rem",
            color: "var(--color-muted)",
            textAlign: "center",
          }}
        >
          Speak naturally — you can interrupt Verdikt at any time.
        </p>
      </main>
    </>
  );
}
