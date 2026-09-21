"""Regenerate examples/academic/thesis_sample.docx.

    python examples/build_docx_example.py

The DOCX is generated so the repository does not depend on a binary edited by hand.
It mirrors examples/academic/draft.md (same deliberate problems), as a Word file.
"""

from __future__ import annotations

from pathlib import Path

import docx

OUT = Path(__file__).parent / "academic" / "thesis_sample.docx"


def main() -> None:
    d = docx.Document()
    d.add_heading("Antenatal Care Utilisation in Rural Districts", 0)

    d.add_heading("Introduction", 1)
    d.add_paragraph(
        "Antenatal care reduces maternal and newborn risk, yet attendance in rural districts "
        "remains low. This chapter reports a mixed-methods study of the barriers women describe "
        "and the patterns visible in clinic records."
    )

    d.add_heading("Research Questions", 1)
    d.add_paragraph(
        "What factors are associated with utilisation of antenatal care in rural districts?"
    )
    d.add_paragraph("How do travel distance and cost affect attendance at antenatal clinics?")

    d.add_heading("Methodology", 1)
    d.add_paragraph(
        "We reviewed 1,240 clinic records and interviewed 36 women — a purposive sample "
        "drawn from three districts."
    )
    table = d.add_table(rows=3, cols=2)
    table.style = "Table Grid"
    for r, row in enumerate([["District", "Interviews"], ["North", "12"], ["South", "24"]]):
        for c, value in enumerate(row):
            table.cell(r, c).text = value

    d.add_heading("Findings", 1)
    d.add_paragraph("Attendance was highest where transport support existed.")

    d.add_heading("Conclusion", 1)
    d.add_paragraph("Transport support is the most promising lever identified in this study.")

    d.add_heading("References", 1)
    for ref in (
        "Adeyemi, T. (2024). Clinic access in rural districts. Journal of Public Health, 12(3), 45-60.",
        "Okafor, N. and Bello, S. (2023). Transport costs and care seeking. Health Policy Review, 8(1), 12-30.",
        "Smith, J. (2022). Measuring attendance. Global Health Notes, 5(2), 101-115.",
    ):
        d.add_paragraph(ref)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    d.save(str(OUT))
    print(f"Wrote {OUT}")


if __name__ == "__main__":
    main()
