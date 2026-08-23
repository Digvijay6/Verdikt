/**
 * Interview complete — shown when the interview ends.
 * The candidate sees a simple thank-you; no feedback on performance.
 */

export function InterviewComplete() {
  return (
    <div className="flex items-center justify-center min-h-screen bg-gray-50">
      <div className="max-w-md text-center">
        <div className="w-16 h-16 mx-auto mb-6 rounded-full bg-green-100 flex items-center justify-center">
          <svg
            className="w-8 h-8 text-green-600"
            fill="none"
            viewBox="0 0 24 24"
            stroke="currentColor"
            strokeWidth={2}
          >
            <path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" />
          </svg>
        </div>
        <h1 className="text-xl font-semibold text-gray-900 mb-2">
          Interview complete
        </h1>
        <p className="text-sm text-gray-600 mb-6">
          Thank you for your time. Your recruiter will follow up with next steps.
        </p>
        <p className="text-xs text-gray-400">
          You can close this window.
        </p>
      </div>
    </div>
  );
}