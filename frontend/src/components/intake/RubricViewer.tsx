/**
 * The job's scoring rubric, readable.
 *
 * This screen is load-bearing for D35. Once questions are generated per
 * candidate, nobody reviews two thousand question sets — so the rubric becomes
 * the thing a human actually checks, and compliance.md now says as much. A
 * rubric that cannot be read is a promise we do not keep.
 *
 * So it shows every anchor, not a summary. The specific thing a reviewer is
 * looking for is an anchor that names a technology ("mentions idempotency
 * keys"), because that one marks a candidate down for a correct answer about a
 * system they built differently.
 */

import { motion } from "motion/react";
import { useState } from "react";

import { Pill } from "./primitives";

export type Dimension = {
  key: string;
  weight: number;
  anchors: Record<string, string>;
};

export type Competency = {
  key: string;
  name: string;
  why: string;
  kind: "technical" | "behavioral";
  must_have: boolean;
  weight: number;
  dimensions: Dimension[];
};

export type Rubric = { competencies: Competency[]; version: string };

const pct = (n: number) => `${Math.round(n * 100)}%`;

export function RubricViewer({ rubric }: { rubric: Rubric }) {
  const [open, setOpen] = useState<string | null>(
    rubric.competencies[0]?.key ?? null,
  );

  // Should be 1.0. Surfaced rather than silently normalised: a rubric whose
  // weights do not sum is a generation bug, and hiding it means scores are
  // quietly scaled wrong.
  const total = rubric.competencies.reduce((sum, c) => sum + c.weight, 0);
  const off = Math.abs(total - 1) > 0.02;

  return (
    <div>
      <div className="mb-4 flex flex-wrap items-center gap-2">
        <Pill tone="cool">{rubric.version}</Pill>
        <Pill>{rubric.competencies.length} competencies</Pill>
        <Pill tone={off ? "attention" : "good"}>weights {pct(total)}</Pill>
        {off && (
          <span className="error text-sm">
            Weights should total 100%. Rebuild the rubric.
          </span>
        )}
      </div>

      <ul className="m-0 list-none space-y-3 p-0">
        {rubric.competencies.map((c) => {
          const isOpen = open === c.key;
          return (
            <li
              key={c.key}
              className="overflow-hidden rounded-[1.25rem] border-2 border-ink bg-panel"
            >
              <button
                onClick={() => setOpen(isOpen ? null : c.key)}
                aria-expanded={isOpen}
                className="flex w-full flex-wrap items-center gap-2 border-none bg-transparent p-3.5 text-left"
              >
                <span className="font-extrabold">{c.name}</span>
                {c.must_have && <Pill tone="attention">must-have</Pill>}
                <Pill tone={c.kind === "technical" ? "good" : "cool"}>
                  {c.kind}
                </Pill>
                <span className="ml-auto flex items-center gap-3">
                  <b className="tabular-nums">{pct(c.weight)}</b>
                  <span aria-hidden className="text-lg leading-none">
                    {isOpen ? "−" : "+"}
                  </span>
                </span>
              </button>

              {/* The competency key, shown deliberately: it is what each
                  generated question is tagged with, so it is the join between
                  a candidate's question and the anchors it was scored on. */}
              <div className="border-t-2 border-ink/10 px-3.5 pb-2 text-xs">
                <code className="font-mono text-muted">{c.key}</code>
                <p className="hint mt-1 mb-2">{c.why}</p>
              </div>

              {isOpen && (
                <motion.div
                  initial={{ opacity: 0 }}
                  animate={{ opacity: 1 }}
                  className="border-t-2 border-ink bg-paper p-3.5"
                >
                  {c.dimensions.map((d) => (
                    <div key={d.key} className="mb-4 last:mb-0">
                      <div className="mb-1.5 flex items-baseline gap-2">
                        <b className="font-mono text-sm">{d.key}</b>
                        <span className="hint">{pct(d.weight)}</span>
                      </div>
                      <ol className="m-0 list-none space-y-1 p-0">
                        {[1, 2, 3, 4, 5].map((level) => (
                          <li
                            key={level}
                            className="flex gap-2.5 rounded-lg border-2 border-ink bg-panel px-2.5 py-1.5 text-sm"
                          >
                            <b
                              className="shrink-0 tabular-nums"
                              aria-label={`Level ${level}`}
                            >
                              {level}
                            </b>
                            <span>{d.anchors[String(level)]}</span>
                          </li>
                        ))}
                      </ol>
                    </div>
                  ))}
                </motion.div>
              )}
            </li>
          );
        })}
      </ul>
    </div>
  );
}
