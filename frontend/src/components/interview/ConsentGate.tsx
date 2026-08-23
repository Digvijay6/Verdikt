/**
 * Consent gate — shown before the candidate joins the interview.
 *
 * GDPR Art. 9 / IL BIPA / NY AEDTA all require explicit opt-in for voice
 * recording, AI analysis, and biometric processing. This screen discloses
 * what is recorded, how it's used, how long it's kept, and how to request
 * deletion.
 */

interface ConsentGateProps {
  onAccept: () => void;
  error?: string | null;
}

export function ConsentGate({ onAccept, error }: ConsentGateProps) {
  return (
    <div className="flex items-center justify-center min-h-screen bg-gray-50 px-4">
      <div className="max-w-lg w-full bg-white rounded-xl shadow-sm p-8">
        <h1 className="text-xl font-semibold text-gray-900 mb-4">
          Before we begin
        </h1>

        <div className="space-y-4 text-sm text-gray-600">
          <p>
            This interview is conducted by an AI interviewer. Your voice will be
            recorded, transcribed, and analysed to produce a score for the
            recruiter.
          </p>

          <div className="border-l-2 border-gray-200 pl-4 space-y-1">
            <p><strong>What we record:</strong> Audio of the interview conversation.</p>
            <p><strong>What we analyse:</strong> Your answers against a scoring rubric.</p>
            <p><strong>How long we keep it:</strong> Audio for 90 days, transcripts and scores for 12 months.</p>
            <p><strong>Your rights:</strong> You can request deletion of your data at any time by contacting the recruiter.</p>
          </div>

          <p className="text-gray-500">
            By clicking "Start interview" you consent to the above. You can
            withdraw at any point during the interview by ending the call.
          </p>
        </div>

        {error && (
          <p className="text-sm text-red-600 mt-4">{error}</p>
        )}

        <button
          onClick={onAccept}
          className="mt-6 w-full py-3 bg-gray-900 text-white rounded-lg font-medium hover:bg-gray-800 transition"
        >
          Start interview
        </button>
      </div>
    </div>
  );
}