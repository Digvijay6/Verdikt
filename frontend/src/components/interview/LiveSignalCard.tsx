/**
 * Live signal card — shows a provisional correctness score per question.
 * Clearly marked "live estimate" — the final score is computed post-call.
 */

interface LiveSignalCardProps {
  questionId: string;
  score: number;
}

export function LiveSignalCard({ questionId, score }: LiveSignalCardProps) {
  const band = getBand(score);
  const color = getColor(score);

  return (
    <div className="border rounded-lg p-3">
      <div className="flex items-center justify-between mb-1">
        <span className="text-xs font-medium text-gray-500">
          {questionId}
        </span>
        <span className={`text-xs px-2 py-0.5 rounded-full ${color}`}>
          {band}
        </span>
      </div>
      <div className="flex items-baseline gap-1">
        <span className="text-2xl font-bold text-gray-900">{score}</span>
        <span className="text-sm text-gray-400">/ 100</span>
      </div>
      <p className="text-xs text-gray-400 mt-1">Provisional — live estimate</p>
    </div>
  );
}

function getBand(score: number): string {
  if (score >= 90) return "Expert";
  if (score >= 70) return "Strong";
  if (score >= 50) return "Adequate";
  if (score >= 25) return "Weak";
  return "Poor";
}

function getColor(score: number): string {
  if (score >= 70) return "bg-green-100 text-green-700";
  if (score >= 50) return "bg-yellow-100 text-yellow-700";
  if (score >= 25) return "bg-orange-100 text-orange-700";
  return "bg-red-100 text-red-700";
}