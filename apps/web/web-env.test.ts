import { spawnSync } from "node:child_process";
import { describe, expect, test } from "bun:test";

describe("web environment", () => {
	test("accepts the documented placeholder for optional modal transcription", () => {
		const result = spawnSync(
			process.execPath,
			[
				"--eval",
				'import("@opencut-ai/env/web").then(({ webEnv }) => process.exit(webEnv.MODAL_TRANSCRIPTION_URL === undefined ? 0 : 1)).catch(() => process.exit(1))',
			],
			{
				cwd: import.meta.dirname,
				env: {
					...process.env,
					NODE_ENV: "test",
					DATABASE_URL: "postgresql://localhost:5432/test",
					BETTER_AUTH_SECRET: "test-secret",
					MODAL_TRANSCRIPTION_URL: "your_modal_url_here",
				},
				encoding: "utf8",
			},
		);

		expect(result.status).toBe(0);
	});
});
