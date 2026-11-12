"""The flow planner — turning a declared flow into executable steps.

Pure, by the porting rule: no Frappe, no network, no backends. The runner in
``services/flow_runner.py`` calls this to answer three questions per step, and
each answer is either a value or a sentence the model can be shown — never an
exception, because a flow that half-ran is exactly the situation in which a
raised exception is least helpful.

The three questions
-------------------
* **Do the caller's arguments fill every placeholder?** A step's arguments may
  embed ``{patient_name}`` — a reference into the flow tool's own schema. A
  placeholder naming a parameter the schema does not declare is checked
  *before* anything runs, because the alternative is discovering it as the
  literal string ``"{patient_name}"`` inside a created document.
* **What are this step's concrete arguments?** Placeholders substituted from
  the caller's arguments, and the wiring from an earlier step's output
  (``from_step``/``from_field``) resolved. A wiring that asks for a field the
  earlier step's output does not carry is a sentence, not a KeyError.
* **How is a completed step undone?** The step's own tool compensation names
  the undo tool (``mechanism="reverse"``); the undo call's arguments are the
  completed step's output fields, narrowed to what the undo tool's schema
  actually declares. A step whose output does not carry what its undo needs
  is an undo that fails honestly and is reported, not guessed.

The output convention
---------------------
A step's ``ToolResult.content`` is read as JSON when it parses as one object;
otherwise the whole content string is the output under the field ``""``. This
is the one convention every extension's create-style handler must meet to be
wired into a flow, and it is written here rather than assumed, because a
convention nobody wrote down is a convention only the first extension uses.
"""

from __future__ import annotations

import json
import re
from typing import Any

from albanna_ai_chat.core.flow import FlowStep
from albanna_ai_chat.core.tools import ToolSpec

#: A placeholder is ``{identifier}`` — the same spelling the healthcare
#: manifest uses, and the same spelling ``str.format`` would eat, which is
#: why substitution is done with a regex on values rather than with
#: ``str.format``: an argument value containing ``{`` from the caller would
#: be a format string the model controls.
PLACEHOLDER = re.compile(r"\{([a-zA-Z_][a-zA-Z0-9_]*)\}")


def placeholder_problems(spec: ToolSpec, arguments: dict[str, Any]) -> list[str]:
    """Every placeholder in the flow that the tool's schema does not declare.

    Checked before anything runs. The schema is the flow tool's own — a
    placeholder is a reference into what the model was *given*, so a name the
    schema does not carry is a name no valid call could ever fill.
    """
    flow = spec.flow
    declared = set((spec.parameters or {}).get("properties") or {})
    problems: list[str] = []
    for index, step in enumerate(flow.steps):
        for value in step.arguments.values():
            if not isinstance(value, str):
                continue
            for match in PLACEHOLDER.finditer(value):
                name = match.group(1)
                if name not in declared:
                    problems.append(
                        f"flow {flow.name!r} step {index} references "
                        f"{{{name}}}, which is not a parameter of {spec.name!r}"
                    )
    return problems


def _substitute(value: Any, arguments: dict[str, Any]) -> Any:
    """Placeholders in a string replaced from the caller's arguments.

    A value that is *entirely* one placeholder is replaced by the argument
    itself — an integer stays an integer, a list stays a list. A value with
    placeholders among other text is interpolated as a string, because that
    is what the step asked for.
    """
    if not isinstance(value, str):
        return value
    match = PLACEHOLDER.fullmatch(value.strip())
    if match:
        name = match.group(1)
        return arguments.get(name, value)
    return PLACEHOLDER.sub(
        lambda m: str(arguments.get(m.group(1), m.group(0))),
        value,
    )


def step_arguments(
    step: FlowStep,
    arguments: dict[str, Any],
    outputs: dict[int, Any],
) -> tuple[dict[str, Any], str]:
    """One step's concrete arguments, or the sentence saying why there are none.

    @param step: the step being planned
    @param arguments: the flow tool's validated arguments
    @param outputs: completed steps' outputs, keyed by step index
    @returns: ``(arguments, error)`` — exactly one is empty
    """
    concrete = {key: _substitute(value, arguments) for key, value in step.arguments.items()}

    if step.from_step is not None:
        output = outputs.get(step.from_step)
        if output is None:
            return {}, (
                f"step {step.tool!r} consumes output from step {step.from_step}, "
                "which has not produced one"
            )
        value = output.get(step.from_field) if isinstance(output, dict) else None
        if value is None:
            return {}, (
                f"step {step.tool!r} reads {step.from_field!r} from step "
                f"{step.from_step}'s output, which does not carry it"
            )
        # The wired value lands in the argument the step named with `into` —
        # a parameter the step's tool declared. Landing it under the field's
        # own name would be an argument a closed schema refuses.
        target = step.into or step.from_field
        concrete[target] = value

    return concrete, ""


def parse_output(content: str) -> Any:
    """A tool result's content, as the output the planner wires between steps.

    An object is the object. Anything else — a plain sentence, a list, JSON
    that is not an object — becomes ``{"": content}``, so a wiring that asks
    for a named field fails with *the field is missing* rather than with a
    parse error, and a wiring that does not ask for a field still works.
    """
    try:
        parsed = json.loads(content)
    except (ValueError, TypeError):
        return {"": content}
    return parsed if isinstance(parsed, dict) else {"": content}


def undo_arguments(
    undo_spec: ToolSpec,
    step_output: Any,
) -> tuple[dict[str, Any], str]:
    """The undo call's arguments, from the completed step's output.

    The undo tool receives the fields of the step's output that its own
    schema declares — ``delete_patient`` wants ``name`` and the created
    patient's output carries ``name``. An undo tool whose needs the output
    does not meet is an undo that would run with half its arguments, and
    that is refused here with a sentence rather than guessed at runtime.
    """
    declared = set((undo_spec.parameters or {}).get("properties") or {})
    required = set((undo_spec.parameters or {}).get("required") or [])
    output = step_output if isinstance(step_output, dict) else {}

    missing = required - set(output)
    if missing:
        return {}, (
            f"the undo tool {undo_spec.name!r} requires "
            f"{', '.join(sorted(missing))}, which the completed step's "
            "output does not carry — the step cannot be undone automatically"
        )

    picked = {key: value for key, value in output.items() if key in declared}
    if not picked:
        return {}, (
            f"the undo tool {undo_spec.name!r} declares no parameter the "
            "completed step's output fills — the step cannot be undone "
            "automatically"
        )
    return picked, ""


def flow_summary(
    flow_name: str,
    steps: list[tuple[str, bool, str]],
) -> str:
    """The one-paragraph account of what a flow did, for the transcript.

    Every step appears — the ones that ran, the one that failed, and whether
    each was undone. A reader who sees "created the patient, undid it"
    knows exactly what exists afterwards: nothing.
    """
    lines = [f"Flow {flow_name!r}:"]
    for tool, ok, note in steps:
        state = "ok" if ok else "FAILED"
        lines.append(f"  {tool}: {state}{f' — {note}' if note else ''}")
    return "\n".join(lines)
