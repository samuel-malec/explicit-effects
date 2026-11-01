import subprocess
import tempfile
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "evaluation" / "reproduce.sh"

#: A provenance.txt as provenance.sh writes it for two trees copied by sync-pontos.sh, both exactly a commit.
CLEAN = """\
recorded: 2026-10-29T12:00:00+01:00 on pontos04.fi.muni.cz
tool, a copy made by sync-pontos.sh (/home/xmalec/explicit-effects):
    synced: 2026-10-29T11:59:00+01:00 from xmalec:/home/xmalec/explicit-effects
    commit: af584b11c5b2c4757fcefc1a73646cff3207d8f1 (petclinic) graal: point the submodule at the streamed export and the tool cleanup
    uncommitted: 0 tracked files changed, 0 untracked
    diff-sha256: e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855
fork, a copy made by sync-pontos.sh (/home/xmalec/graal):
    synced: 2026-10-29T11:59:10+01:00 from xmalec:/home/xmalec/graal
    commit: 07363cb42cc1e87c124fd23bcf762515c3730357 (side-effect-analysis) side-effect-analysis: stop the tool when the image generator ends first
    uncommitted: 0 tracked files changed, 0 untracked
    diff-sha256: e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855
builder: /home/xmalec/graal/sdk/mxbuild/linux-amd64/GRAALVM_41ABF4132D_JAVA25/graalvm-41abf4132d-java25-25.5.5-dev
    svm.jar: built 2026-10-29T01:30:54+01:00, 32711616 bytes
    pointsto.jar: built 2026-10-29T01:30:54+01:00, 2355911 bytes
"""


def _decide(text: str) -> tuple[int, str]:
    """The script's decision on a provenance.txt: its exit status and what it says."""
    with tempfile.TemporaryDirectory() as directory:
        file = Path(directory) / "provenance.txt"
        file.write_text(text)
        done = subprocess.run(["bash", str(SCRIPT), "--check", str(file)], capture_output=True, text=True)
        return done.returncode, done.stdout + done.stderr


def check_code_that_is_exactly_a_commit_is_accepted() -> None:
    """The control for the refusals below: they are not refusals of everything."""
    status, said = _decide(CLEAN)
    assert status == 0, said
    print("ok   two trees that are exactly a commit, with a builder made from them, are accepted")


def check_changed_tracked_files_are_refused() -> None:
    """Also a count of more than one digit, and a change in the fork alone."""
    for count in ("1", "2", "12"):
        status, said = _decide(CLEAN.replace("uncommitted: 0 tracked", f"uncommitted: {count} tracked", 1))
        assert status == 1 and f"uncommitted: {count} tracked" in said, (count, said)
    head, _, tail = CLEAN.rpartition("uncommitted: 0 tracked")  # the fork's line is the last
    status, said = _decide(head + "uncommitted: 3 tracked" + tail)
    assert status == 1 and "uncommitted: 3 tracked" in said, said
    print("ok   changed tracked files in either tree are refused")


def check_untracked_files_are_refused() -> None:
    status, said = _decide(CLEAN.replace("0 tracked files changed, 0 untracked", "0 tracked files changed, 4 untracked", 1))
    assert status == 1 and "4 untracked" in said, said
    print("ok   untracked files are refused")


def check_a_builder_older_than_the_sources_is_refused() -> None:
    warning = "WARNING: the fork's sources are newer than the builder's svm.jar, so the images lack those changes (rebuild with mx build):\n    /home/xmalec/graal/Some.java\n"
    status, said = _decide(CLEAN + warning)
    assert status == 1 and "WARNING" in said, said
    print("ok   a builder older than the fork's sources is refused")


def check_a_tree_without_a_stamp_is_refused() -> None:
    text = CLEAN.split("fork, a copy")[0] + "fork (/home/xmalec/graal): no history and no stamp\n"
    status, said = _decide(text)
    assert status == 1 and "no history and no stamp" in said, said
    print("ok   a tree that says nothing of where it is from is refused")
