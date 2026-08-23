/**
 * LANE 2 — candidate interview room.
 *
 * Public route: /interview/:token
 *
 * Flow:
 *   1. Consent gate (GDPR/BIPA/AEDTA)
 *   2. Redeem invite token → get LiveKit access token + room name
 *   3. Connect to LiveKit room
 *   4. Start proctoring client
 *   5. Show live transcript
 *   6. On interview complete → thank you screen
 */

import { useState, useEffect, useRef } from "react";
import { useParams } from "react-router-dom";
import { useLiveKitRoom } from "@livekit/components-react";
import { RoomEvent } from "livekit-client";

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
  const [phase, setPhase] = useState<"consent" | "connecting" | "live" | "done">(
    "consent",
  );
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
      (connection as RedeemResponse & { org_id?: string }).org_id ?? "",
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
    <LiveKitRoomWrapper
      connection={connection}
      onTranscriptUpdate={setTranscript}
      onInterviewEnd={() => {
        setPhase("done");
        proctorRef.current?.destroy();
      }}
      transcript={transcript}
    />
  );
}

function LiveKitRoomWrapper({
  connection,
  onTranscriptUpdate,
  onInterviewEnd,
  transcript,
}: {
  connection: RedeemResponse;
  onTranscriptUpdate: (entries: TranscriptEntry[]) => void;
  onInterviewEnd: () => void;
  transcript: TranscriptEntry[];
}) {
  const roomProps = {
    serverUrl: connection.livekit_url,
    token: connection.access_token,
  };

  const room = useLiveKitRoom(roomProps);

  useEffect(() => {
    if (!room) return;

    const handleData = (payload: Uint8Array) => {
      try {
        const msg = JSON.parse(new TextDecoder().decode(payload));
        if (msg.type === "transcript") {
          onTranscriptUpdate([
            ...transcript,
            {
              speaker: msg.speaker,
              text: msg.text,
              questionId: msg.question_id,
            },
          ]);
        } else if (msg.type === "interview_end") {
          onInterviewEnd();
        }
      } catch {
        // Ignore malformed messages
      }
    };

    room.on(RoomEvent.DataReceived, handleData);

    return () => {
      room.off(RoomEvent.DataReceived, handleData);
    };
  }, [room, transcript, onTranscriptUpdate, onInterviewEnd]);

  return (
    <main className="wrap" style={{ maxWidth: "44rem" }}>
      {/* Header */}
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
        <span
          style={{
            fontSize: "0.85rem",
            color: "var(--color-muted)",
            fontFamily: "var(--font-sans)",
          }}
        >
          Interview in progress
        </span>
      </div>

      {/* Transcript card */}
      <div
        className="nb-card"
        style={{
          minHeight: "60vh",
          maxHeight: "70vh",
          overflowY: "auto",
        }}
      >
        <LiveTranscript transcript={transcript} />
      </div>

      {/* Hint */}
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
  );
}