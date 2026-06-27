"""Proposal editing agent — the proposals tab's counterpart to the writeup agent.

One :class:`ProposalSession` per proposal (per-window, any number in parallel):
a sandboxed ``pi`` collaborator whose document is the real ``proposals/<name>.md``,
mounted read-write at ``/proposals`` so its edits land directly in the repo dir.
Conversation + agent log live under ``outputs/07_proposal_studio/<name>/``.
"""

from __future__ import annotations

from pathlib import Path

from src import sandbox
from src.blogpost_studio import DEFAULT_STUDIO_MODEL, DEFAULT_THINKING, DocAgentSession

ROOT = Path(__file__).resolve().parent.parent
PROPOSALS_DIR = ROOT / "proposals"
WORK_ROOT = ROOT / "outputs" / "07_proposal_studio"

SYSTEM_PROMPT = """\
You are collaborating with a researcher on their research proposals (short
markdown plans for empirical/conceptual AI-safety projects).

The proposals directory is mounted read-write at /proposals. The proposal you
are working on together is /proposals/{name}.md — edit that file directly with
your editing tools. The sibling proposals are there as reference for tone,
structure, and scope; do NOT modify any other file unless explicitly asked.

Working style:
- Preserve the author's intent and voice; sharpen, don't replace.
- Make plans concrete: crisp motivation, falsifiable questions, explicit
  experiment steps, expected evidence. Cut filler and repetition.
- If something essential is missing or ambiguous, ask in chat rather than
  inventing facts.
- Keep chat replies short: say what you changed and why, then stop.
"""

POLISH_PROMPT = """\
Clean up and tighten this proposal: fix structure and flow, remove redundancy
and filler, make the plan concrete and unambiguous (motivation, questions,
experiment steps, expected evidence), and keep the author's intent and voice.
Edit the file directly, then summarize your edits in one short paragraph.
"""


class ProposalSession(DocAgentSession):
    """Chat agent that edits one proposal file in place."""

    def __init__(
        self,
        name: str,
        *,
        model: str = DEFAULT_STUDIO_MODEL,
        thinking: str = DEFAULT_THINKING,
    ) -> None:
        self.name = name
        if not (PROPOSALS_DIR / f"{name}.md").is_file():
            raise ValueError(f"no proposal named {name}")
        super().__init__(
            WORK_ROOT / name,
            model=model,
            thinking=thinking,
            system_prompt=SYSTEM_PROMPT.format(name=name),
        )

    @property
    def doc_path(self) -> Path:
        return PROPOSALS_DIR / f"{self.name}.md"

    def _expand(self, message: str) -> str:
        cmd, _, rest = message.partition(" ")
        if cmd == "/polish":
            prompt = POLISH_PROMPT
            if rest.strip():
                prompt += f"\nAdditional instructions from the author:\n{rest.strip()}"
            return prompt
        return message

    def job_spec(self) -> dict:
        return {
            "module": "src.proposal_studio",
            "cls": "ProposalSession",
            "kwargs": {"name": self.name},
            "model": self.model,
            "thinking": self.thinking,
        }

    def _argv(self, prompt: str) -> list[str]:
        return sandbox.build_argv(
            self.work,
            self._inner_argv(prompt),
            extra_binds=((str(PROPOSALS_DIR), "/proposals"),),
        )

    def reset(self) -> None:
        """Forget the conversation. The proposal file itself is never touched."""
        if self.is_running():
            raise RuntimeError("stop the running turn first")
        for p in (self.session_path, self.log_path):
            p.unlink(missing_ok=True)
        self._clear_session_state()

    def state(self) -> dict:
        return {**super().state(), "name": self.name}
