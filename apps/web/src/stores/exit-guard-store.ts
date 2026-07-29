import { create } from "zustand";

interface ExitGuardState {
	isOpen: boolean;
	onConfirm: (() => void) | null;
	requestExit: (action: () => void) => void;
	resolve: (confirmed: boolean) => void;
}

export const useExitGuardStore = create<ExitGuardState>()((set, get) => ({
	isOpen: false,
	onConfirm: null,
	requestExit: (action) => set({ isOpen: true, onConfirm: action }),
	resolve: (confirmed) => {
		const { onConfirm } = get();
		set({ isOpen: false, onConfirm: null });
		if (confirmed) onConfirm?.();
	},
}));
