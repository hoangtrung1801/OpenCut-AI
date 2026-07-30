# Contextual Translation and Caption Layout Design

## Goal

Produce natural, concise contextual translations and readable display captions
without repeating source or target text. A display cue may contain at most two
lines, and each line may contain at most 32 weighted characters.

This design keeps the existing `/api/translations/contextual` request and
response schema. Parent translations remain suitable for dubbing, while
`display_segments` and generated subtitle documents carry the display-only
splits.

## Root Cause

The current postprocessor uses whitespace tokens to find source split
boundaries. Chinese text normally has no spaces, so a target-length overflow can
split the source immediately before its final punctuation or character.
Recursive passes then produce punctuation-only or one-character pieces.

When a short source cannot be split further, the target-only fallback copies the
entire source into every generated cue. The minimum-duration merge then combines
pieces with newline characters. Together, these behaviors cause duplicated
source text, repeated translated words, and captions containing more than two
lines.

The translation prompt also requests faithful translation but does not require
concise, subtitle-ready target text or forbid line breaks.

## Translation Contract

The contextual translation prompt will require every returned translation to:

- be natural and idiomatic in the target language;
- be concise enough for on-screen captions without omitting meaning;
- preserve cross-segment continuity when a sentence spans adjacent IDs;
- contain no embedded newline characters; and
- retain each input ID exactly once and in order.

Translation validation will collapse repeated whitespace and reject empty
results. Parent `segments` and `audio_segments` keep the translated text and
original timing granularity used by dubbing.

## Display Caption Policy

Each display cue must satisfy all of these rules:

- at most two lines;
- at most 32 weighted characters per line;
- line breaks only at target-language word or punctuation boundaries;
- no empty or punctuation-only cue;
- no duplicated source or translated content;
- monotonic timing contained within its parent segment; and
- no overlap with an adjacent display cue.

The existing multilingual character weights remain in use. The effective
capacity of one cue is two lines, but each individual line must still satisfy
the 32-character limit.

## Source Splitting

Source splitting will prefer the supplied Whisper word stream:

1. Reconstruct each word's span within the source text.
2. Consider boundaries only between complete words.
3. Prefer sentence punctuation, then phrase punctuation or a meaningful pause,
   then the boundary closest to a balanced split.
4. Keep attached punctuation with the preceding word.

This works for Chinese words such as `今天`, `来了,`, and `什么` without relying
on whitespace.

If word reconstruction is unavailable, a deterministic Unicode fallback will
prefer punctuation and balanced character boundaries. It must never isolate
terminal punctuation when another valid boundary exists.

## Target Alignment and Wrapping

When one parent pair exceeds the two-line cue capacity:

1. Split the source into exact, timed source parts.
2. Ask the existing alignment backend to place boundaries in the already
   translated target text.
3. Require the aligned target parts, after whitespace normalization, to
   reconstruct the original target translation exactly and in order.
4. Retry invalid alignment through the existing correction retry mechanism.
5. Wrap each accepted target part into one or two balanced lines at natural
   target-language boundaries.

The alignment backend may choose boundaries but may not rewrite, repeat, omit,
or invent target content.

If alignment remains invalid after retries, the request fails with the existing
caption-alignment error instead of returning corrupted captions.

## Short Cue Handling

A short cue may merge with an adjacent cue from the same parent only when the
combined target still fits the two-line policy.

Merged source text uses the source language's natural joiner: no inserted space
for CJK text and one space for whitespace-delimited languages. Merged target
text uses a single normalized space and is wrapped again. Stored text is never
combined by stacking arbitrary newline-separated fragments.

If a short cue cannot merge without violating the policy, it remains separate.
The implementation will not sacrifice text integrity to meet the preferred
minimum duration.

## Subtitle Documents

`display_segments` contains the approved one- or two-line target text.
Source-only subtitle variants contain exact, non-duplicated source chunks.
Bilingual variants add the source/target separator only when serializing the
subtitle document.

No later serializer performs another semantic split.

## Error Handling

- Invalid translation IDs or empty translations use the existing translation
  validation retry path.
- Invalid alignment IDs, reconstruction mismatches, repeated content, or empty
  parts use the existing alignment correction retry path.
- Unsplittable content that cannot satisfy two lines raises
  `CaptionPolicyError`; partial or corrupted display captions are not returned.
- Provider failures retain the current sanitized 502/503 route responses.

## Testing

Regression coverage will include the supplied Chinese-to-Vietnamese payload and
assert that:

- normalized display source chunks reconstruct each original source exactly;
- normalized display target chunks reconstruct each parent translation exactly;
- no source chunk is duplicated;
- no cue is empty or punctuation-only;
- each target cue contains at most two lines;
- each target line is at most 32 weighted characters;
- cue timestamps are ordered and stay within the parent range;
- parent `segments` and `audio_segments` remain unchanged; and
- generated SRT/VTT variants contain the same corrected display text.

Focused unit tests will also cover CJK word-boundary splitting, punctuation
attachment, balanced Vietnamese wrapping, invalid alignment reconstruction, and
short-cue merging.

## Scope

This change does not alter transcription segmentation, dubbing granularity,
public API schemas, or UI controls. Correcting an ASR word itself remains the
responsibility of the transcription stage; contextual translation only ensures
that imperfect adjacent source segments are translated coherently.
