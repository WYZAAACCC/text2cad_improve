from pathlib import Path

p = Path(r"E:\text_to_cad_improve\auto_detection_process\_main_experiment\parallel_run.py")

def edit(old_lines, new_lines):
    s = p.read_text(encoding="utf-8")
    old = "\n".join(old_lines)
    new = "\n".join(new_lines)
    n = s.count(old)
    if n != 1:
        raise SystemExit("not unique count=%d" % n)
    p.write_text(s.replace(old, new), encoding="utf-8")

edit([
    "    parser.add_argument(\"--no-resume\", action=\"store_true\")",
], [
    "    parser.add_argument(\"--no-resume\", action=\"store_true\")",
    "    parser.add_argument(\"--model\", default=None, help=\"LLM model override\")",
    "    parser.add_argument(\"--base-url\", default=None, help=\"LLM base URL override\")",
    "    parser.add_argument(\"--api-key-env\", default=None, help=\"LLM API key env var override\")",
])

edit([
    "    config = default_experiment_config()",
    "    if args.output:",
], [
    "    config = default_experiment_config()",
    "    if args.model or args.base_url or args.api_key_env:",
    "        config = config.model_copy(update={\"llm\": config.llm.model_copy(update={",
    "            \"model\": args.model or config.llm.model,",
    "            \"base_url\": args.base_url or config.llm.base_url,",
    "            \"api_key_env\": args.api_key_env or config.llm.api_key_env,",
    "        })})",
    "    if args.output:",
])

