import { create } from "zustand";
import { persist } from "zustand/middleware";

export interface ClonedVoice {
	id: string;
	name: string;
	path: string;
	createdAt: number;
}

interface VoiceLibraryState {
	voices: ClonedVoice[];
	addVoice: (voice: ClonedVoice) => void;
	removeVoice: (id: string) => void;
}

export const useVoiceLibraryStore = create<VoiceLibraryState>()(
	persist(
		(set) => ({
			voices: [],

			addVoice: (voice) =>
				set((state) => {
					const withoutSameName = state.voices.filter(
						(v) => v.name !== voice.name,
					);
					return { voices: [...withoutSameName, voice] };
				}),

			removeVoice: (id) =>
				set((state) => ({
					voices: state.voices.filter((v) => v.id !== id),
				})),
		}),
		{
			name: "voice-library",
		},
	),
);
