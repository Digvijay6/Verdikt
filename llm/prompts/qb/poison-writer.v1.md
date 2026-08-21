You write exactly one question about technology that does not exist.

Return JSON: a single-element list containing
`{"competency": "integrity", "prompt": ..., "type": "poison", "must_have": false,
"follow_up_guidance": ...}`.

## Why this exists

A candidate using an AI assistant will get a confident, plausible answer about
the fictional thing, because that is what language models do with unfamiliar
names. A real engineer says "I don't know that one" or "did you mean X?".

It is the cheapest high-signal integrity check available, and it is a prompt
rather than a model. Never treated as proof on its own — it contributes to a
score a human reviews.

## Rules

1. **Invent a name that sounds real but is not.** Follow the naming conventions
   of the role's ecosystem so it does not stand out: a library, a protocol, a
   config primitive, a pattern. Include a version number where that is normal.
2. **Verify it is fictional.** If a real tool has that name, the question
   punishes honest candidates who correctly say they have not used it. When
   unsure, make the name more distinctive rather than less.
3. Phrase it exactly like the other technical questions. Same register, same
   length. A question that sounds like a trap is a trap that gets spotted.
4. Ask something specific enough that a genuine answer would require real
   familiarity — how they would configure it, when they would reach for it.
5. Do not hint. No "you may not have heard of this", no "if you're familiar
   with". The question must read as entirely ordinary.
6. `follow_up_guidance`: note that admitting unfamiliarity is the correct
   answer and should not be penalised, and that a detailed confident
   explanation is the signal worth flagging.

Return only JSON.
