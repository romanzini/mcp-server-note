from __future__ import annotations
"""Orquestra o fluxo notes_chat reutilizável entre MCP server e API web.

Contrato de saída:
{
  success: bool,
  text: str,
  actions: [ { tool, args, result } ],
  synthesized: bool
}
"""
from typing import Any, Callable, Dict, List, Optional
import json
import logging
from .openrouter_client import chat_with_tools

logger = logging.getLogger("mcp_notes.orchestrator")

async def run_notes_chat(
    prompt: str,
    *,
    model: Optional[str] = None,
    params: Dict[str, Any] | None = None,
    chat_func: Callable[..., Any] | None = None,
    add_note_func: Callable[..., Dict[str, Any]] | None = None,
    search_notes_func: Callable[..., Dict[str, Any]] | None = None,
) -> Dict[str, Any]:
    if not prompt or not str(prompt).strip():
        raise ValueError("prompt vazio")
    params = params or {}
    temperature = float(params.get("temperature", 0.2))
    max_tokens = int(params.get("max_tokens", 400))
    timeout_seconds = float(params.get("timeout_seconds", 60))
    chat_callable = chat_func or chat_with_tools
    draft_text, planned_actions = await chat_callable(
        prompt,
        model=model,
        temperature=temperature,
        max_tokens=max_tokens,
        timeout=timeout_seconds,
    )
    executed: List[Dict[str, Any]] = []
    for act in planned_actions:
        tool = act.get("tool")
        args = act.get("args") or {}
        if tool == "add_note" and add_note_func:
            res = add_note_func(args.get("content"), args.get("title"), args.get("tags") or [])
        elif tool == "search_notes" and search_notes_func:
            res = search_notes_func(args.get("query"), args.get("title"), args.get("tags") or [])
            try:
                if res.get("success") and isinstance(res.get("data"), dict):
                    results = res["data"].get("results")
                    if isinstance(results, list) and len(results) > 10:
                        res["data"]["results"] = results[:10]
                        res["data"]["truncated_results"] = True
            except Exception:  # pragma: no cover
                pass
        else:
            res = {"success": False, "error": "tool not supported"}
        executed.append({"tool": tool, "args": args, "result": res})
    final_text = draft_text
    synthesized = False
    if executed:
        ctx_parts = []
        for ex in executed:
            res = ex["result"]
            res_str = json.dumps(res, ensure_ascii=False)[:800]
            ctx_parts.append(f"Ferramenta={ex['tool']}: args={json.dumps(ex['args'], ensure_ascii=False)} resultado={res_str}")
        tool_context = "\n".join(ctx_parts)
        synth_prompt = (
            f"O usuário pediu: {prompt}\n\n"
            f"Resultados das ferramentas executadas:\n{tool_context}\n\n"
            "Produza uma resposta final concisa em português para o usuário, incorporando os dados relevantes."
        )
        final_text, _ = await chat_callable(
            synth_prompt,
            model=model,
            temperature=0.2,
            max_tokens=max_tokens,
            timeout=timeout_seconds,
            max_tool_passes=1,
        )
        synthesized = True
    return {"success": True, "text": final_text, "actions": executed, "synthesized": synthesized}
