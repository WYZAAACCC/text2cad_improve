from pathlib import Path

MODELS = Path(r"E:\text_to_cad_improve\auto_detection_process\integrations\engineering_tools\src\seekflow_engineering_tools\generative_cad\llm\models.py")
PIPE = Path(r"E:\text_to_cad_improve\auto_detection_process\_main_experiment\pipeline.py")
AGENT = Path(r"E:\text_to_cad_improve\auto_detection_process\app\text-to-cad\server\agentic_l2.py")

def edit(p, old_lines, new_lines):
    s = p.read_text(encoding="utf-8")
    old = "\n".join(old_lines)
    new = "\n".join(new_lines)
    n = s.count(old)
    if n != 1:
        raise SystemExit("not unique: %s count=%d" % (p.name, n))
    p.write_text(s.replace(old, new), encoding="utf-8")

# 1. models.py: add api_key_env
edit(MODELS, [
    "    timeout_s: int = 90",
    "    max_retries: int = 2",
], [
    "    timeout_s: int = 90",
    "    max_retries: int = 2",
    "    api_key_env: str = \"DEEPSEEK_API_KEY\"",
])

# 2. pipeline: pass api_key_env into LlmModelConfig
edit(PIPE, [
    "        temperature=llm_cfg.temperature if llm_cfg.temperature is not None else 0.3,",
    "        seed=llm_cfg.seed,",
    "    )",
], [
    "        temperature=llm_cfg.temperature if llm_cfg.temperature is not None else 0.3,",
    "        seed=llm_cfg.seed,",
    "        api_key_env=llm_cfg.api_key_env,",
    "    )",
])

# 3. agentic_l2: profile tool loop env
edit(AGENT, [
    "    api_key = os.environ.get(\"DEEPSEEK_API_KEY\", \"\")",
    "    if not api_key:",
    "        raise LlmToolCallError(\"DEEPSEEK_API_KEY not set for profile tool loop\",",
    "                               code=\"provider_no_auth\")",
], [
    "    _api_key_env = getattr(model_config, \"api_key_env\", \"DEEPSEEK_API_KEY\")",
    "    api_key = os.environ.get(_api_key_env, \"\")",
    "    if not api_key:",
    "        raise LlmToolCallError(f\"{_api_key_env} not set for profile tool loop\",",
    "                               code=\"provider_no_auth\")",
])

# 4. agentic_l2: design tool loop env
edit(AGENT, [
    "    api_key = os.environ.get(\"DEEPSEEK_API_KEY\", \"\")",
    "    if not api_key:",
    "        raise LlmToolCallError(\"DEEPSEEK_API_KEY not set for design tool loop\",",
    "                               code=\"provider_no_auth\")",
], [
    "    _api_key_env = getattr(model_config, \"api_key_env\", \"DEEPSEEK_API_KEY\")",
    "    api_key = os.environ.get(_api_key_env, \"\")",
    "    if not api_key:",
    "        raise LlmToolCallError(f\"{_api_key_env} not set for design tool loop\",",
    "                               code=\"provider_no_auth\")",
])

