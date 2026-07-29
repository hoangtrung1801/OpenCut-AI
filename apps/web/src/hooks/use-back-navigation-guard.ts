import { useEffect } from "react";
import { useExitGuardStore } from "@/stores/exit-guard-store";

const HISTORY_GUARD_STATE = { __editorExitGuard: true } as const;

export function useBackNavigationGuard() {
	const requestExit = useExitGuardStore((s) => s.requestExit);

	useEffect(() => {
		// Depth tracks how many sentinel entries sit on top of the real
		// history entry, so `history.go(-depth)` lands back on real content
		// however many times the guard has intercepted a back navigation.
		let depth = 1;

		// Skip the push if a sentinel is already the current entry (e.g. a
		// React Strict Mode double-invoked mount) — otherwise we'd stack a
		// second sentinel the guard doesn't know about, breaking `depth`.
		const currentState = window.history.state as
			| { __editorExitGuard?: boolean }
			| null;
		if (!currentState?.__editorExitGuard) {
			window.history.pushState(
				HISTORY_GUARD_STATE,
				"",
				window.location.href,
			);
		}

		const handlePopState = () => {
			if (useExitGuardStore.getState().isOpen) return;
			depth += 1;

			window.history.pushState(
				HISTORY_GUARD_STATE,
				"",
				window.location.href,
			);

			requestExit(() => {
				window.removeEventListener("popstate", handlePopState);
				window.history.go(-depth);
			});
		};

		window.addEventListener("popstate", handlePopState);
		return () => window.removeEventListener("popstate", handlePopState);
	}, [requestExit]);
}
