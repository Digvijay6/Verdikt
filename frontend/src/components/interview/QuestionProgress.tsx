/**
 * Question progress indicator — "Question 3 of 7".
 */

interface QuestionProgressProps {
  current: number;
  total: number;
}

export function QuestionProgress({ current, total }: QuestionProgressProps) {
  if (total === 0) {
    return (
      <span className="text-sm text-gray-500">
        Question {current + 1}
      </span>
    );
  }

  return (
    <div className="flex items-center gap-2">
      <div className="flex gap-1">
        {Array.from({ length: total }).map((_, i) => (
          <div
            key={i}
            className={`w-2 h-2 rounded-full ${
              i < current ? "bg-gray-900" : "bg-gray-200"
            }`}
          />
        ))}
      </div>
      <span className="text-sm text-gray-500">
        {current} / {total}
      </span>
    </div>
  );
}