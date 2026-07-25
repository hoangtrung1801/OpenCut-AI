import { afterEach, describe, expect, test } from "bun:test";
import { PlaybackManager } from "@/core/managers/playback-manager";

type MockEditor = {
	timeline: {
		getTotalDuration: () => number;
	};
};

const originalRequestAnimationFrame = globalThis.requestAnimationFrame;
const originalCancelAnimationFrame = globalThis.cancelAnimationFrame;
const originalPerformanceNow = performance.now;
const originalWindow = globalThis.window;

afterEach(() => {
	globalThis.requestAnimationFrame = originalRequestAnimationFrame;
	globalThis.cancelAnimationFrame = originalCancelAnimationFrame;
	performance.now = originalPerformanceNow;
	globalThis.window = originalWindow;
});

describe("PlaybackManager", () => {
	test("normal playback advances timeline time at 1x", () => {
		let now = 1_000;
		let nextFrame: FrameRequestCallback | null = null;

		performance.now = () => now;
		globalThis.requestAnimationFrame = (callback) => {
			nextFrame = callback;
			return 1;
		};
		globalThis.cancelAnimationFrame = () => {};
		globalThis.window = {
			dispatchEvent: () => true,
		} as unknown as Window & typeof globalThis;

		const editor = {
			timeline: {
				getTotalDuration: () => 10,
			},
		} as MockEditor;
		const playback = new PlaybackManager(editor as never);

		playback.play();
		now += 1_000;
		const frame = nextFrame as FrameRequestCallback | null;
		if (!frame) throw new Error("Expected playback to schedule an animation frame");
		frame(now);

		expect(playback.getCurrentTime()).toBe(1);
		expect(playback.getShuttleSpeed()).toBe(1);
		expect(playback.getShuttleDirection()).toBeNull();
	});
});
