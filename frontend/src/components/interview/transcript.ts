export interface TranscriptEntry {
  id: string;
  speaker: "agent" | "candidate";
  text: string;
}

interface LiveKitTranscription {
  text: string;
  participantInfo: { identity: string };
  streamInfo: { id: string };
}

export function toTranscriptEntries(
  transcriptions: readonly LiveKitTranscription[],
  localParticipantIdentity: string,
): TranscriptEntry[] {
  const entries: TranscriptEntry[] = [];
  for (const transcription of transcriptions) {
    const text = transcription.text.trim();
    if (!text) continue;

    entries.push({
      id: transcription.streamInfo.id,
      speaker:
        transcription.participantInfo.identity === localParticipantIdentity
          ? "candidate"
          : "agent",
      text,
    });
  }
  return entries;
}
