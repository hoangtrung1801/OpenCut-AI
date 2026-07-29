import { Button } from "@/components/ui/button";
import {
	Dialog,
	DialogBody,
	DialogContent,
	DialogFooter,
	DialogHeader,
	DialogTitle,
} from "@/components/ui/dialog";
import { useExitGuardStore } from "@/stores/exit-guard-store";

export function ExitConfirmationDialog() {
	const isOpen = useExitGuardStore((s) => s.isOpen);
	const resolve = useExitGuardStore((s) => s.resolve);

	return (
		<Dialog open={isOpen} onOpenChange={(open) => !open && resolve(false)}>
			<DialogContent>
				<DialogHeader>
					<DialogTitle>Exit project?</DialogTitle>
				</DialogHeader>

				<DialogBody>
					<p className="text-sm text-muted-foreground">
						You'll be taken back to your projects. Your changes are saved
						automatically.
					</p>
				</DialogBody>

				<DialogFooter>
					<Button variant="outline" onClick={() => resolve(false)}>
						Cancel
					</Button>
					<Button onClick={() => resolve(true)}>Exit project</Button>
				</DialogFooter>
			</DialogContent>
		</Dialog>
	);
}
