import * as fs from "node:fs";
import * as path from "node:path";

export class MemoryManager {
  private readonly memoryDir: string;
  private readonly memoryFile: string;
  private readonly soulFile: string;
  private readonly logsDir: string;

  constructor(memoryDir: string = "./data/memory") {
    this.memoryDir = memoryDir;
    this.memoryFile = path.join(memoryDir, "MEMORY.md");
    this.soulFile = path.join(memoryDir, "SOUL.md");
    this.logsDir = path.join(memoryDir, "logs");
  }

  ensureDir(): void {
    fs.mkdirSync(this.memoryDir, { recursive: true });
    fs.mkdirSync(this.logsDir, { recursive: true });
  }

  readMemory(): string {
    try {
      return fs.readFileSync(this.memoryFile, "utf-8");
    } catch {
      return "";
    }
  }

  writeMemory(content: string): void {
    fs.writeFileSync(this.memoryFile, content, "utf-8");
  }

  appendToMemory(entry: string): void {
    const timestamp = new Date().toISOString();
    const line = `\n- [${timestamp}] ${entry}`;

    let existing = this.readMemory();

    if (!existing) {
      existing = "# AutoSwarm Office Memory\n\n## Log Entries\n";
    }

    this.writeMemory(existing + line);
  }

  readSoul(): string {
    try {
      return fs.readFileSync(this.soulFile, "utf-8");
    } catch {
      return "";
    }
  }

  writeDailyLog(entries: string[]): void {
    const date = new Date().toISOString().split("T")[0];
    const logFile = path.join(this.logsDir, `${date}.md`);

    const header = `# Daily Log: ${date}\n\n`;
    const body = entries.map((e) => `- ${e}`).join("\n");
    const content = header + body + "\n";

    fs.writeFileSync(logFile, content, "utf-8");
  }

  rotateLogs(keepDays: number = 30): void {
    const cutoff = new Date();
    cutoff.setDate(cutoff.getDate() - keepDays);

    let files: string[];
    try {
      files = fs.readdirSync(this.logsDir);
    } catch {
      return;
    }

    for (const file of files) {
      if (!file.endsWith(".md")) {
        continue;
      }

      const dateStr = file.replace(".md", "");
      const fileDate = new Date(dateStr);

      if (isNaN(fileDate.getTime())) {
        continue;
      }

      if (fileDate < cutoff) {
        const filePath = path.join(this.logsDir, file);
        fs.unlinkSync(filePath);
        console.log(`[memory] Rotated old log: ${file}`);
      }
    }
  }
}
