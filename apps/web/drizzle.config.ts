import type { Config } from "drizzle-kit";
import "./drizzle-env";

const databaseUrl = process.env.DATABASE_URL;

if (!databaseUrl) {
	throw new Error("DATABASE_URL is required to load the Drizzle configuration");
}

export default {
	schema: ["./src/lib/db/schema.ts", "./src/lib/db/schema-version-control.ts"],
	dialect: "postgresql",
	migrations: {
		table: "drizzle_migrations",
	},
	dbCredentials: {
		url: databaseUrl,
	},
	out: "./migrations",
	strict: process.env.NODE_ENV === "production",
} satisfies Config;
