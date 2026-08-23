/**
 * Live transcript — shows agent and candidate turns as they happen.
 */

interface TranscriptEntry {
  speaker: "agent" | "candidate";
  text: string;
  questionId?: string;
}

interface LiveTranscriptProps {
  transcript: TranscriptEntry[];
}

export function LiveTranscript({ transcript }: LiveTranscriptProps) {
  if (transcript.length === 0) {
    return (
      <div className="flex items-center justify-center h-full text-gray-400 text-sm">
        The interview will begin shortly...
      </div>
    );
  }

  return (
    <div className="space-y-4">
      {transcript.map((entry, i) => (
        <div
          key={i}
          className={`flex ${entry.speaker === "agent" ? "justify-start" : "justify-end"}`}
        >
          <div
            className={`max-w-[80%] rounded-2xl px-4 py-3 ${
              entry.speaker === "agent"
                ? "bg-gray-100 text-gray-900"
                : "bg-blue-50 text-gray-900"
            }`}
          >
            <div className="text-xs text-gray-400 mb-1">
              {entry.speaker === "agent" ? "Interviewer" : "You"}
            </div>
            <p className="text-sm leading-relaxed">{entry.text}</p>
          </div>
        </div>
      ))}
    </div>
  );
}