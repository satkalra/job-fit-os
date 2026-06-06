from app.utils.resume_parser import parse_resume


def test_parse_resume_preserves_structured_entries():
    resume = """Jane Doe
jane@example.com | Austin, TX

Summary
Builder of useful software.

Experience
Senior Engineer | Chime | San Francisco, CA | 2022 - Present
- Led platform work.
Software Engineer | Stripe | Remote | 2020 - 2022
- Built payment tooling.
Developer | Acme | Austin, TX | 2018 - 2020
- Shipped APIs.

Projects
Realtime Matching | 2024
- Built matching service.
Resume Tailor | 2023
- Built document pipeline.
Search Index | 2022
- Improved search.

Skills
Python, FastAPI, SQL

Education
B.S. Computer Science | State University | Austin, TX | 2018
"""
    parsed = parse_resume(resume)

    assert len(parsed.jobs) == 3
    assert parsed.jobs[0].title == "Senior Engineer"
    assert parsed.jobs[0].company == "Chime"
    assert len(parsed.projects) == 3
    assert parsed.education[0].school == "State University"
