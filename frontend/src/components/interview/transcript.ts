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
  const streams: TranscriptEntry[] = [];
  const streamIndexes = new Map<string, number>();
  for (const transcription of transcriptions) {
    const text = transcription.text.trim();
    if (!text) continue;

    const entry: TranscriptEntry = {
      id: transcription.streamInfo.id,
      speaker:
        transcription.participantInfo.identity === localParticipantIdentity
          ? "candidate"
          : "agent",
      text,
    };
    const existingIndex = streamIndexes.get(entry.id);
    if (existingIndex !== undefined) {
      streams[existingIndex] = entry;
    } else {
      streamIndexes.set(entry.id, streams.length);
      streams.push(entry);
    }
  }

  const entries: TranscriptEntry[] = [];
  for (const stream of streams) {
    const previous = entries.at(-1);
    if (previous?.speaker === stream.speaker) {
      previous.text = `${previous.text} ${stream.text}`;
    } else {
      entries.push({ ...stream });
    }
  }
  return entries;
}
