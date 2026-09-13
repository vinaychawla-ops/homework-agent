"""Sample Math and Science assignments with answer keys (demo data)."""

import json
import os
import re
from typing import Dict, List, Optional

from .models import Assignment, Question


def math_assignment() -> Assignment:
    return Assignment(
        id="math-fractions-01",
        title="Fractions & Basic Algebra",
        subject="math",
        teacher_name="Ms. Rivera",
        teacher_email="rivera.teacher@example.edu",
        questions=[
            Question(
                id="Q1",
                subject="math",
                prompt="Simplify: 6/8. Write your answer as a fraction in lowest terms.",
                question_type="numeric",
                correct_answer="3/4",
                correct_explanation="Divide numerator and denominator by their greatest common divisor, 2: 6/8 = 3/4.",
            ),
            Question(
                id="Q2",
                subject="math",
                prompt="Solve for x: 2x + 6 = 14",
                question_type="numeric",
                correct_answer="4",
                correct_explanation="Subtract 6 from both sides: 2x = 8, then divide by 2: x = 4.",
            ),
            Question(
                id="Q3",
                subject="math",
                prompt="Which of the following equals 2^3? (a) 6  (b) 8  (c) 9",
                question_type="multiple_choice",
                correct_answer="b",
                correct_explanation="2^3 = 2 x 2 x 2 = 8, which is option (b).",
            ),
            Question(
                id="Q4",
                subject="math",
                prompt="Expand: (x + 2)(x + 3)",
                question_type="expression",
                correct_answer="x^2 + 5x + 6",
                correct_explanation="Use FOIL: x*x + 3x + 2x + 6 = x^2 + 5x + 6.",
            ),
            Question(
                id="Q5",
                subject="math",
                prompt="A pizza is cut into 8 equal slices. You eat 3 slices. What fraction of the pizza is left? Explain in one or two sentences.",
                question_type="short_answer",
                correct_answer="5/8 (five eighths) of the pizza is left, because 8 - 3 = 5 slices remain.",
                correct_explanation="8 - 3 = 5 slices remain out of 8, so 5/8 of the pizza is left.",
                key_concepts=["5/8", "8 - 3", "5 slices", "five eighths"],
                points=2.0,
            ),
        ],
    )


def science_assignment() -> Assignment:
    return Assignment(
        id="sci-water-cycle-01",
        title="The Water Cycle",
        subject="science",
        teacher_name="Mr. Chen",
        teacher_email="chen.teacher@example.edu",
        questions=[
            Question(
                id="Q1",
                subject="science",
                prompt="Which process turns liquid water into water vapor? (a) condensation (b) evaporation (c) precipitation",
                question_type="multiple_choice",
                correct_answer="b",
                correct_explanation="Evaporation is the process by which liquid water becomes water vapor due to heat energy.",
            ),
            Question(
                id="Q2",
                subject="science",
                prompt="In one or two sentences, explain why puddles disappear on a hot sunny day.",
                question_type="short_answer",
                correct_answer="The Sun's heat gives water molecules energy so liquid water evaporates into water vapor, which mixes into the air.",
                correct_explanation="Heat from the Sun increases the kinetic energy of water molecules at the puddle's surface until they escape as water vapor (evaporation).",
                key_concepts=["heat", "evaporat", "water vapor", "energy"],
                points=2.0,
            ),
            Question(
                id="Q3",
                subject="science",
                prompt="Name the process by which water vapor cools and turns back into liquid droplets in clouds.",
                question_type="short_answer",
                correct_answer="Condensation.",
                correct_explanation="Condensation is the cooling of water vapor into liquid droplets, forming clouds.",
                key_concepts=["condensation"],
            ),
            Question(
                id="Q4",
                subject="science",
                prompt="About what percentage of Earth's water is fresh water available for drinking? (a) 1% (b) 25% (c) 75%",
                question_type="multiple_choice",
                correct_answer="a",
                correct_explanation="Only about 2.5% of Earth's water is fresh, and most of that is locked in ice; roughly 1% is readily available.",
            ),
        ],
    )


def rainbow_assignment() -> Assignment:
    return Assignment(
        id="sci-rainbows-01",
        title="Rainbows",
        subject="science",
        teacher_name="Mr. Chen",
        teacher_email="chen.teacher@example.edu",
        questions=[
            Question(
                id="Q1",
                subject="science",
                prompt="How is a rainbow created in the sky?",
                question_type="short_answer",
                correct_answer="A rainbow appears when sunlight shines through raindrops while it is raining: the sunlight is refracted and reflected inside the drops and spreads out into colors.",
                correct_explanation="A rainbow needs rain and sunshine at the same time. Sunlight entering the raindrops is refracted (bent), reflected inside the drop, and dispersed into the colors of the rainbow.",
                key_concepts=["sunlight", "rain", "shine"],
            ),
        ],
    )


ASSIGNMENTS = {
    "math-fractions-01": math_assignment(),
    "sci-water-cycle-01": science_assignment(),
    "sci-rainbows-01": rainbow_assignment(),
}


def get_assignment(assignment_id: str) -> Assignment:
    try:
        return all_assignments()[assignment_id]
    except KeyError:
        raise KeyError(
            f"Unknown assignment {assignment_id!r}. "
            f"Available: {sorted(all_assignments())}"
        )


def resolve_assignment(ref: str) -> Assignment:
    """Resolve a free-text assignment reference to an Assignment.

    Accepts the assignment id or title, case-insensitively, or any
    unambiguous substring of a title (e.g. "rainbows", "water", "fractions").
    Raises KeyError listing the available assignments when nothing matches.
    """
    key = (ref or "").strip().lower()
    if not key:
        raise KeyError("No assignment was named.")
    known = all_assignments()
    for assignment in known.values():
        if key == assignment.id.lower() or key == assignment.title.lower():
            return assignment
    partial = [a for a in known.values() if key in a.title.lower()]
    if len(partial) == 1:
        return partial[0]
    available = ", ".join(f"{a.title} ({a.id})" for a in known.values())
    raise KeyError(f"Unknown assignment {ref!r}. Available: {available}")


def _signal_words(text: str) -> set:
    """Content words (4+ letters) used as assignment-detection signals."""
    return set(re.findall(r"[a-z]{4,}", (text or "").lower()))


def detect_assignment(text: str) -> Optional[Assignment]:
    """Guess which assignment a submission belongs to from its text.

    Scores each assignment by how many of its signal words (taken from
    question prompts and key concepts) appear in the text. Each signal is
    weighted by 1/(number of assignments that use it), so generic words
    like "explain" that appear in several assignments don't dominate.

    Returns the winning assignment when it has a clear lead (weighted
    score >= 2 and strictly ahead of the runner-up); otherwise None.
    """
    haystack = (text or "").lower()
    if not haystack.strip():
        return None
    scored = []
    for assignment in all_assignments().values():
        signals = set()
        for question in assignment.questions:
            signals.update(_signal_words(question.prompt))
            for concept in question.key_concepts or []:
                signals.update(_signal_words(concept))
        scored.append((assignment, signals))
    rarity = {}
    for _, signals in scored:
        for word in signals:
            rarity[word] = rarity.get(word, 0) + 1
    ranked = []
    for assignment, signals in scored:
        score = sum(1.0 / rarity[word] for word in signals if word in haystack)
        ranked.append((score, assignment))
    ranked.sort(key=lambda item: item[0], reverse=True)
    (best_score, best), (runner_up_score, _) = ranked[0], ranked[1]
    if best_score >= 2.0 and best_score > runner_up_score:
        return best
    return None


# ---------------------------------------------------------------------------
# Teacher-uploaded assignments (persisted as JSON)
# ---------------------------------------------------------------------------

#: Directory holding teacher-uploaded assignments as ``<id>.json`` files.
#: Override with the ``HOMEWORK_ASSIGNMENTS_DIR`` environment variable (the
#: Modal deployment points it at a persistent volume).
ASSIGNMENTS_DIR_ENV = "HOMEWORK_ASSIGNMENTS_DIR"


def assignments_dir() -> str:
    return os.environ.get(
        ASSIGNMENTS_DIR_ENV,
        os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "assignments"),
    )


def question_to_dict(question: Question) -> Dict:
    return {
        "id": question.id,
        "subject": question.subject,
        "prompt": question.prompt,
        "question_type": question.question_type,
        "correct_answer": question.correct_answer,
        "correct_explanation": question.correct_explanation,
        "key_concepts": list(question.key_concepts),
        "points": question.points,
        "tolerance": question.tolerance,
        "pass_threshold": question.pass_threshold,
    }


def question_from_dict(data: Dict) -> Question:
    return Question(
        id=data["id"],
        subject=data["subject"],
        prompt=data.get("prompt", ""),
        question_type=data["question_type"],
        correct_answer=data["correct_answer"],
        correct_explanation=data.get(
            "correct_explanation", f"The correct answer is {data['correct_answer']}."
        ),
        key_concepts=list(data.get("key_concepts") or []),
        points=float(data.get("points", 1.0)),
        tolerance=float(data.get("tolerance", 1e-6)),
        pass_threshold=float(data.get("pass_threshold", 0.7)),
    )


def assignment_to_dict(assignment: Assignment) -> Dict:
    return {
        "id": assignment.id,
        "title": assignment.title,
        "subject": assignment.subject,
        "teacher_name": assignment.teacher_name,
        "teacher_email": assignment.teacher_email,
        "questions": [question_to_dict(q) for q in assignment.questions],
    }


def assignment_from_dict(data: Dict) -> Assignment:
    return Assignment(
        id=data["id"],
        title=data["title"],
        subject=data["subject"],
        teacher_name=data.get("teacher_name", ""),
        teacher_email=data.get("teacher_email", ""),
        questions=[question_from_dict(q) for q in data["questions"]],
    )


def load_custom_assignments() -> Dict[str, Assignment]:
    """Load teacher-uploaded assignments from the JSON directory."""
    custom: Dict[str, Assignment] = {}
    directory = assignments_dir()
    if not os.path.isdir(directory):
        return custom
    for filename in sorted(os.listdir(directory)):
        if not filename.endswith(".json"):
            continue
        path = os.path.join(directory, filename)
        try:
            with open(path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            assignment = assignment_from_dict(data)
        except (OSError, ValueError, KeyError, TypeError):
            continue  # skip corrupt files; built-ins keep working
        custom[assignment.id] = assignment
    return custom


def all_assignments() -> Dict[str, Assignment]:
    """Built-in plus teacher-uploaded assignments (custom ids win on clash)."""
    return {**ASSIGNMENTS, **load_custom_assignments()}


def save_assignment(assignment: Assignment) -> str:
    """Persist a teacher-uploaded assignment as JSON; returns its file path."""
    directory = assignments_dir()
    os.makedirs(directory, exist_ok=True)
    path = os.path.join(directory, f"{assignment.id}.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(assignment_to_dict(assignment), fh, indent=2)
    return path


def slugify(title: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", title.strip().lower()).strip("-")
    return slug or "assignment"


def unique_assignment_id(title: str) -> str:
    """Generate a ``custom-<slug>`` id not used by any known assignment."""
    known = all_assignments()
    base = f"custom-{slugify(title)}"
    candidate = base
    counter = 2
    while candidate in known:
        candidate = f"{base}-{counter}"
        counter += 1
    return candidate


def title_in_use(title: str) -> bool:
    wanted = title.strip().lower()
    return any(a.title.strip().lower() == wanted for a in all_assignments().values())


def build_assignment(
    key_questions: List,
    *,
    title: str,
    subject: str,
    teacher_name: str = "",
    teacher_email: str = "",
) -> Assignment:
    """Build an Assignment from parsed answer-key questions."""
    from .answer_key import KeyQuestion  # deferred: avoids a circular import

    questions: List[Question] = []
    for kq in key_questions:
        assert isinstance(kq, KeyQuestion)
        questions.append(
            Question(
                id=kq.qid,
                subject=subject,
                prompt=kq.prompt,
                question_type=kq.question_type,
                correct_answer=kq.answer,
                correct_explanation=kq.explanation,
                key_concepts=list(kq.key_concepts),
                points=kq.points,
            )
        )
    return Assignment(
        id=unique_assignment_id(title),
        title=title.strip(),
        subject=subject,
        teacher_name=teacher_name.strip(),
        teacher_email=teacher_email.strip(),
        questions=questions,
    )
