export const INCOMPLETE_END_WARNING =
  "Ending now will submit this interview as incomplete. Do you want to end the call?";

export function canEndCall(
  questionsComplete: boolean,
  confirm: (message: string) => boolean,
): boolean {
  return questionsComplete || confirm(INCOMPLETE_END_WARNING);
}
