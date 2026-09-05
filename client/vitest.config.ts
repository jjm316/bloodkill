import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

// 前端测试基建（.scratch/frontend-test-infra/spec.md）：与 vite.config.ts 分离，
// 测试运行不继承 dev 代理配置。
export default defineConfig({
  plugins: [react()],
  test: {
    environment: "jsdom",
    // RTL 依靠全局 afterEach 做自动 cleanup，必须开 globals
    globals: true,
    setupFiles: "./src/test/setup.ts",
  },
});
