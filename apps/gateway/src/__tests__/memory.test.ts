import { describe, it, expect, beforeEach, afterEach } from "vitest";
import * as fs from "node:fs";
import * as path from "node:path";
import * as os from "node:os";
import { MemoryManager } from "../memory";

describe("MemoryManager", () => {
  let tmpDir: string;
  let manager: MemoryManager;

  beforeEach(() => {
    // Create a unique temporary directory for each test to avoid cross-test
    // contamination. The directory is cleaned up in afterEach.
    tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), "autoswarm-memory-test-"));
    manager = new MemoryManager(tmpDir);
    manager.ensureDir();
  });

  afterEach(() => {
    // Clean up the temporary directory and all its contents
    fs.rmSync(tmpDir, { recursive: true, force: true });
  });

  // -------------------------------------------------------------------------
  // readMemory
  // -------------------------------------------------------------------------
  describe("readMemory", () => {
    it("returns empty string when memory file does not exist", () => {
      // The ensureDir creates the directory but not the MEMORY.md file
      const result = manager.readMemory();
      expect(result).toBe("");
    });

    it("returns file content when memory file exists", () => {
      const memoryFile = path.join(tmpDir, "MEMORY.md");
      fs.writeFileSync(memoryFile, "# Existing Memory\n\nSome content here.");
      const result = manager.readMemory();
      expect(result).toBe("# Existing Memory\n\nSome content here.");
    });
  });

  // -------------------------------------------------------------------------
  // writeMemory
  // -------------------------------------------------------------------------
  describe("writeMemory", () => {
    it("creates the memory file with the given content", () => {
      manager.writeMemory("# New Memory\n\nFirst entry.");
      const memoryFile = path.join(tmpDir, "MEMORY.md");
      const content = fs.readFileSync(memoryFile, "utf-8");
      expect(content).toBe("# New Memory\n\nFirst entry.");
    });

    it("overwrites existing content", () => {
      manager.writeMemory("old content");
      manager.writeMemory("new content");
      expect(manager.readMemory()).toBe("new content");
    });
  });

  // -------------------------------------------------------------------------
  // writeMemory + readMemory roundtrip
  // -------------------------------------------------------------------------
  describe("writeMemory / readMemory roundtrip", () => {
    it("reads back exactly what was written", () => {
      const content =
        "# AutoSwarm Office Memory\n\n## Log Entries\n\n- Entry one\n- Entry two";
      manager.writeMemory(content);
      expect(manager.readMemory()).toBe(content);
    });

    it("handles empty string write and read", () => {
      manager.writeMemory("");
      expect(manager.readMemory()).toBe("");
    });

    it("handles unicode content", () => {
      const content = "# Memory\n\nAgent status: working hard";
      manager.writeMemory(content);
      expect(manager.readMemory()).toBe(content);
    });
  });

  // -------------------------------------------------------------------------
  // appendToMemory
  // -------------------------------------------------------------------------
  describe("appendToMemory", () => {
    it("creates header and appends timestamped entry when memory is empty", () => {
      manager.appendToMemory("Agent deployed successfully");
      const result = manager.readMemory();

      // Should contain the auto-generated header
      expect(result).toContain("# AutoSwarm Office Memory");
      expect(result).toContain("## Log Entries");

      // Should contain the entry text
      expect(result).toContain("Agent deployed successfully");

      // Should contain an ISO timestamp in brackets
      const isoTimestampPattern = /\[\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}/;
      expect(result).toMatch(isoTimestampPattern);
    });

    it("appends to existing content without overwriting", () => {
      manager.writeMemory("# AutoSwarm Office Memory\n\n## Log Entries\n");
      manager.appendToMemory("First entry");
      manager.appendToMemory("Second entry");

      const result = manager.readMemory();
      expect(result).toContain("First entry");
      expect(result).toContain("Second entry");
    });

    it("preserves existing non-empty memory content", () => {
      const existingContent =
        "# AutoSwarm Office Memory\n\n## Log Entries\n\n- [2026-03-01T00:00:00.000Z] Initial setup";
      manager.writeMemory(existingContent);
      manager.appendToMemory("New event");

      const result = manager.readMemory();
      expect(result).toContain("Initial setup");
      expect(result).toContain("New event");
    });

    it("formats each entry as a markdown list item", () => {
      manager.appendToMemory("Test entry");
      const result = manager.readMemory();

      // Each appended entry starts with "\n- [timestamp] entry"
      const entryPattern = /\n- \[\d{4}-\d{2}-\d{2}T.+?\] Test entry/;
      expect(result).toMatch(entryPattern);
    });
  });

  // -------------------------------------------------------------------------
  // readSoul
  // -------------------------------------------------------------------------
  describe("readSoul", () => {
    it("returns empty string when soul file does not exist", () => {
      expect(manager.readSoul()).toBe("");
    });

    it("returns content of the SOUL.md file", () => {
      const soulFile = path.join(tmpDir, "SOUL.md");
      fs.writeFileSync(soulFile, "# Agent Soul\n\nCore identity.");
      expect(manager.readSoul()).toBe("# Agent Soul\n\nCore identity.");
    });
  });

  // -------------------------------------------------------------------------
  // writeDailyLog
  // -------------------------------------------------------------------------
  describe("writeDailyLog", () => {
    it("creates a date-stamped log file in the logs directory", () => {
      const entries = ["Task completed", "Code reviewed", "Tests passed"];
      manager.writeDailyLog(entries);

      const today = new Date().toISOString().split("T")[0];
      const logFile = path.join(tmpDir, "logs", `${today}.md`);
      expect(fs.existsSync(logFile)).toBe(true);

      const content = fs.readFileSync(logFile, "utf-8");
      expect(content).toContain(`# Daily Log: ${today}`);
      expect(content).toContain("- Task completed");
      expect(content).toContain("- Code reviewed");
      expect(content).toContain("- Tests passed");
    });

    it("formats entries as markdown list items", () => {
      manager.writeDailyLog(["Entry A", "Entry B"]);

      const today = new Date().toISOString().split("T")[0];
      const logFile = path.join(tmpDir, "logs", `${today}.md`);
      const content = fs.readFileSync(logFile, "utf-8");

      expect(content).toContain("- Entry A\n- Entry B");
    });
  });

  // -------------------------------------------------------------------------
  // rotateLogs
  // -------------------------------------------------------------------------
  describe("rotateLogs", () => {
    it("removes log files older than the keep threshold", () => {
      const logsDir = path.join(tmpDir, "logs");

      // Create an old log file (45 days ago)
      const oldDate = new Date();
      oldDate.setDate(oldDate.getDate() - 45);
      const oldDateStr = oldDate.toISOString().split("T")[0];
      fs.writeFileSync(
        path.join(logsDir, `${oldDateStr}.md`),
        "# Old log"
      );

      // Create a recent log file (5 days ago)
      const recentDate = new Date();
      recentDate.setDate(recentDate.getDate() - 5);
      const recentDateStr = recentDate.toISOString().split("T")[0];
      fs.writeFileSync(
        path.join(logsDir, `${recentDateStr}.md`),
        "# Recent log"
      );

      manager.rotateLogs(30);

      expect(fs.existsSync(path.join(logsDir, `${oldDateStr}.md`))).toBe(
        false
      );
      expect(fs.existsSync(path.join(logsDir, `${recentDateStr}.md`))).toBe(
        true
      );
    });

    it("does not crash when logs directory is empty", () => {
      expect(() => manager.rotateLogs(30)).not.toThrow();
    });

    it("ignores non-md files in the logs directory", () => {
      const logsDir = path.join(tmpDir, "logs");
      fs.writeFileSync(path.join(logsDir, "readme.txt"), "Not a log");

      // Should not throw or delete non-md files
      expect(() => manager.rotateLogs(0)).not.toThrow();
      expect(fs.existsSync(path.join(logsDir, "readme.txt"))).toBe(true);
    });
  });

  // -------------------------------------------------------------------------
  // ensureDir
  // -------------------------------------------------------------------------
  describe("ensureDir", () => {
    it("creates memory directory and logs subdirectory", () => {
      const freshDir = path.join(tmpDir, "fresh-memory");
      const freshManager = new MemoryManager(freshDir);
      freshManager.ensureDir();

      expect(fs.existsSync(freshDir)).toBe(true);
      expect(fs.existsSync(path.join(freshDir, "logs"))).toBe(true);
    });

    it("does not throw if directories already exist", () => {
      // ensureDir was already called in beforeEach; calling again should be safe
      expect(() => manager.ensureDir()).not.toThrow();
    });
  });
});
