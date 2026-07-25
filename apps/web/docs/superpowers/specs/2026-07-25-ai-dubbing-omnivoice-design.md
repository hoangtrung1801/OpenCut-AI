# AI Dubbing OmniVoice Voice Design

## Scope

Update `src/components/editor/panels/assets/views/ai-dubbing.tsx` so the AI Dubbing panel uses the local OmniVoice TTS flow. Sarvam AI and Smallest AI remain available to other product surfaces, but cannot be selected from this panel.

## User experience

- The panel defaults to the local engine.
- The local voice control is an optional voice-design text field.
- An empty field means OmniVoice Auto voice: the request omits both speaker configuration fields.
- A non-empty field is sent as `speaker`, allowing descriptions such as `female, young adult, high pitch, british accent`.
- Supporting guidance explains that the field accepts gender, age, pitch, style, accents, and Chinese dialect descriptions.

## Architecture and data flow

The panel passes the optional voice-design value through the existing `useAIDubbing` hook. The dubbing hook keeps the existing `DubbingOptions` shape compatible with other callers while allowing the local voice value to be absent. For local generation, it builds a TTS request with `text` and `language`, adding `speaker` only when the trimmed voice-design value is non-empty. Sarvam and Smallest branches remain unchanged for compatibility with other callers.

## Validation and error handling

Whitespace-only voice designs are treated as empty and use OmniVoice Auto voice. Existing transcript, source/target language, progress, and generation error handling remain unchanged.

## Testing

Add focused tests around the local request construction or generation path that verify:

1. An empty or whitespace-only design does not include `speaker`.
2. A populated design is passed as the trimmed `speaker` value.

Run the focused tests and the repository lint/type validation available for the web app.
