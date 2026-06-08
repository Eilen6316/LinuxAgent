import { readFile } from "node:fs/promises";
import { resolve } from "node:path";

const PROMPT_NAME_PATTERN = /^(?:[a-z0-9_-]+\/)*[a-z0-9_-]+\.md$/;

export class PromptLoader {
  private readonly root: string;

  constructor(root = resolve(process.cwd(), "prompts")) {
    this.root = resolve(root);
  }

  async load(name: string): Promise<string> {
    if (!PROMPT_NAME_PATTERN.test(name)) {
      throw new Error(`invalid prompt name: ${name}`);
    }

    return await readFile(resolve(this.root, name), "utf8");
  }
}
