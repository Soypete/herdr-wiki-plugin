# herdr-orchestrator evals

Eval cases for the herdr-orchestrator skill, portable across all three harnesses
(Claude Code, Codex, opencode).

## Run

From the repo root with the eval runner:

```sh
node scripts/run-evals.mjs --skill herdr-orchestrator --harness opencode --model <provider>/deepseek-ai/DeepSeek-V4-Flash --jobs 2 --out evals-out/herdr-orchestrator-deepseek-<date>
```

Replace `<provider>` with the opencode provider name configured in your
`opencode.json`. The provider must point at an OpenAI-compatible vLLM endpoint.
Example provider config (do not commit real hostnames or IPs):

```json
{
  "providers": {
    "my-provider": {
      "baseURL": "https://api.example.com/v1",
      "apiKey": "key-...",
      "defaultModel": "deepseek-ai/DeepSeek-V4-Flash"
    }
  }
}
```

Grading uses `claude -p` (the Claude Code CLI). Results land in
`evals-out/` — only the summary (`benchmark.md`, `benchmark.json`) is
committed to `evals/results/`.
