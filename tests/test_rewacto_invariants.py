from app.pipeline.rewacto import _preserve_original_structure
from app.schemas.resume import JobEntry, RewrittenResume, ResumeStructure


def test_preserve_original_structure_keeps_job_metadata():
    original = ResumeStructure(
        jobs=[
            JobEntry(
                title="Original Title",
                company="Original Co",
                location="New York, NY",
                dates="2020 - Present",
                bullets=["Old bullet"],
            )
        ]
    )
    rewritten = RewrittenResume(
        summary="Summary",
        jobs=[
            JobEntry(
                title="Changed Title",
                company="Changed Co",
                location="Remote",
                dates="2024",
                bullets=["Rewritten bullet"],
            )
        ],
        skills=["Python"],
    )

    result = _preserve_original_structure(original, rewritten)

    assert result.jobs[0].title == "Original Title"
    assert result.jobs[0].company == "Original Co"
    assert result.jobs[0].dates == "2020 - Present"
    assert result.jobs[0].bullets == ["Rewritten bullet"]
