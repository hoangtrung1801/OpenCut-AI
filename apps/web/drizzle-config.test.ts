import { spawnSync } from "node:child_process";
import { describe, expect, test } from "bun:test";

describe("Drizzle configuration", () => {
	test("loads local environment variables and database schemas", () => {
		const environment = { ...process.env };
		delete environment.DATABASE_URL;
		delete environment.BETTER_AUTH_SECRET;

		const result = spawnSync(
			process.execPath,
			[
				"--eval",
				'import("./drizzle.config.ts").then(({ default: config }) => process.exit(JSON.stringify(config.schema) === JSON.stringify(["./src/lib/db/schema.ts", "./src/lib/db/schema-version-control.ts"]) ? 0 : 1)).catch(() => process.exit(1))',
			],
			{
				cwd: import.meta.dirname,
				env: { ...environment, NODE_ENV: "development" },
				encoding: "utf8",
			},
		);

		expect(result.status).toBe(0);
	});
});
