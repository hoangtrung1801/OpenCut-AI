"use client";

import { useEffect, useState } from "react";
import { storageService } from "@/services/storage/service";
import { useTranscriptStore } from "@/stores/transcript-store";
import {
	createTranscriptSnapshot,
	normalizeTranscriptSnapshot,
} from "@/lib/transcription/transcript-persistence";

export function useTranscriptPersistence(projectId: string | null): boolean {
	const [hydratedProjectId, setHydratedProjectId] = useState<string | null>(
		null,
	);

	useEffect(() => {
		if (!projectId) {
			setHydratedProjectId(null);
			return;
		}

		let cancelled = false;
		let ready = false;
		let saveTimer: ReturnType<typeof setTimeout> | undefined;

		setHydratedProjectId(null);
		useTranscriptStore.getState().reset();

		const save = () => {
			void storageService
				.saveTranscript({
					projectId,
					transcript: createTranscriptSnapshot(useTranscriptStore.getState()),
				})
				.catch(() => undefined);
		};

		const unsubscribe = useTranscriptStore.subscribe((state) => {
			if (!ready || cancelled) return;
			if (saveTimer) clearTimeout(saveTimer);
			saveTimer = setTimeout(save, 250);
		});

		void storageService
			.loadTranscript({ projectId })
			.then((stored) => {
				if (cancelled) return;
				const transcript = normalizeTranscriptSnapshot(stored);
				if (transcript) {
					useTranscriptStore
						.getState()
						.restorePersistedTranscript(transcript);
				}
				ready = true;
				setHydratedProjectId(projectId);
			})
			.catch(() => {
				if (cancelled) return;
				ready = true;
				setHydratedProjectId(projectId);
			});

		return () => {
			cancelled = true;
			unsubscribe();
			if (saveTimer) clearTimeout(saveTimer);
			if (ready) save();
		};
	}, [projectId]);

	return hydratedProjectId === projectId;
}
