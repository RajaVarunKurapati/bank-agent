"""
Discovery loop: an LLM drives the live surface to accomplish a goal.
observe -> decide (model picks one tool) -> act -> repeat.
Every turn is logged to evidence/. The model is ONLY in the loop here.
LLM: Groq (OpenAI-compatible chat + function calling).
"""
import sys, os, json, datetime
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
from groq import Groq, BadRequestError
from driver.surface_driver import SurfaceDriver

load_dotenv()
client = Groq(api_key=os.environ["GROQ_API_KEY"])
MODEL = "qwen/qwen3.8-27b"   # clean tool-calling; gpt-oss emits phantom tool names on Groq
MAX_STEPS = 12

TOOLS = [
    {"type": "function", "function": {
        "name": "navigate", "description": "Go to a URL.",
        "parameters": {"type": "object",
            "properties": {"url": {"type": "string"}}, "required": ["url"]}}},
    {"type": "function", "function": {
        "name": "type_text",
        "description": "Type a value into a field, identified by its role and/or nearby label text.",
        "parameters": {"type": "object", "properties": {
            "value": {"type": "string"},
            "role": {"type": "string", "description": "e.g. textbox"},
            "name": {"type": "string", "description": "accessible name/label, if any"},
        }, "required": ["value"]}}},
    {"type": "function", "function": {
        "name": "click",
        "description": "Click a control, identified by its visible name/text or role.",
        "parameters": {"type": "object", "properties": {
            "name": {"type": "string", "description": "button/link text, e.g. Search"},
            "role": {"type": "string"},
        }}}},
    {"type": "function", "function": {
        "name": "read",
        "description": "Read the current page text (use to extract requested data).",
        "parameters": {"type": "object", "properties": {}}}},
    {"type": "function", "function": {
        "name": "finish",
        "description": "Goal is complete. Provide a short result summary and any extracted data.",
        "parameters": {"type": "object", "properties": {
            "summary": {"type": "string"},
            "extracted": {"type": "string", "description": "JSON string of any extracted data"},
        }, "required": ["summary"]}}},
]

SYSTEM = """You are an automation agent operating a legacy bank web app by reading its
accessibility tree and taking ONE action at a time via the provided tools. Always call
exactly one tool per turn, using only the tool names provided. When the goal is achieved,
call finish with a summary and any data you were asked to extract. Do not guess data you
have not read."""


def _salvage(err):
    """Some models mislabel the tool (e.g. 'commentary'/'json'); Groq rejects it 400 with
    the intended arguments in 'failed_generation'. If it looks like a finish, recover it."""
    body = getattr(err, "body", None)
    if not isinstance(body, dict):
        return None
    err_obj = body.get("error", body)
    fg = err_obj.get("failed_generation") if isinstance(err_obj, dict) else None
    if not fg:
        return None
    try:
        obj = json.loads(fg)
        args = obj.get("arguments", obj)
        if isinstance(args, str):
            args = json.loads(args)
        if isinstance(args, dict) and "summary" in args:
            return args
    except Exception:
        return None
    return None


def run(goal, start_url, run_dir):
    os.makedirs(run_dir, exist_ok=True)
    log = []
    driver = SurfaceDriver(headless=False)
    driver.navigate(start_url)

    messages = [
        {"role": "system", "content": SYSTEM},
        {"role": "user", "content":
            f"Goal: {goal}\nStart URL: {start_url}\n"
            f"Current page accessibility tree:\n{driver.observe()['elements']}"},
    ]

    result = None
    for step in range(1, MAX_STEPS + 1):
        try:
            resp = client.chat.completions.create(
                model=MODEL, messages=messages, tools=TOOLS, tool_choice="auto",
                max_tokens=800, temperature=0)
        except BadRequestError as e:
            salvaged = _salvage(e)
            if salvaged is not None:
                log.append({"step": step, "reasoning": "recovered malformed tool call",
                            "action": "finish", "args": salvaged,
                            "observation": "finished (salvaged from tool_use_failed)"})
                result = salvaged
                break
            raise

        msg = resp.choices[0].message
        reasoning = msg.content or ""

        if not msg.tool_calls:
            log.append({"step": step, "note": "no tool call", "reasoning": reasoning})
            break

        call = msg.tool_calls[0]
        action = call.function.name
        if action in ("commentary", "json"):   # phantom names -> treat as finish
            action = "finish"
        try:
            args = json.loads(call.function.arguments or "{}")
        except Exception:
            args = {}

        entry = {"step": step, "reasoning": reasoning, "action": action, "args": args}

        try:
            if action == "navigate":
                driver.navigate(args["url"]); observation = "navigated"
            elif action == "type_text":
                driver.type(args["value"], role=args.get("role"), name=args.get("name"))
                observation = "typed"
            elif action == "click":
                driver.click(role=args.get("role"), name=args.get("name"))
                driver.page.wait_for_timeout(800); observation = "clicked"
            elif action == "read":
                observation = driver.read_text()
            elif action == "finish":
                result = args; entry["observation"] = "finished"
                log.append(entry); break
            else:
                observation = f"unknown action {action}"
        except Exception as e:
            observation = f"ERROR: {e}"

        entry["observation"] = observation[:500]
        log.append(entry)

        messages.append({
            "role": "assistant", "content": reasoning,
            "tool_calls": [{
                "id": call.id, "type": "function",
                "function": {"name": call.function.name,
                             "arguments": call.function.arguments}}]})
        messages.append({
            "role": "tool", "tool_call_id": call.id,
            "content": f"{observation[:1500]}\n\nCurrent page:\n{driver.observe()['elements']}"})

    driver.screenshot(os.path.join(run_dir, "final_state.png"))
    with open(os.path.join(run_dir, "discovery_log.json"), "w") as f:
        json.dump({"goal": goal, "start_url": start_url,
                   "result": result, "steps": log}, f, indent=2)
    driver.close()
    print(f"\nDone. Result: {result}\nEvidence saved to {run_dir}")
    return result, log


if __name__ == "__main__":
    stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    run(
        goal="Look up member 12345 and read their current savings balance.",
        start_url="http://127.0.0.1:5000",
        run_dir=os.path.join("evidence", f"discovery_{stamp}"),
    )