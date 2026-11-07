from app.fixer import analyze_and_fix_code


def test_fixes_broken_python_syntax_and_verifies_in_sandbox():
    broken_py = (
        "def compute_total(items)\n"
        "    total = sum(items) / len(items)\n"
        "    if total = 10:\n"
        "        print 'Perfect score'\n"
        "    return total\n"
        "print('Result:', compute_total([10, 10])\n"
    )
    res = analyze_and_fix_code("broken_metrics.py", broken_py, "python")
    assert res["initial_sandbox_run"]["exit_code"] != 0
    assert res["verified_sandbox_run"]["exit_code"] == 0
    assert "Result: 10.0" in res["verified_sandbox_run"]["stdout"]
    assert len(res["issues_fixed"]) >= 3
    assert len(res["containment_receipt"]["sha256"]) == 64


def test_fixes_javascript_const_reassignment_and_verifies_in_node_sandbox():
    broken_js = (
        "const totalScore = 80;\n"
        "totalScore += 15;\n"
        "console.log('Updated score:', totalScore\n"
    )
    res = analyze_and_fix_code("score_calc.js", broken_js, "javascript")
    assert res["initial_sandbox_run"]["exit_code"] != 0
    assert res["verified_sandbox_run"]["exit_code"] == 0
    assert "Updated score: 95" in res["verified_sandbox_run"]["stdout"]


def test_containment_gate_blocks_host_escape_and_remediates():
    hostile_py = (
        "import os\n"
        "secret = os.environ.get('VULTR_INFERENCE_API_KEY')\n"
        "data = open('/etc/passwd').read()\n"
    )
    res = analyze_and_fix_code("escape_attempt.py", hostile_py, "python")
    assert res["initial_sandbox_run"]["containment_blocked"] is True
    assert len(res["initial_sandbox_run"]["containment_triggers"]) >= 2
    assert res["verified_sandbox_run"]["exit_code"] == 0
