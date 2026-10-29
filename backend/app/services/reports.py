import io
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import (
    HRFlowable,
    KeepTogether,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)


def _paragraph(value: object, style: ParagraphStyle) -> Paragraph:
    text = escape(str(value or "Not provided")).replace("\n", "<br/>")
    return Paragraph(text, style)


def generate_pdf_report(report: dict) -> bytes:
    output = io.BytesIO()
    document = SimpleDocTemplate(
        output,
        pagesize=A4,
        rightMargin=19 * mm,
        leftMargin=19 * mm,
        topMargin=17 * mm,
        bottomMargin=17 * mm,
        title=f"Interview practice report - {report.get('title', 'Practice interview')}",
        author="LLM Interview Copilot",
    )
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(
        name="ReportTitle",
        parent=styles["Title"],
        alignment=TA_CENTER,
        textColor=colors.HexColor("#5143c8"),
        fontSize=20,
        leading=25,
        spaceAfter=8,
    ))
    styles.add(ParagraphStyle(name="Question", parent=styles["Heading2"], fontSize=12, leading=16, spaceBefore=10, spaceAfter=6))
    styles.add(ParagraphStyle(name="SectionLabel", parent=styles["Heading3"], fontSize=9, leading=12, spaceBefore=7, spaceAfter=3))
    styles.add(ParagraphStyle(name="BodySmall", parent=styles["BodyText"], fontSize=9, leading=13, spaceAfter=5))
    styles.add(ParagraphStyle(name="Meta", parent=styles["BodyText"], fontSize=9, textColor=colors.HexColor("#606174"), alignment=TA_CENTER, leading=13))

    completed = report.get("completed_at") or report.get("created_at") or "Unknown date"
    story = [
        _paragraph("Interview Practice Report", styles["ReportTitle"]),
        _paragraph(report.get("title", "Practice interview"), styles["Heading2"]),
        _paragraph(
            f"Date: {completed}  |  Mode: {report.get('mode', 'mixed')}  |  "
            f"Difficulty: {report.get('difficulty', 'intermediate')}",
            styles["Meta"],
        ),
        _paragraph(f"Overall practice score: {report.get('average_score', '—')} / 10", styles["Meta"]),
        Spacer(1, 5 * mm),
        HRFlowable(width="100%", thickness=0.7, color=colors.HexColor("#dedcf2")),
        Spacer(1, 3 * mm),
    ]

    answers = report.get("answers", [])
    for index, item in enumerate(answers, start=1):
        evaluation = item.get("evaluation") or {}
        blocks = [
            _paragraph(f"Question {index}: {item.get('question', '')}", styles["Question"]),
            _paragraph("Candidate answer", styles["SectionLabel"]),
            _paragraph(item.get("answer", ""), styles["BodySmall"]),
        ]
        category_scores = evaluation.get("category_scores") or {}
        score_data = [["Overall", "Technical", "Relevance", "Depth", "Clarity", "Examples"]]
        score_data.append([
            f"{evaluation.get('overall_score', '—')}/10",
            *[f"{category_scores.get(name, '—')}/10" for name in (
                "technical_correctness", "relevance", "depth", "clarity", "examples"
            )],
        ])
        table = Table(score_data, colWidths=[25 * mm, 27 * mm, 24 * mm, 19 * mm, 22 * mm, 22 * mm], repeatRows=1)
        table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#f0effb")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.HexColor("#5143c8")),
            ("FONTNAME", (0, 0), (-1, -1), "Helvetica"),
            ("FONTSIZE", (0, 0), (-1, -1), 7.5),
            ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#dedcf2")),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("LEFTPADDING", (0, 0), (-1, -1), 5),
            ("RIGHTPADDING", (0, 0), (-1, -1), 5),
            ("TOPPADDING", (0, 0), (-1, -1), 5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ]))
        blocks.extend([Spacer(1, 2 * mm), table])
        for label, key in (
            ("Strengths", "strengths"),
            ("Missing concepts", "missing_concepts"),
            ("Incorrect or unsupported statements", "unsupported_statements"),
        ):
            values = evaluation.get(key) or []
            blocks.append(_paragraph(label, styles["SectionLabel"]))
            blocks.append(_paragraph(" • ".join(values) if values else "None reported.", styles["BodySmall"]))
        blocks.append(_paragraph("Improvement suggestion / sample answer", styles["SectionLabel"]))
        blocks.append(_paragraph(evaluation.get("improved_answer", ""), styles["BodySmall"]))
        follow_up = evaluation.get("follow_up_question")
        if follow_up:
            blocks.extend([
                _paragraph("Suggested follow-up question", styles["SectionLabel"]),
                _paragraph(follow_up, styles["BodySmall"]),
            ])
        story.append(KeepTogether(blocks))
        story.append(Spacer(1, 3 * mm))

    if not answers:
        story.append(_paragraph("No answers were submitted in this interview.", styles["BodySmall"]))
    story.extend([
        Spacer(1, 4 * mm),
        HRFlowable(width="100%", thickness=0.5, color=colors.HexColor("#dedcf2")),
        Spacer(1, 2 * mm),
        _paragraph(
            report.get("score_notice", "Practice feedback only; not an authoritative assessment."),
            styles["Meta"],
        ),
    ])
    document.build(story)
    return output.getvalue()
