# Transcript Translation Auto-Selection Design

## Goal

After transcript translation completes, show only the translated transcript text
in the transcript panel. Preserve the original transcript unchanged for later
use and keep it accessible through its original-language tab.

## Existing State

- `useTranscriptStore.segments` contains the original transcription.
- `useTranscriptStore.translations` contains translated transcripts by language.
- `TextEditingPanel` already renders the original and translations in separate
  language tabs.
- Translation currently stores the translated transcript without changing the
  active tab, so the panel can continue showing the original.

## Design

Keep the existing state model. Do not copy, replace, or mutate the original
segments.

When the translations collection changes, `TextEditingPanel` selects the most
recent translated language. Its existing `TranslationView` renders only the
translated text. The original-language tab remains available and selects the
untouched source transcript.

This also applies when translating again into an existing language: the
replacement translation becomes active even though the number of translations
does not increase.

Removing a translation continues to fall back to the original transcript when
the active language is no longer available.

## Data Flow

1. Translation completes.
2. `addTranslation` replaces or appends the target-language entry.
3. `TextEditingPanel` observes the changed translations collection.
4. The panel selects the most recently stored target language.
5. `TranslationView` displays its translated segments only.
6. Original segments remain in `useTranscriptStore.segments`.

## Error Handling

Failed translations do not update the translations collection, so the active
transcript view does not change. If an active translation is removed, the
existing validity check displays the original transcript.

## Testing

Add a focused component regression test that:

- starts on the original transcript;
- adds a translation and verifies the translated text becomes visible;
- verifies the original text is not shown in the translated view;
- selects the original-language tab and verifies the original text remains
  available;
- replaces an existing target-language translation and verifies the updated
  translation becomes active.

No backend, schema, or translation API changes are required.
