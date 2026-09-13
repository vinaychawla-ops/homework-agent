"""Sample Math and Science assignments with answer keys (demo data)."""

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
        return ASSIGNMENTS[assignment_id]
    except KeyError:
        raise KeyError(f"Unknown assignment {assignment_id!r}. Available: {sorted(ASSIGNMENTS)}")


def resolve_assignment(ref: str) -> Assignment:
    """Resolve a free-text assignment reference to an Assignment.

    Accepts the assignment id or title, case-insensitively, or any
    unambiguous substring of a title (e.g. "rainbows", "water", "fractions").
    Raises KeyError listing the available assignments when nothing matches.
    """
    key = (ref or "").strip().lower()
    if not key:
        raise KeyError("No assignment was named.")
    for assignment in ASSIGNMENTS.values():
        if key == assignment.id.lower() or key == assignment.title.lower():
            return assignment
    partial = [a for a in ASSIGNMENTS.values() if key in a.title.lower()]
    if len(partial) == 1:
        return partial[0]
    available = ", ".join(f"{a.title} ({a.id})" for a in ASSIGNMENTS.values())
    raise KeyError(f"Unknown assignment {ref!r}. Available: {available}")
