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
 *   5. Show live transcript + provisional scores
 *   6. On interview complete → thank you screen
 */

import { useState, useEffect, useRef } from "react";
import { useParams } from "react-router-dom";
import { useLiveKitRoom, useTracks } from "@livekit/components-react";
import { RoomEvent, Track } from "livekit-client";

import { api } from "../../lib/api";
import { ProctorClient } from "../../lib/proctor";

import { ConsentGate } from "../../components/interview/ConsentGate";
import { LiveTranscript } from "../../components/interview/LiveTranscript";
import { LiveSignalCard } from "../../components/interview/LiveSignalCard";
import { QuestionProgress } from "../../components/interview/QuestionProgress";
import { InterviewComplete } from "../../components/interview/InterviewComplete";

interface RedeemResponse {
  interview_id: string;
  org_id?: string;
  room_name: string;
  livekit_url: string;
  access_token: string;
  resuming: boolean;
}

export default function InterviewRoom() {
  const { token } = useParams();
  const [phase, setPhase] = useState<"consent" | "connecting" | "live" | "done">(
    "consent",
  );
  const [error, setError] = useState<string | null>(null);
  const [connection, setConnection] = useState<RedeemResponse | null>(null);
  const [transcript, setTranscript] = useState<TranscriptEntry[]>([]);
  const [signals, setSignals] = useState<Record<string, number>>({});
  const [questionCount, setQuestionCount] = useState(0);
  const proctorRef = useRef<ProctorClient | null>(null);

  // 1. Redeem the token after consent
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

  // 2. Start proctoring + connect to LiveKit when we have the connection info
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
    return <div className="flex items-center justify-center h-screen">Connecting...</div>;
  }

  if (phase === "done" || !connection) {
    return <InterviewComplete />;
  }

  return (
    <LiveKitRoomWrapper
      connection={connection}
      onTranscriptUpdate={setTranscript}
      onSignalUpdate={setSignals}
      onQuestionCount={setQuestionCount}
      onInterviewEnd={() => {
        setPhase("done");
        proctorRef.current?.destroy();
      }}
      transcript={transcript}
      signals={signals}
      questionCount={questionCount}
    />
  );
}

interface TranscriptEntry {
  speaker: "agent" | "candidate";
  text: string;
  questionId?: string;
}

function LiveKitRoomWrapper({
  connection,
  onTranscriptUpdate,
  onSignalUpdate,
  onQuestionCount,
  onInterviewEnd,
  transcript,
  signals,
  questionCount,
}: {
  connection: RedeemResponse;
  onTranscriptUpdate: (entries: TranscriptEntry[]) => void;
  onSignalUpdate: (signals: Record<string, number>) => void;
  onQuestionCount: (n: number) => void;
  onInterviewEnd: () => void;
  transcript: TranscriptEntry[];
  signals: Record<string, number>;
  questionCount: number;
}) {
  const roomProps = {
    serverUrl: connection.livekit_url,
    token: connection.access_token,
  };

  const room = useLiveKitRoom(roomProps);

  // Subscribe to data messages (transcript + live signals from the agent)
  useEffect(() => {
    if (!room) return;

    const handleData = (payload: Uint8Array) => {
      try {
        const msg = JSON.parse(new TextDecoder().decode(payload));
        if (msg.type === "transcript") {
          onTranscriptUpdate([...transcript, {
            speaker: msg.speaker,
            text: msg.text,
            questionId: msg.question_id,
          }]);
        } else if (msg.type === "live_signal") {
          onSignalUpdate({ ...signals, [msg.question_id]: msg.correctness });
        } else if (msg.type === "question_count") {
          onQuestionCount(msg.count);
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
  }, [room, transcript, signals, onTranscriptUpdate, onSignalUpdate, onQuestionCount, onInterviewEnd]);

  return (
    <div className="flex flex-col h-screen bg-gray-50">
      {/* Header */}
      <div className="flex items-center justify-between px-6 py-3 bg-white border-b">
        <div className="flex items-center gap-3">
          <div className="w-2 h-2 rounded-full bg-red-500 animate-pulse" />
          <span className="text-sm text-gray-600">Interview in progress</span>
        </div>
        <QuestionProgress current={questionCount} total={0} />
      </div>

      {/* Main content */}
      <div className="flex-1 flex overflow-hidden">
        {/* Transcript panel */}
        <div className="flex-1 overflow-y-auto p-6">
          <LiveTranscript transcript={transcript} />
        </div>

        {/* Live scores sidebar */}
        <div className="w-80 border-l bg-white p-4 overflow-y-auto">
          <h3 className="text-sm font-medium text-gray-700 mb-3">
            Provisional Scores
          </h3>
          <div className="space-y-2">
            {Object.entries(signals).map(([qid, score]) => (
              <LiveSignalCard key={qid} questionId={qid} score={score} />
            ))}
          </div>
          <p className="text-xs text-gray-400 mt-4">
            Scores are provisional and marked "live estimate". Final scores are
            computed after the interview.
          </p>
        </div>
      </div>
    </div>
  );
}