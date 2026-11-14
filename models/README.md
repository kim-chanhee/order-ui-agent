# Local model

- Model: Qwen2.5-Coder-7B-Instruct
- File: `qwen2.5-coder-7b-instruct-q4_k_m.gguf`
- Quantization: Q4_K_M
- SHA-256: `509287f78cb4d4cf6b3843734733b914b2c158e43e22a7f4bf5e963800894d3c`
- Source: https://huggingface.co/Qwen/Qwen2.5-Coder-7B-Instruct-GGUF

The GGUF file is excluded from Git. LM Studio also retains the original downloaded file; this folder contains a copy.

## Run with LM Studio

The model must be loaded and the local server running before starting the application:

```sh
lms load qwen2.5-coder-7b-instruct --identifier qwen2.5-coder-7b-instruct --context-length 32768 --gpu max --yes
lms server start --port 1234
```

Project `.env` settings:

```dotenv
AGENT_PROVIDER=lm_studio
AGENT_BASE_URL=http://127.0.0.1:1234/v1
AGENT_API_KEY=not-needed
AGENT_MODEL=qwen2.5-coder-7b-instruct
AGENT2UI_PLANNER_MODEL=qwen2.5-coder-7b-instruct
AGENT_TIMEOUT_SECONDS=180
FAST_SQL_TIMEOUT_SECONDS=120
FAST_SQL_TOTAL_TIMEOUT_SECONDS=240
```

Restart the application after changing settings. Routing, planning, SQL generation, and response generation share the local endpoint. The structured routing/planning adapter uses `tool_choice="required"` because this LM Studio runtime rejects a named tool-choice object. Plan validation remains enabled.

The current planner can exceed 23,000 prompt tokens, so 16K context is insufficient. Larger context does not guarantee that a 7B model will produce a valid or correct plan. See `artifacts/local-baseline-20261101` for development test results, including failures. These are smoke tests, not a controlled study or a reproduction of another paper's reported accuracy.
