import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

/**
 * Unit tests for the web app.
 *
 * `e2e/` is excluded on purpose: those are Playwright specs, and Vitest
 * would collect them and then hang waiting for a browser that never comes.
 */
export default defineConfig({
    plugins: [react()],
    test: {
        environment: "jsdom",
        setupFiles: ["./vitest.setup.ts"],
        include: ["**/*.test.ts", "**/*.test.tsx"],
        exclude: ["node_modules/**", ".next/**", "e2e/**"],
        // The builder's page suites mount antd and React Flow with F2's 70
        // cards: the first test of a file also pays the cold import (about
        // 3 s), which put it at the 5 s default on a loaded machine
        // (workflow-builder-ui 04).
        testTimeout: 20_000,
    },
});
